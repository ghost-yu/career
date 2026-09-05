from __future__ import annotations

from collections import Counter
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.services import mbti_inline_data

MBTI_TYPES = {
    "INTJ",
    "INTP",
    "ENTJ",
    "ENTP",
    "INFJ",
    "INFP",
    "ENFJ",
    "ENFP",
    "ISTJ",
    "ISFJ",
    "ESTJ",
    "ESFJ",
    "ISTP",
    "ISFP",
    "ESTP",
    "ESFP",
}

TYPE_PAIRS: list[tuple[str, str]] = [("E", "I"), ("S", "N"), ("T", "F"), ("J", "P")]
VALID_ANSWER_TYPES: set[str] = {token for pair in TYPE_PAIRS for token in pair}

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")
_SECTION_RE_TEMPLATE = r"<h3>\s*{title}\s*</h3>\s*<p>(.*?)</p>"

_FAMILY_HINT_RULES: list[tuple[str, str]] = [
    ("后端", "backend"),
    ("前端", "frontend"),
    ("人工智能", "ai"),
    ("算法", "ai"),
    ("数据", "data"),
    ("测试", "qa"),
    ("运维", "ops"),
    ("产品", "product"),
    ("设计", "design"),
    ("销售", "general"),
    ("运营", "general"),
    ("教育", "general"),
    ("咨询", "general"),
]


def normalize_mbti_type(value: str | None) -> str | None:
    raw = str(value or "").strip().upper()
    return raw if raw in MBTI_TYPES else None


def _clean_text(value: str | None) -> str:
    if not value:
        return ""
    text = _HTML_TAG_RE.sub("", str(value))
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    text = _SPACE_RE.sub(" ", text).strip()
    return text


def _extract_section(content_html: str, title: str) -> str:
    pattern = re.compile(_SECTION_RE_TEMPLATE.format(title=re.escape(title)), re.IGNORECASE | re.DOTALL)
    match = pattern.search(content_html or "")
    return _clean_text(match.group(1)) if match else ""


def _extract_first_section(content_html: str, titles: list[str]) -> str:
    for title in titles:
        value = _extract_section(content_html, title)
        if value:
            return value
    return ""


def _split_items(text: str, *, limit: int = 6) -> list[str]:
    if not text:
        return []
    parts = re.split(r"[；;。!！\n]+", text)
    out: list[str] = []
    seen: set[str] = set()
    for part in parts:
        item = part.strip(" ,，、.。")
        if not item:
            continue
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
        if len(out) >= limit:
            break
    return out


def _infer_family_hints(career_text: str) -> list[str]:
    text = str(career_text or "")
    out: list[str] = []
    seen: set[str] = set()
    for keyword, family in _FAMILY_HINT_RULES:
        if keyword in text and family not in seen:
            seen.add(family)
            out.append(family)
    return out[:6]


def _repo_root() -> Path:
    # backend/app/services/mbti.py -> repo root
    return Path(__file__).resolve().parents[3]


def _load_json_file(path: Path) -> Any:
    # MBTI-master data files may include UTF-8 BOM; try utf-8-sig first.
    for encoding in ("utf-8-sig", "utf-8"):
        try:
            return json.loads(path.read_text(encoding=encoding))
        except Exception:
            continue
    raise ValueError("json_load_failed")


