from __future__ import annotations

import base64
import io
import json
import logging
import re
import time
import zipfile
from pathlib import Path
from typing import Any

import httpx

from app.services.llm_runtime import load_effective_llm_config
from app.utils.docx import extract_text_from_docx
from app.utils.pdf import extract_text_from_pdf
from app.utils.text import normalize_text

logger = logging.getLogger(__name__)

_SUPPORTED_EXTS = {".pdf", ".docx", ".doc", ".txt"}
_PARSER_TOOL_TYPE = "prime-sync"
_INLINE_IMAGE_MARK_RE = re.compile(r"^!\[[^\]]*\]\([^)]+\)\s*$")
_FILE_UNDERSTANDING_MODEL = "glm-4.5v"
_QUALITY_HINTS = (
    "教育背景",
    "实习经历",
    "项目经历",
    "校园经历",
    "工作经历",
    "专业技能",
    "奖项",
    "证书",
    "求职意向",
    "联系方式",
)


def _parser_sync_url(base_url: str) -> str:
    base = str(base_url or "").strip().rstrip("/")
    if not base:
        raise ValueError("llm_base_url_empty")
    if base.endswith("/files/parser/sync"):
        return base
    return f"{base}/files/parser/sync"


def _chat_url(base_url: str) -> str:
    base = str(base_url or "").strip().rstrip("/")
    if not base:
        raise ValueError("llm_base_url_empty")
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def _parser_result_url(base_url: str, task_id: str) -> str:
    base = str(base_url or "").strip().rstrip("/")
    if not base:
        raise ValueError("llm_base_url_empty")
    safe_task_id = str(task_id or "").strip()
    if not safe_task_id:
        return ""
    return f"{base}/files/parser/result/{safe_task_id}/text"


def _guess_mime(ext: str) -> str:
    ext = str(ext or "").lower()
    if ext == ".pdf":
        return "application/pdf"
    if ext == ".docx":
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if ext == ".doc":
        return "application/msword"
    if ext == ".txt":
        return "text/plain"
    return "application/octet-stream"


def _headers(api_key: str, *, json_mode: bool = True) -> dict[str, str]:
    out = {"Authorization": f"Bearer {api_key}"}
    if json_mode:
        out["Content-Type"] = "application/json"
    return out


def _file_type_for_parser(ext: str) -> str:
    normalized = str(ext or "").strip().lower()
    if normalized == ".pdf":
        return "PDF"
    if normalized == ".docx":
        return "DOCX"
    if normalized == ".doc":
        return "DOC"
    if normalized == ".txt":
        return "TXT"
    return "TXT"


def _collect_text(value: Any) -> list[str]:
    out: list[str] = []
    if value is None:
        return out
    if isinstance(value, str):
        text = value.strip()
        if text:
            out.append(text)
        return out
    if isinstance(value, list):
        for item in value:
            out.extend(_collect_text(item))
        return out
    if isinstance(value, dict):
        preferred_keys = {
            "text",
            "content",
            "output_text",
            "reasoning_content",
            "arguments",
            "result",
            "markdown",
            "plain_text",
            "extracted_text",
            "elements",
            "data",
            "pages",
            "page_text",
        }
        for key, val in value.items():
            if not isinstance(key, str):
                continue
            if key in {"Text", "Elements"}:
                out.extend(_collect_text(val))
                continue
            if key.lower() in preferred_keys:
                out.extend(_collect_text(val))
        return out
    return out


def _is_textual_content_type(content_type: str) -> bool:
    ct = str(content_type or "").lower()
    if not ct:
        return False
    if ct.startswith("text/"):
        return True
    for token in ("json", "xml", "markdown", "csv", "html"):
        if token in ct:
            return True
    return False


def _looks_like_binary_garbage(text: str) -> bool:
    raw = str(text or "")
    if not raw:
        return False
    head = raw[:120]
    if ("PK\u0003\u0004" in head) or ("PK\x03\x04" in head) or ("PK" in head):
        return True
    sample = raw[:2000]
    ctrl = sum(1 for ch in sample if (ord(ch) < 32 and ch not in "\n\r\t"))
    return ctrl > 10


def _decode_text_bytes(data: bytes) -> str:
    if not data:
        return ""
    for enc in ("utf-8", "utf-8-sig", "gb18030", "gbk"):
        try:
            return normalize_text(data.decode(enc))
        except Exception:
            continue
    try:
        return normalize_text(data.decode("latin-1", errors="ignore"))
    except Exception:
        return ""


