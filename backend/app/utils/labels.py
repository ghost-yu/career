from __future__ import annotations

from typing import Any

from app.services.dictionary_cache import dictionary_cache
from app.services.mbti import get_mbti_brief, normalize_mbti_type
from app.services.skill_proficiency import DEFAULT_JOB_LEVEL, DEFAULT_STUDENT_LEVEL, proficiency_info

JOB_FAMILY_LABELS = {
    "backend": "后端开发",
    "frontend": "前端开发",
    "ai": "人工智能",
    "data": "数据开发",
    "qa": "测试质量",
    "ops": "运维云平台",
    "product": "产品运营",
    "design": "设计体验",
    "security": "网络安全",
    "implementation": "实施交付",
    "support": "技术支持",
    "sales": "销售商务",
    "research": "科研研发",
    "embedded": "嵌入式",
    "mobile": "移动开发",
    "general": "综合方向",
}

LEVEL_LABELS_ZH = {
    "junior": "初级/校招",
    "mid": "中级",
    "senior": "高级/资深",
    "lead": "负责人/专家",
}

_FAMILY_ALIASES = {
    "后端": "backend",
    "后端开发": "backend",
    "backend": "backend",
    "java": "backend",
    "服务端": "backend",
    "前端": "frontend",
    "前端开发": "frontend",
    "frontend": "frontend",
    "react": "frontend",
    "vue": "frontend",
    "人工智能": "ai",
    "ai": "ai",
    "算法": "ai",
    "aigc": "ai",
    "机器学习": "ai",
    "深度学习": "ai",
    "数据": "data",
    "数据开发": "data",
    "数据分析": "data",
    "数仓": "data",
    "data": "data",
    "测试": "qa",
    "测试开发": "qa",
    "qa": "qa",
    "质量": "qa",
    "运维": "ops",
    "云平台": "ops",
    "ops": "ops",
    "devops": "ops",
    "sre": "ops",
    "实施": "implementation",
    "交付": "implementation",
    "实施交付": "implementation",
    "技术支持": "support",
    "support": "support",
    "销售": "sales",
    "销售商务": "sales",
    "商务": "sales",
    "商务拓展": "sales",
    "bd": "sales",
    "客户经理": "sales",
    "sales": "sales",
    "安全": "security",
    "网络安全": "security",
    "嵌入式": "embedded",
    "移动开发": "mobile",
    "科研": "research",
    "产品": "product",
    "产品经理": "product",
    "product": "product",
    "设计": "design",
    "ui": "design",
    "ux": "design",
}


def _dict_name_by_id(item_id: Any, fallback: Any = "") -> str:
    iid = str(item_id or "").strip()
    fb = str(fallback or "").strip()
    if not iid:
        return fb
    try:
        snap = dictionary_cache.get_snapshot(force=False)
        for it in snap.items:
            if str(it.get("item_id") or "").strip() == iid:
                return str(it.get("name_zh") or it.get("name_en") or fb or iid).strip()
    except Exception:
        pass
    return fb or iid


