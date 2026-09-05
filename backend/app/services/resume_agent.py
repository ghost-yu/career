from __future__ import annotations

import json
import re
from typing import Any

from app.db import sqlite as db
from app.services.deepseek_client import DEEPSEEK_RESUME_MODEL, deepseek_chat_json_sync, deepseek_json_enabled
from app.services.profile_snapshot import build_student_profile_snapshot
from app.services.resume_file_extract import extract_resume_text_smart
from app.utils.text import normalize_text

_KEYWORD_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.#/-]{1,}|[\u4e00-\u9fff]{2,}")
_RESUME_SCHEMA_KEYS = {
    "resume_markdown",
    "targeted_summary",
    "highlighted_keywords",
    "missing_keywords",
    "risk_notes",
    "cover_letter",
}


def _safe_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    return []


def _dedupe_keep_order(items: list[str], *, limit: int = 30) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in items:
        token = normalize_text(str(raw or "")).strip()
        if not token:
            continue
        key = token.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(token)
        if len(out) >= limit:
            break
    return out


def _top_keywords(text: str, *, limit: int = 20) -> list[str]:
    hit: dict[str, int] = {}
    for tok in _KEYWORD_TOKEN_RE.findall(text or ""):
        token = normalize_text(tok).strip()
        if len(token) < 2:
            continue
        hit[token] = int(hit.get(token, 0)) + 1
    ranked = sorted(hit.items(), key=lambda x: (x[1], x[0]), reverse=True)
    return [k for k, _ in ranked[:limit]]


def _latest_resume_text(student_id: str) -> tuple[str, str | None]:
    files = db.list_student_files(student_id) or []
    if not files:
        return "", None
    latest = sorted(files, key=lambda x: str(x.get("created_at") or ""), reverse=True)[0]
    path = str(latest.get("path") or "")
    if not path:
        return "", None
    text, _source = extract_resume_text_smart(path, filename=str(latest.get("filename") or ""))
    return normalize_text(text), str(latest.get("filename") or "")


def _compact_profile(profile: dict[str, Any]) -> dict[str, Any]:
    return build_student_profile_snapshot(
        profile,
        hard_limit=30,
        soft_limit=15,
        cert_limit=15,
        detail_limit_per_field=6,
        include_detail_items=True,
        include_education=True,
        notes_limit=360,
        profile_notes_limit=520,
    )


def _job_context(body: dict[str, Any]) -> dict[str, Any]:
    job_id = str(body.get("job_id") or "").strip()
    title = normalize_text(str(body.get("target_title") or body.get("job_title") or ""))
    description = normalize_text(str(body.get("job_description") or ""))
    out: dict[str, Any] = {
        "job_id": job_id or None,
        "title": title,
        "description": description,
        "job_profile": {},
    }
    if not job_id:
        return out

    job = db.get_job(job_id) or {}
    job_profile = (db.get_job_profile(job_id) or {}).get("profile") or {}
    if not out["title"]:
        out["title"] = normalize_text(str(job.get("title") or ""))
    if not out["description"]:
        out["description"] = normalize_text(str(job.get("description") or ""))
    out["job_profile"] = {
        "job_family": job_profile.get("job_family"),
        "hard_skills": [
            str(x.get("mention") or x.get("name") or "").strip()
            for x in _safe_list(job_profile.get("hard_skills"))
            if str(x.get("mention") or x.get("name") or "").strip()
        ][:30],
        "soft_skills": [
            str(x.get("name") or x.get("mention") or "").strip()
            for x in _safe_list(job_profile.get("soft_skills"))
            if str(x.get("name") or x.get("mention") or "").strip()
        ][:15],
        "certificates": [
            str(x.get("name") or x.get("mention") or "").strip()
            for x in _safe_list(job_profile.get("certificates"))
            if str(x.get("name") or x.get("mention") or "").strip()
        ][:10],
    }
    return out