def _drop_inline_image_lines(text: str) -> str:
    raw = normalize_text(text)
    if not raw:
        return ""
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    cleaned = [ln for ln in lines if not _INLINE_IMAGE_MARK_RE.match(ln)]
    return normalize_text("\n".join(cleaned))


def _estimate_text_quality(text: str) -> float:
    raw = normalize_text(text)
    if not raw:
        return -1e9
    if _looks_like_binary_garbage(raw):
        return -1e6
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    chars = len(raw)
    heading_hits = sum(1 for h in _QUALITY_HINTS if h in raw)
    date_hits = len(re.findall(r"(?:19|20)\d{2}[./-]\d{1,2}", raw))
    bad_tokens = 0
    for token in ("_md_fu", "images/", "![", "PK\x03\x04", "PK"):
        bad_tokens += raw.count(token)
    # Character volume + structure cues + time cues, penalize obvious parser garbage markers.
    score = 0.0
    score += min(chars, 12000) / 150.0
    score += min(len(lines), 400) * 0.4
    score += heading_hits * 18.0
    score += min(date_hits, 30) * 2.2
    score -= bad_tokens * 28.0
    return score


def _extract_resume_text_from_zip_bytes(blob: bytes) -> tuple[str, str]:
    if not blob:
        return "", ""
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            infos = [i for i in zf.infolist() if not i.is_dir()]
            if not infos:
                return "", ""

            def _natural_key(name: str) -> list[Any]:
                return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", str(name or ""))]

            infos.sort(key=lambda it: _natural_key(it.filename))

            # 1) Full markdown result, if present.
            md_full_infos = [it for it in infos if it.filename.lower().endswith("_md_full.md")]
            for info in md_full_infos:
                data = zf.read(info)
                text = _drop_inline_image_lines(_decode_text_bytes(data))
                if text and (not _looks_like_binary_garbage(text)):
                    return text, info.filename

            # 2) Multi-file markdown/txt: merge all pages/files in natural order.
            merged_text_parts: list[str] = []
            merged_names: list[str] = []
            for info in infos:
                lower = info.filename.lower()
                if not lower.endswith((".md", ".txt")):
                    continue
                data = zf.read(info)
                text = _drop_inline_image_lines(_decode_text_bytes(data))
                text = normalize_text(text)
                if not text or _looks_like_binary_garbage(text):
                    continue
                merged_text_parts.append(text)
                merged_names.append(info.filename)
            if merged_text_parts:
                merged_text = normalize_text("\n\n".join(merged_text_parts))
                merged_desc = f"{len(merged_names)} files: {merged_names[0]}" if len(merged_names) == 1 else f"{len(merged_names)} files: {merged_names[0]} .. {merged_names[-1]}"
                return merged_text, merged_desc

            # 3) OCR/page JSON: merge all pages in natural order.
            json_text_parts: list[str] = []
            json_names: list[str] = []
            for info in infos:
                lower = info.filename.lower()
                if not lower.endswith(".json"):
                    continue
                text = _decode_text_bytes(zf.read(info))
                if not text:
                    continue
                try:
                    obj = json.loads(text)
                except Exception:
                    obj = None
                parsed = _drop_inline_image_lines(_extract_resume_text_from_parser_payload(obj))
                parsed = normalize_text(parsed)
                if not parsed or _looks_like_binary_garbage(parsed):
                    continue
                json_text_parts.append(parsed)
                json_names.append(info.filename)
            if json_text_parts:
                merged_json_text = normalize_text("\n\n".join(json_text_parts))
                merged_desc = f"{len(json_names)} files: {json_names[0]}" if len(json_names) == 1 else f"{len(json_names)} files: {json_names[0]} .. {json_names[-1]}"
                return merged_json_text, merged_desc
    except Exception:
        return "", ""
    return "", ""


def _extract_resume_text_from_parser_payload(payload: Any) -> str:
    if payload is None:
        return ""
    if isinstance(payload, str):
        return normalize_text(payload)
    if isinstance(payload, list):
        parts = _collect_text(payload)
        return normalize_text("\n".join(parts))
    if not isinstance(payload, dict):
        return ""
    for key in (
        "content",
        "text",
        "output_text",
        "result",
        "markdown",
        "plain_text",
        "extracted_text",
    ):
        value = normalize_text(str(payload.get(key) or ""))
        if value:
            return value
    data_obj = payload.get("data")
    if isinstance(data_obj, (dict, list, str)):
        nested = _extract_resume_text_from_parser_payload(data_obj)
        if nested:
            return nested
    parts = _collect_text(payload)
    return normalize_text("\n".join(parts))