def _enrich_named_items(
    items: Any,
    *,
    id_keys: tuple[str, ...],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for raw in items or []:
        if not isinstance(raw, dict):
            continue
        row = dict(raw)
        item_id = ""
        for key in id_keys:
            v = str(row.get(key) or "").strip()
            if v:
                item_id = v
                break
        row["name"] = _dict_name_by_id(item_id, row.get("name") or row.get("mention") or item_id)
        out.append(row)
    return out


def _enrich_proficiency(row: dict[str, Any], *, default: str) -> dict[str, Any]:
    level = row.get("proficiency") or row.get("level")
    info = proficiency_info(level, default=default)
    row["level"] = info["level"]
    row["proficiency"] = info["level"]
    row["proficiency_label"] = info["label"]
    row["proficiency_score"] = info["score"]
    return row


def normalize_job_family_code(value: str | None) -> str | None:
    raw = str(value or "").strip().lower()
    if not raw:
        return None
    return _FAMILY_ALIASES.get(raw, raw if raw in JOB_FAMILY_LABELS else None)



def job_family_label(value: str | None) -> str:
    key = normalize_job_family_code(value) or "general"
    return JOB_FAMILY_LABELS.get(key, key)



def level_label_zh(value: str | None) -> str:
    key = str(value or "mid").strip().lower() or "mid"
    return LEVEL_LABELS_ZH.get(key, key)



def enrich_role_labels(item: dict[str, Any] | None) -> dict[str, Any] | None:
    if not item:
        return item
    out = dict(item)
    out["job_family_label"] = job_family_label(out.get("job_family"))
    out["level_label_zh"] = level_label_zh(out.get("level_label"))
    if isinstance(out.get("top_hard_skills"), list):
        out["top_hard_skills"] = _enrich_named_items(out.get("top_hard_skills"), id_keys=("skill_id", "item_id"))
    if isinstance(out.get("top_soft_skills"), list):
        out["top_soft_skills"] = _enrich_named_items(out.get("top_soft_skills"), id_keys=("soft_skill_id", "item_id"))
    if isinstance(out.get("top_certificates"), list):
        out["top_certificates"] = _enrich_named_items(out.get("top_certificates"), id_keys=("certificate_id", "item_id"))
    return out



def enrich_job_labels(item: dict[str, Any] | None) -> dict[str, Any] | None:
    if not item:
        return item
    out = dict(item)
    profile = out.get("profile") or {}
    if isinstance(profile, dict):
        family = profile.get("job_family")
        if family and "job_family_label" not in profile:
            profile = dict(profile)
            profile["job_family_label"] = job_family_label(family)
            out["profile"] = profile
        if isinstance(profile.get("hard_skills"), list):
            profile = dict(profile)
            enriched = _enrich_named_items(profile.get("hard_skills"), id_keys=("skill_id", "item_id", "name", "mention"))
            for row in enriched:
                if not str(row.get("mention") or "").strip():
                    row["mention"] = row.get("name")
                _enrich_proficiency(row, default=DEFAULT_JOB_LEVEL)
            profile["hard_skills"] = enriched
            out["profile"] = profile
        if isinstance(profile.get("soft_skills"), list):
            profile = dict(profile)
            profile["soft_skills"] = _enrich_named_items(profile.get("soft_skills"), id_keys=("soft_skill_id", "item_id", "name", "mention"))
            out["profile"] = profile
        if isinstance(profile.get("certificates"), list):
            profile = dict(profile)
            profile["certificates"] = _enrich_named_items(profile.get("certificates"), id_keys=("certificate_id", "item_id", "name", "mention"))
            out["profile"] = profile
        if isinstance(profile.get("top_soft_skills"), list):
            profile = dict(profile)
            profile["top_soft_skills"] = _enrich_named_items(profile.get("top_soft_skills"), id_keys=("soft_skill_id", "item_id"))
            out["profile"] = profile
        if isinstance(profile.get("top_hard_skills"), list):
            profile = dict(profile)
            profile["top_hard_skills"] = _enrich_named_items(profile.get("top_hard_skills"), id_keys=("skill_id", "item_id"))
            out["profile"] = profile
        if isinstance(profile.get("top_certificates"), list):
            profile = dict(profile)
            profile["top_certificates"] = _enrich_named_items(profile.get("top_certificates"), id_keys=("certificate_id", "item_id"))
            out["profile"] = profile
    return out



def enrich_student_profile_labels(profile: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(profile, dict):
        return profile
    out = dict(profile)
    if isinstance(out.get("hard_skills"), list):
        hard_items = _enrich_named_items(out.get("hard_skills"), id_keys=("skill_id", "item_id", "name", "mention"))
        for row in hard_items:
            if not str(row.get("mention") or "").strip():
                row["mention"] = row.get("name")
            _enrich_proficiency(row, default=DEFAULT_STUDENT_LEVEL)
        out["hard_skills"] = hard_items
    if isinstance(out.get("soft_skills"), list):
        out["soft_skills"] = _enrich_named_items(out.get("soft_skills"), id_keys=("soft_skill_id", "item_id", "name", "mention"))
    if isinstance(out.get("certificates"), list):
        out["certificates"] = _enrich_named_items(out.get("certificates"), id_keys=("certificate_id", "item_id", "name", "mention"))
    mbti_type = normalize_mbti_type(out.get("mbti_type"))
    if mbti_type:
        out["mbti_type"] = mbti_type
        brief = get_mbti_brief(mbti_type) or {}
        out["mbti_label"] = brief.get("subtitle") or mbti_type
        out["mbti_description"] = brief.get("description") or ""
        out["mbti_career_text"] = brief.get("career_text") or ""
        out["mbti_career_keywords"] = brief.get("career_keywords") or []
        out["mbti_job_family_hints"] = brief.get("job_family_hints") or []
        out["mbti_strengths"] = brief.get("strengths") or []
        out["mbti_challenges"] = brief.get("challenges") or []
    prefs = out.get("preferences") or {}
    if isinstance(prefs, dict):
        families = prefs.get("preferred_job_families") or []
        labels = [job_family_label(x) for x in families if x]
        if mbti_type:
            brief = get_mbti_brief(mbti_type) or {}
            hints = [x for x in (brief.get("job_family_hints") or []) if x]
            hint_labels = [job_family_label(x) for x in hints]
        else:
            hints = []
            hint_labels = []
        prefs = dict(prefs)
        prefs["preferred_job_family_labels"] = labels
        prefs["mbti_job_family_hints"] = hints
        prefs["mbti_job_family_hint_labels"] = hint_labels
        out["preferences"] = prefs
    return out