def _fallback_resume_markdown(
    *,
    student_name: str,
    base_resume_text: str,
    target_title: str,
    keywords: list[str],
) -> str:
    lines: list[str] = []
    lines.append(f"# {student_name or '候选人'}")
    if target_title:
        lines.append("## 目标岗位")
        lines.append(target_title)
    lines.append("## 生成说明")
    lines.append("本次输出触发了安全兜底模板，已尽量保留原始简历信息并按求职场景重排。")
    if keywords:
        lines.append("")
        lines.append("## 关键词建议")
        lines.append("、".join(keywords[:18]))
    if base_resume_text:
        lines.append("")
        lines.append("## 原始简历节选")
        excerpt = base_resume_text[:5200].strip()
        lines.append(excerpt)
    return "\n".join(lines).strip()


def _fallback_cover_letter(
    *,
    student_name: str,
    target_title: str,
    targeted_summary: str,
    highlighted_keywords: list[str],
) -> str:
    role = target_title or "相关岗位"
    name = student_name or "候选人"
    key_line = "、".join(highlighted_keywords[:6]) if highlighted_keywords else "岗位匹配能力"
    summary_line = targeted_summary or "我具备较强的学习能力、执行力和团队协作能力。"
    lines = [
        f"尊敬的招聘负责人：",
        "",
        f"您好！我是{name}，希望应聘贵司的{role}岗位。",
        f"{summary_line}",
        f"结合岗位要求，我重点突出以下能力：{key_line}。",
        "我愿意在入职后快速补齐差距，在实际项目中持续交付可验证成果。",
        "感谢您审阅我的申请，期待进一步沟通。",
        "",
        "此致",
        "敬礼",
        "",
        name,
    ]
    return "\n".join(lines).strip()


def _generate_cover_letter_if_missing(
    *,
    include_cover_letter: bool,
    cover_letter: str,
    student_name: str,
    target_title: str,
    targeted_summary: str,
    highlighted_keywords: list[str],
    base_resume_text: str,
) -> tuple[str, bool]:
    if not include_cover_letter:
        return "", False
    if cover_letter.strip():
        return cover_letter.strip(), False

    if deepseek_json_enabled():
        system = """你是求职信写作助手，只输出 JSON 对象。
格式：{"cover_letter": "中文求职信正文"}
要求：
1) 不得编造经历、项目、证书、业绩；
2) 语气专业、简洁；
3) 控制在220~380字。"""
        user_payload = {
            "student_name": student_name,
            "target_title": target_title,
            "targeted_summary": targeted_summary,
            "highlighted_keywords": highlighted_keywords[:12],
            "resume_excerpt": base_resume_text[:5000],
        }
        try:
            data = deepseek_chat_json_sync(
                system,
                json.dumps(user_payload, ensure_ascii=False),
                trace_context="resume_agent.cover_letter_fallback.deepseek",
                max_tokens=900,
                expected_root_keys={"cover_letter"},
            )
            text = normalize_text(str(data.get("cover_letter") or "")).strip()
            if text:
                return text, True
        except Exception:
            pass

    return (
        _fallback_cover_letter(
            student_name=student_name,
            target_title=target_title,
            targeted_summary=targeted_summary,
            highlighted_keywords=highlighted_keywords,
        ),
        False,
    )