def _parse_chat_text(data: dict[str, Any]) -> str:
    try:
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        parts = _collect_text(message.get("content"))
        if not parts:
            parts = _collect_text(message.get("reasoning_content"))
        if not parts:
            for tc in message.get("tool_calls") or []:
                if isinstance(tc, dict):
                    fn = tc.get("function") or {}
                    parts.extend(_collect_text(fn.get("arguments")))
        if not parts:
            parts.extend(_collect_text(data.get("output_text")))
        return normalize_text("\n".join([p for p in parts if p]))
    except Exception:
        return ""


def _local_extract(path: str) -> str:
    p = str(path or "")
    ext = Path(p).suffix.lower()
    if ext == ".pdf":
        return normalize_text(extract_text_from_pdf(p))
    if ext in {".doc", ".docx"}:
        return normalize_text(extract_text_from_docx(p))
    if ext == ".txt":
        try:
            return normalize_text(Path(p).read_text(encoding="utf-8"))
        except Exception:
            try:
                return normalize_text(Path(p).read_text(encoding="utf-8-sig"))
            except Exception:
                return ""
    return ""


def _extract_with_zhipu_file_understanding(path: str, filename: str | None = None) -> str:
    cfg = load_effective_llm_config()
    provider = str(cfg.get("provider") or "").strip().lower()
    api_key = str(cfg.get("api_key") or "").strip()
    base_url = str(cfg.get("base_url") or "").strip()
    if provider != "zhipu" or not api_key or not base_url:
        return ""

    file_path = Path(path)
    ext = file_path.suffix.lower()
    if ext not in _SUPPORTED_EXTS or (not file_path.exists()):
        return ""

    with file_path.open("rb") as f:
        file_bytes = f.read()
    if not file_bytes:
        return ""
    name = str(filename or file_path.name or "resume")
    mime = _guess_mime(ext)
    file_b64 = base64.b64encode(file_bytes).decode("ascii")
    file_url_candidates: list[tuple[str, str]] = [
        ("base64", file_b64),
        ("data_url", f"data:{mime};base64,{file_b64}"),
    ]
    timeout = float(cfg.get("timeout_seconds") or 60)
    chat_url = _chat_url(base_url)

    with httpx.Client(timeout=max(60.0, timeout)) as client:
        data: dict[str, Any] | None = None
        last_err: str | None = None
        for url_mode, file_url in file_url_candidates:
            payload = {
                "model": _FILE_UNDERSTANDING_MODEL,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "file_url", "file_url": {"url": file_url}},
                            {
                                "type": "text",
                                "text": (
                                    "请读取该简历文件并提取完整文本。"
                                    "仅输出简历正文，不要解释，不要JSON，不要代码块。"
                                ),
                            },
                        ],
                    }
                ],
                "stream": False,
                "temperature": 0.0,
                "thinking": {"type": "enabled"},
                "max_tokens": 4000,
            }
            logger.info(
                "[RESUME_FILE_API][FILE_UNDERSTANDING_REQUEST] model=%s filename=%s ext=%s bytes=%s endpoint=%s url_mode=%s",
                _FILE_UNDERSTANDING_MODEL,
                name,
                ext,
                len(file_bytes),
                chat_url,
                url_mode,
            )
            for attempt in range(1, 3):
                resp = client.post(chat_url, headers=_headers(api_key, json_mode=True), json=payload)
                if resp.status_code < 400:
                    data = resp.json() if resp.text else {}
                    break
                body = (resp.text or "")[:240]
                last_err = f"zhipu_file_understanding_failed:{resp.status_code}:{body}"
                logger.warning(
                    "[RESUME_FILE_API][FILE_UNDERSTANDING_RETRY] url_mode=%s attempt=%s status=%s",
                    url_mode,
                    attempt,
                    resp.status_code,
                )
                if resp.status_code < 500:
                    break
                time.sleep(float(attempt))
            if data is not None:
                break
        if data is None:
            raise RuntimeError(last_err or "zhipu_file_understanding_failed:unknown")
    text = _drop_inline_image_lines(_parse_chat_text(data))
    if _looks_like_binary_garbage(text):
        return ""
    logger.info(
        "[RESUME_FILE_API][FILE_UNDERSTANDING_RESPONSE] model=%s extracted_chars=%s",
        _FILE_UNDERSTANDING_MODEL,
        len(text),
    )
    return text


