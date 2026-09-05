from __future__ import annotations

import re
from typing import Any

from app.utils.text import normalize_token

PROFICIENCY_SCALE = [
    {"level": "aware", "label": "了解", "rank": 1, "score": 0.42},
    {"level": "familiar", "label": "熟悉", "rank": 2, "score": 0.58},
    {"level": "proficient", "label": "熟练", "rank": 3, "score": 0.74},
    {"level": "project", "label": "项目实战", "rank": 4, "score": 0.88},
    {"level": "delivery", "label": "可独立交付", "rank": 5, "score": 1.0},
]

DEFAULT_STUDENT_LEVEL = "delivery"
DEFAULT_JOB_LEVEL = "delivery"

_ALIASES = {
    "了解": "aware",
    "入门": "aware",
    "基础": "aware",
    "基础使用": "aware",
    "aware": "aware",
    "熟悉": "familiar",
    "familiar": "familiar",
    "掌握": "familiar",
    "熟练": "proficient",
    "熟练要求": "proficient",
    "高熟练要求": "proficient",
    "proficient": "proficient",
    "熟练/深入": "proficient",
    "项目": "project",
    "项目实战": "project",
    "项目可用": "project",
    "project": "project",
    "实战": "project",
    "可独立交付": "delivery",
    "独立交付": "delivery",
    "独立负责": "delivery",
    "delivery": "delivery",
    "最高": "delivery",
}

_BY_LEVEL = {item["level"]: item for item in PROFICIENCY_SCALE}


def normalize_proficiency_level(value: Any, *, default: str = DEFAULT_STUDENT_LEVEL) -> str:
    raw = str(value or "").strip()
    if not raw:
        return default
    key = raw.lower()
    if key in _ALIASES:
        return _ALIASES[key]
    norm = normalize_token(raw)
    for alias, level in _ALIASES.items():
        if normalize_token(alias) == norm:
            return level
    return default


def proficiency_info(value: Any, *, default: str = DEFAULT_STUDENT_LEVEL) -> dict[str, Any]:
    level = normalize_proficiency_level(value, default=default)
    info = dict(_BY_LEVEL.get(level) or _BY_LEVEL[default])
    return info


def proficiency_label(value: Any, *, default: str = DEFAULT_STUDENT_LEVEL) -> str:
    return str(proficiency_info(value, default=default)["label"])


def proficiency_score(value: Any, *, default: str = DEFAULT_STUDENT_LEVEL) -> float:
    return float(proficiency_info(value, default=default)["score"])


def infer_student_proficiency_from_evidence(skill_name: str, item: dict[str, Any] | None, resume_text: str = "") -> dict[str, Any]:
    item = item or {}
    explicit = item.get("proficiency") or item.get("level")
    if explicit:
        info = proficiency_info(explicit, default=DEFAULT_STUDENT_LEVEL)
        return {
            **info,
            "evidence": str(item.get("evidence") or item.get("proficiency_evidence") or f"画像技能：{skill_name}").strip()[:180],
            "source": str(item.get("proficiency_source") or item.get("source_section") or "profile").strip() or "profile",
        }

    text = normalize_token(
        " ".join(
            str(x or "")
            for x in [
                item.get("evidence"),
                item.get("source_section"),
                item.get("description"),
                resume_text,
            ]
        )
    )
    if any(word in text for word in ["主导", "负责架构", "独立负责", "上线", "生产环境", "交付", "高并发", "性能优化"]):
        level = "delivery"
    elif any(word in text for word in ["项目", "实习", "开发", "实现", "部署", "联调", "接口", "系统"]):
        level = "project"
    elif any(word in text for word in ["熟练", "掌握", "常用", "多次"]):
        level = "proficient"
    elif any(word in text for word in ["使用", "用过", "课程", "实验", "学习"]):
        level = "familiar"
    else:
        level = DEFAULT_STUDENT_LEVEL
    info = proficiency_info(level)
    evidence = str(item.get("evidence") or "").strip() or f"画像中出现 {skill_name}"
    return {**info, "evidence": evidence[:180], "source": str(item.get("source_section") or "profile")}


def infer_required_proficiency_from_text(skill_name: str, text: str, *, default: str = DEFAULT_JOB_LEVEL) -> dict[str, Any]:
    norm = normalize_token(text)
    key = normalize_token(skill_name)
    window = norm
    if key and key in norm:
        idx = norm.find(key)
        window = norm[max(0, idx - 36) : idx + len(key) + 36]
    if any(word in window for word in ["精通", "架构", "高并发", "性能优化", "独立负责", "独立交付"]):
        level = "delivery"
    elif any(word in window for word in ["项目经验", "实战", "上线", "生产环境", "开发经验"]):
        level = "project"
    elif any(word in window for word in ["熟练", "掌握", "负责", "独立"]):
        level = "proficient"
    elif any(word in window for word in ["熟悉", "了解", "优先", "加分"]):
        level = "familiar"
    else:
        level = default
    info = proficiency_info(level, default=default)
    return {**info, "evidence": window[:180]}


def ability_verification_from_review(review: dict[str, Any] | None, challenge: dict[str, Any] | None = None) -> dict[str, Any] | None:
    if not isinstance(review, dict):
        return None
    try:
        overall = float(review.get("overall_score") or 0)
    except Exception:
        overall = 0.0
    dims = review.get("dimension_scores") if isinstance(review.get("dimension_scores"), dict) else {}
    job_ability = float(dims.get("岗位相关能力") or overall or 0)
    correctness = float(dims.get("正确性") or overall or 0)
    effective = max(overall, job_ability * 0.92, correctness * 0.88)
    if effective >= 88:
        level = "delivery"
    elif effective >= 76:
        level = "project"
    elif effective >= 64:
        level = "proficient"
    elif effective >= 50:
        level = "familiar"
    else:
        level = "aware"
    tags = []
    if isinstance(challenge, dict):
        tags = [str(x).strip() for x in (challenge.get("tags") or []) if str(x).strip()]
    if not tags:
        note = " ".join([str(review.get("interview_note") or ""), " ".join(review.get("strengths") or [])])
        tags = re.findall(r"[A-Za-z][A-Za-z0-9+.#/_-]{1,}|[\u4e00-\u9fff]{2,}", note)[:8]
    info = proficiency_info(level)
    return {
        **info,
        "overall_score": round(overall, 2),
        "dimension_scores": dims,
        "skills": tags[:8],
        "evidence": str(review.get("interview_note") or "岗位能力验证结果").strip()[:180],
        "source": "ability_verification",
    }


def merge_proficiency_with_verification(
    base_level: Any,
    *,
    verification_level: Any = None,
    verification_score: Any = None,
) -> dict[str, Any]:
    base = proficiency_info(base_level, default=DEFAULT_STUDENT_LEVEL)
    if not verification_level and verification_score is None:
        return base
    ver = proficiency_info(verification_level or base["level"], default=base["level"])
    try:
        score = float(verification_score)
    except Exception:
        score = None
    if score is not None:
        if score >= 88:
            ver = proficiency_info("delivery")
        elif score >= 76:
            ver = proficiency_info("project")
        elif score >= 64:
            ver = proficiency_info("proficient")
        elif score >= 50:
            ver = proficiency_info("familiar")
        else:
            ver = proficiency_info("aware")
    picked = ver if int(ver["rank"]) >= int(base["rank"]) else base
    return dict(picked)