def _normalize_resume_result(
    raw: dict[str, Any] | None,
    *,
    student_name: str,
    base_resume_text: str,
    target_title: str,
    default_keywords: list[str],
    include_cover_letter: bool,
) -> tuple[dict[str, Any], bool]:
    data = raw or {}
    resume_markdown = normalize_text(str(data.get("resume_markdown") or ""))
    extra_text_blocks: list[str] = []
    for key, value in data.items():
        if key in _RESUME_SCHEMA_KEYS:
            continue
        extra_text = normalize_text(str(value or "")).strip()
        if not extra_text:
            continue
        if len(extra_text) < 8:
            continue
        extra_text_blocks.append(extra_text)
    if extra_text_blocks:
        for extra in extra_text_blocks:
            if extra not in resume_markdown:
                resume_markdown = (resume_markdown + "\n\n" + extra).strip() if resume_markdown else extra

    highlighted_keywords = [str(x).strip() for x in _safe_list(data.get("highlighted_keywords")) if str(x).strip()]
    missing_keywords = [str(x).strip() for x in _safe_list(data.get("missing_keywords")) if str(x).strip()]
    risk_notes = [str(x).strip() for x in _safe_list(data.get("risk_notes")) if str(x).strip()]
    targeted_summary = normalize_text(str(data.get("targeted_summary") or ""))

    if not highlighted_keywords:
        highlighted_keywords = list(default_keywords[:20])
    highlighted_keywords = _dedupe_keep_order(highlighted_keywords, limit=20)

    source_len = len(base_resume_text or "")
    min_length = 280 if source_len <= 1200 else (520 if source_len <= 3600 else 820)
    looks_truncated = (
        (not resume_markdown)
        or (len(resume_markdown) < min_length)
        or (resume_markdown.count("**") % 2 == 1 and len(resume_markdown) < 2200)
        or (source_len > 2600 and resume_markdown.count("##") < 2)
    )
    if looks_truncated:
        resume_markdown = _fallback_resume_markdown(
            student_name=student_name,
            base_resume_text=base_resume_text,
            target_title=target_title,
            keywords=highlighted_keywords,
        )
        risk_notes = _dedupe_keep_order(
            ["模型返回结构不完整，已自动启用兜底模板并保留原始简历关键信息。", *risk_notes],
            limit=12,
        )
    if not targeted_summary:
        targeted_summary = "已根据目标岗位与学生画像完成简历重排，突出真实经历与核心能力。"
    cover_letter_raw = normalize_text(str(data.get("cover_letter") or ""))
    cover_letter, used_cover_letter_llm = _generate_cover_letter_if_missing(
        include_cover_letter=include_cover_letter,
        cover_letter=cover_letter_raw,
        student_name=student_name,
        target_title=target_title,
        targeted_summary=targeted_summary,
        highlighted_keywords=highlighted_keywords,
        base_resume_text=base_resume_text,
    )

    return {
        "resume_markdown": resume_markdown,
        "targeted_summary": targeted_summary,
        "highlighted_keywords": highlighted_keywords[:20],
        "missing_keywords": _dedupe_keep_order(missing_keywords, limit=20),
        "risk_notes": _dedupe_keep_order(risk_notes, limit=12),
        "cover_letter": cover_letter,
    }, used_cover_letter_llm


def _needs_retry_resume_generation(raw: dict[str, Any] | None, *, source_resume_text: str) -> bool:
    if not isinstance(raw, dict) or not raw:
        return True
    resume_markdown = normalize_text(str(raw.get("resume_markdown") or ""))
    source_len = len(source_resume_text or "")
    min_length = 280 if source_len <= 1200 else (520 if source_len <= 3600 else 820)
    if len(resume_markdown) < min_length:
        return True
    if resume_markdown.count("**") % 2 == 1 and len(resume_markdown) < 2200:
        return True
    extra_keys = [key for key in raw.keys() if key not in _RESUME_SCHEMA_KEYS]
    if len(extra_keys) >= 2:
        return True
    missing_core = 0
    for key in ("targeted_summary", "highlighted_keywords", "missing_keywords", "risk_notes"):
        value = raw.get(key)
        if value is None:
            missing_core += 1
            continue
        if isinstance(value, str) and not value.strip():
            missing_core += 1
            continue
        if isinstance(value, list) and not value:
            missing_core += 1
    return missing_core >= 3