def _extract_with_zhipu_file_api(path: str, filename: str | None = None) -> str:
    cfg = load_effective_llm_config()
    provider = str(cfg.get("provider") or "").strip().lower()
    api_key = str(cfg.get("api_key") or "").strip()
    model = str(cfg.get("model") or "").strip()
    base_url = str(cfg.get("base_url") or "").strip()
    if provider != "zhipu" or not api_key or not model or not base_url:
        return ""

    file_path = Path(path)
    ext = file_path.suffix.lower()
    if ext not in _SUPPORTED_EXTS or (not file_path.exists()):
        return ""

    timeout = float(cfg.get("timeout_seconds") or 60)
    parser_sync_url = _parser_sync_url(base_url)
    name = str(filename or file_path.name or "resume")
    file_type = _file_type_for_parser(ext)

    with file_path.open("rb") as f:
        file_bytes = f.read()
    if not file_bytes:
        return ""
    logger.info(
        "[RESUME_FILE_API][PARSER_SYNC_REQUEST] filename=%s ext=%s file_type=%s bytes=%s model=%s endpoint=%s",
        name,
        ext,
        file_type,
        len(file_bytes),
        model,
        parser_sync_url,
    )

    with httpx.Client(timeout=max(60.0, timeout)) as client:
        parser_resp = client.post(
            parser_sync_url,
            headers=_headers(api_key, json_mode=False),
            data={"tool_type": _PARSER_TOOL_TYPE, "file_type": file_type},
            files={"file": (name, file_bytes, _guess_mime(ext))},
        )
        if parser_resp.status_code >= 400:
            raise RuntimeError(f"zhipu_file_parser_sync_failed:{parser_resp.status_code}:{parser_resp.text[:240]}")
        parser_data = parser_resp.json() if parser_resp.text else {}

        extracted = _drop_inline_image_lines(_extract_resume_text_from_parser_payload(parser_data))
        status = str((parser_data or {}).get("status") or "").strip().lower()
        task_id = str((parser_data or {}).get("task_id") or (parser_data or {}).get("id") or "").strip()
        parsing_result_url = str((parser_data or {}).get("parsing_result_url") or "").strip()
        logger.info(
            "[RESUME_FILE_API][PARSER_SYNC_RESPONSE] status=%s task_id=%s extracted_chars=%s has_result_url=%s",
            status or "unknown",
            task_id or "-",
            len(extracted),
            "yes" if parsing_result_url else "no",
        )

        if (len(extracted) < 80) and parsing_result_url:
            try:
                url_resp = client.get(parsing_result_url, headers=_headers(api_key, json_mode=False))
                if url_resp.status_code < 400:
                    ct = str(url_resp.headers.get("content-type") or "").lower()
                    if "application/json" in ct:
                        url_data = url_resp.json() if url_resp.text else {}
                        url_text = _drop_inline_image_lines(_extract_resume_text_from_parser_payload(url_data))
                    elif "application/zip" in ct or "application/octet-stream" in ct or url_resp.content.startswith(b"PK\x03\x04"):
                        url_text, zip_entry = _extract_resume_text_from_zip_bytes(url_resp.content)
                        logger.info(
                            "[RESUME_FILE_API][PARSER_RESULT_URL_ZIP] status_code=%s content_type=%s zip_entry=%s extracted_chars=%s",
                            url_resp.status_code,
                            ct or "-",
                            zip_entry or "-",
                            len(url_text),
                        )
                    elif _is_textual_content_type(ct):
                        url_text = _drop_inline_image_lines(normalize_text(url_resp.text or ""))
                    else:
                        url_text = ""
                    if _looks_like_binary_garbage(url_text):
                        logger.warning("[RESUME_FILE_API][PARSER_RESULT_URL] detected_binary_garbage_drop=true")
                        url_text = ""
                    if len(url_text) > len(extracted):
                        extracted = url_text
                    logger.info(
                        "[RESUME_FILE_API][PARSER_RESULT_URL] status_code=%s content_type=%s extracted_chars=%s",
                        url_resp.status_code,
                        ct or "-",
                        len(url_text),
                    )
            except Exception:
                pass

        if (len(extracted) < 80) and task_id:
            result_url = _parser_result_url(base_url, task_id)
            if result_url:
                for _ in range(6):
                    time.sleep(1.0)
                    result_resp = client.get(result_url, headers=_headers(api_key, json_mode=False))
                    if result_resp.status_code >= 400:
                        continue
                    result_data = result_resp.json() if result_resp.text else {}
                    extracted = _drop_inline_image_lines(_extract_resume_text_from_parser_payload(result_data))
                    result_status = str((result_data or {}).get("status") or "").strip().lower()
                    logger.info(
                        "[RESUME_FILE_API][PARSER_RESULT_POLL] task_id=%s status=%s extracted_chars=%s",
                        task_id,
                        result_status or "unknown",
                        len(extracted),
                    )
                    if len(extracted) >= 80:
                        break
                    if result_status in {"failed", "error", "cancelled"}:
                        break

    logger.info("[RESUME_FILE_API][PARSER_DONE] extracted_chars=%s", len(extracted))
    return extracted