@lru_cache(maxsize=1)
def _load_mbti_catalog() -> dict[str, dict[str, Any]]:
    data_path = _repo_root() / "MBTI-master" / "MBTI-master" / "data" / "personality-content.json"
    try:
        payload = _load_json_file(data_path) if data_path.exists() else mbti_inline_data.load_personality_content()
    except Exception:
        return {}
    if not isinstance(payload, list):
        return {}

    out: dict[str, dict[str, Any]] = {}
    for item in payload:
        if not isinstance(item, dict):
            continue
        mbti = normalize_mbti_type(str(item.get("type") or ""))
        if not mbti:
            continue
        content_html = str(item.get("contentHtml") or "")
        strengths_text = _extract_first_section(content_html, ["工作优势", "对组织的贡献", "工作特质", "性格特点"])
        challenges_text = _extract_first_section(content_html, ["工作缺陷", "工作潜在缺陷", "可能陷阱", "盲点"])
        career_text = _extract_first_section(content_html, ["适合的职业领域", "适合的职业"])
        out[mbti] = {
            "mbti_type": mbti,
            "subtitle": _clean_text(item.get("subtitle")),
            "description": _clean_text(item.get("description")),
            "strengths": _split_items(strengths_text, limit=8),
            "challenges": _split_items(challenges_text, limit=6),
            "career_text": career_text,
            "career_keywords": _split_items(career_text, limit=10),
            "job_family_hints": _infer_family_hints(career_text),
        }
    return out


def get_mbti_brief(value: str | None) -> dict[str, Any] | None:
    mbti = normalize_mbti_type(value)
    if not mbti:
        return None
    catalog = _load_mbti_catalog()
    return catalog.get(mbti) or {"mbti_type": mbti}


@lru_cache(maxsize=1)
def _load_mbti_questions() -> list[dict[str, Any]]:
    data_path = _repo_root() / "MBTI-master" / "MBTI-master" / "data" / "questions.json"
    try:
        payload = _load_json_file(data_path) if data_path.exists() else mbti_inline_data.load_questions()
    except Exception:
        return []
    if not isinstance(payload, list):
        return []

    out: list[dict[str, Any]] = []
    for idx, raw in enumerate(payload, start=1):
        if not isinstance(raw, dict):
            continue
        question = str(raw.get("question") or "").strip()
        choice_a = raw.get("choice_a") if isinstance(raw.get("choice_a"), dict) else {}
        choice_b = raw.get("choice_b") if isinstance(raw.get("choice_b"), dict) else {}
        a_value = str(choice_a.get("value") or "").strip().upper()
        b_value = str(choice_b.get("value") or "").strip().upper()
        a_text = str(choice_a.get("text") or "").strip()
        b_text = str(choice_b.get("text") or "").strip()
        if not question or a_value not in VALID_ANSWER_TYPES or b_value not in VALID_ANSWER_TYPES:
            continue
        if not a_text or not b_text:
            continue
        out.append(
            {
                "id": idx,
                "question": question,
                "choice_a": {"value": a_value, "text": a_text},
                "choice_b": {"value": b_value, "text": b_text},
            }
        )
    return out


def get_mbti_questions() -> list[dict[str, Any]]:
    return [dict(item) for item in _load_mbti_questions()]


def calculate_mbti_type(answer_list: list[str]) -> str:
    normalized: list[str] = []
    for raw in answer_list or []:
        token = str(raw or "").strip().upper()
        if token not in VALID_ANSWER_TYPES:
            raise ValueError("answer_type_invalid")
        normalized.append(token)

    if not normalized:
        raise ValueError("answer_list_empty")

    counts = Counter(normalized)
    result = "".join(left if counts[left] > counts[right] else right for left, right in TYPE_PAIRS)
    mbti = normalize_mbti_type(result)
    if not mbti:
        raise ValueError("mbti_result_invalid")
    return mbti


def score_mbti_answers(answer_list: list[str]) -> dict[str, Any]:
    normalized = [str(raw or "").strip().upper() for raw in (answer_list or [])]
    mbti = calculate_mbti_type(normalized)
    counts = Counter(normalized)
    return {
        "mbti_type": mbti,
        "answer_counts": {key: int(counts.get(key, 0)) for key in sorted(VALID_ANSWER_TYPES)},
        "dimension_scores": [
            {
                "dimension": f"{left}/{right}",
                "left": left,
                "right": right,
                "left_count": int(counts.get(left, 0)),
                "right_count": int(counts.get(right, 0)),
                "winner": left if counts.get(left, 0) > counts.get(right, 0) else right,
            }
            for left, right in TYPE_PAIRS
        ],
    }