def generate_ai_resume(student_id: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = body or {}
    student = db.get_student(student_id)
    if not student:
        raise ValueError("student_not_found")

    include_cover_letter = bool(payload.get("include_cover_letter", False))
    manual_resume_text = normalize_text(str(payload.get("resume_text") or ""))
    base_resume_text, source_filename = _latest_resume_text(student_id)
    if manual_resume_text:
        base_resume_text = manual_resume_text
        source_filename = source_filename or "manual_input.txt"

    if not base_resume_text:
        raise ValueError("resume_text_not_found")

    prof = (db.get_student_profile(student_id) or {}).get("profile") or {}
    compact_profile = _compact_profile(prof)
    job_ctx = _job_context(payload)
    target_title = str(job_ctx.get("title") or "").strip()
    target_description = str(job_ctx.get("description") or "").strip()

    keyword_seed = _top_keywords((target_title + "\n" + target_description).strip(), limit=20)
    profile_seed = _dedupe_keep_order(
        [str(x or "").strip() for x in _safe_list(compact_profile.get("hard_skills"))],
        limit=20,
    )
    keyword_seed = _dedupe_keep_order([*keyword_seed, *profile_seed], limit=24)
    request_payload = {
        "student": {
            "student_id": student_id,
            "name": student.get("name") or "",
            "profile": compact_profile,
        },
        "target_job": job_ctx,
        "source_resume_text": base_resume_text[:24000],
        "options": {
            "language": str(payload.get("language") or "zh-CN"),
            "include_cover_letter": include_cover_letter,
            "inspiration": ["真实经历优先", "岗位关键词对齐", "避免空洞措辞"],
        },
    }

    llm_result: dict[str, Any] | None = None
    if deepseek_json_enabled():
        system = """你是“中文求职简历重写助手”，只允许输出一个 JSON 对象，禁止输出解释文本或 Markdown 包裹符。
必须严格输出以下结构，且只能包含这 6 个顶层字段：
{
  "resume_markdown": "字符串，完整中文简历 Markdown",
  "targeted_summary": "字符串，3~5句中文总结",
  "highlighted_keywords": ["字符串"],
  "missing_keywords": ["字符串"],
  "risk_notes": ["字符串"],
  "cover_letter": "字符串，可为空"
}
规则：
1) 不能编造公司、学历、证书、项目、指标；只能改写、重排、提炼。
2) `resume_markdown` 必须覆盖教育、实习/项目、技能等关键信息；当原简历很长时可压缩表述，但不能只给半段。
3) 允许在内容不足时给出 `risk_notes`，但仍需输出一份结构完整的中文简历草稿。
4) `highlighted_keywords` 与 `missing_keywords` 去重，单项不超过 20。
5) `cover_letter` 在 options.include_cover_letter=false 时必须返回空字符串。
"""
        try:
            request_body = json.dumps(request_payload, ensure_ascii=False)
            llm_result = deepseek_chat_json_sync(
                system,
                request_body,
                trace_context="resume_agent.generate.deepseek",
                max_tokens=3200,
                expected_root_keys=_RESUME_SCHEMA_KEYS,
            )
            if _needs_retry_resume_generation(llm_result, source_resume_text=base_resume_text):
                retry_system = """你是 JSON 结构修复与补全助手。
继续基于同一份输入，重新生成完整结果，要求：
1) 仅输出 6 个字段：resume_markdown, targeted_summary, highlighted_keywords, missing_keywords, risk_notes, cover_letter；
2) `resume_markdown` 必须是完整中文 Markdown 简历，不允许截断，不允许出现孤立的 `**`；
3) 若首轮输出字段跑偏或内容过短，本轮必须修复并补全；
4) 不能编造事实。"""
                repaired = deepseek_chat_json_sync(
                    retry_system,
                    request_body,
                    trace_context="resume_agent.generate.retry.deepseek",
                    max_tokens=3600,
                    expected_root_keys=_RESUME_SCHEMA_KEYS,
                )
                if isinstance(repaired, dict) and repaired:
                    llm_result = repaired
        except Exception:
            llm_result = None

    normalized, cover_letter_llm_used = _normalize_resume_result(
        llm_result,
        student_name=str(student.get("name") or ""),
        base_resume_text=base_resume_text,
        target_title=target_title,
        default_keywords=keyword_seed,
        include_cover_letter=include_cover_letter,
    )
    return {
        "student_id": student_id,
        "source_filename": source_filename,
        "target_job_id": job_ctx.get("job_id"),
        "llm_used": bool(llm_result) or bool(cover_letter_llm_used),
        "llm_provider": "deepseek" if (bool(llm_result) or bool(cover_letter_llm_used)) else None,
        "llm_model": DEEPSEEK_RESUME_MODEL if (bool(llm_result) or bool(cover_letter_llm_used)) else None,
        "cover_letter_llm_used": bool(cover_letter_llm_used),
        **normalized,
    }