def extract_resume_text_smart(path: str, filename: str | None = None) -> tuple[str, str]:
    """
    Return (text, source).
    source: "zhipu_file_understanding" | "zhipu_file_api" | "local_pdf_docx" | "none"
    """
    ext = Path(path).suffix.lower()
    candidates: list[tuple[str, str]] = []

    # Word resumes should be read locally first. The XML paragraph order is
    # usually good enough, and avoiding remote file parsing removes a slow,
    # failure-prone step before the actual profile-structuring LLM call.
    if ext in {".doc", ".docx"}:
        local_first = normalize_text(_local_extract(path))
        if len(local_first) >= 40 and (not _looks_like_binary_garbage(local_first)):
            logger.info("简历文本提取：Word文件已优先使用本地Python读取，长度=%s", len(local_first))
            return local_first, "local_pdf_docx"

    try:
        direct = _extract_with_zhipu_file_understanding(path, filename=filename)
        direct = normalize_text(direct)
        if len(direct) >= 80 and (not _looks_like_binary_garbage(direct)):
            candidates.append((direct, "zhipu_file_understanding"))
        else:
            logger.info("简历文件理解结果不足，将继续尝试其他链路，长度=%s", len(direct))
    except Exception as e:
        logger.warning("简历文件理解提取失败，将继续尝试其他链路：%s", e)

    try:
        remote = _extract_with_zhipu_file_api(path, filename=filename)
        remote = normalize_text(remote)
        if len(remote) >= 80 and (not _looks_like_binary_garbage(remote)):
            candidates.append((remote, "zhipu_file_api"))
    except Exception as e:
        logger.warning("简历文件API提取失败，将继续尝试本地提取：%s", e)

    local = normalize_text(_local_extract(path))
    if len(local) >= 40 and (not _looks_like_binary_garbage(local)):
        candidates.append((local, "local_pdf_docx"))

    if not candidates:
        return "", "none"

    scored: list[tuple[float, str, str]] = []
    for text, source in candidates:
        score = _estimate_text_quality(text)
        # DOCX often has cleaner ordering in local XML paragraphs than OCR-like parser output.
        if ext == ".docx" and source == "local_pdf_docx":
            score += 16.0
        if source == "zhipu_file_understanding":
            score += 8.0
        elif source == "zhipu_file_api":
            score += 4.0
        scored.append((score, source, text))

    scored.sort(key=lambda x: x[0], reverse=True)
    best_score, best_source, best_text = scored[0]
    logger.info(
        "[RESUME_FILE_API][SELECT_BEST] candidates=%s selected=%s score=%.2f lengths=%s",
        len(scored),
        best_source,
        best_score,
        ",".join([f"{src}:{len(txt)}:{sc:.1f}" for sc, src, txt in scored]),
    )
    if best_source == "zhipu_file_understanding":
        logger.info("简历文本提取：已使用智谱文件理解模型，长度=%s", len(best_text))
    elif best_source == "zhipu_file_api":
        logger.info("简历文本提取：已使用智谱文件API，长度=%s", len(best_text))
    else:
        logger.info("简历文本提取：已使用本地提取（质量择优），长度=%s", len(best_text))
    return best_text, best_source
