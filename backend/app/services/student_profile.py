from __future__ import annotations

import base64
import concurrent.futures
import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Iterable

import httpx

from app.db import sqlite as db
from app.schemas.student import (
    StudentCertificate,
    StudentExperience,
    StudentPreferences,
    StudentProfile,
    StudentSkill,
    StudentSoftSkill,
)
from app.services.llm import llm_client
from app.services.deepseek_client import deepseek_chat_json_sync, deepseek_json_enabled
from app.services.llm_runtime import load_effective_llm_config
from app.services.mbti import normalize_mbti_type
from app.services.mention_extractor import extract_dictionary_mentions
from app.services.normalization import normalize_to_item
from app.services.resume_file_extract import extract_resume_text_smart
from app.services.sectioning import split_resume
from app.services.skill_proficiency import (
    DEFAULT_STUDENT_LEVEL,
    infer_student_proficiency_from_evidence,
    proficiency_info,
)
from app.utils.ids import now_iso
from app.utils.text import normalize_text, normalize_token

COMMON_HARD_SKILLS = [
    "Python",
    "Java",
    "C++",
    "SQL",
    "MySQL",
    "PostgreSQL",
    "Redis",
    "Docker",
    "Kubernetes",
    "Linux",
    "Git",
    "Tableau",
    "Power BI",
    "Excel",
    "Word",
    "PowerPoint",
    "Photoshop",
    "秀米",
    "剪映",
    "WPS",
    "Pandas",
    "NumPy",
    "Spring Boot",
    "React",
    "Vue",
    "JMeter",
    "Postman",
]

COMMON_SOFT_SKILLS = [
    "沟通协作",
    "执行力",
    "学习能力",
    "逻辑思维",
    "责任心",
    "抗压能力",
    "团队合作",
    "问题解决",
]

COMMON_CERTIFICATES = [
    "CET-4",
    "CET-6",
    "计算机二级",
    "软考中级",
    "软考高级",
    "PMP",
    "教师资格证",
    "蓝桥杯",
]

COMMON_LOCATIONS = [
    "北京",
    "上海",
    "广州",
    "深圳",
    "杭州",
    "南京",
    "成都",
    "西安",
    "武汉",
    "苏州",
]

ALLOWED_JOB_FAMILIES = {"backend", "frontend", "ai", "data", "qa", "ops", "product", "design"}
_ASCII_TOKEN_RE = re.compile(r"[a-z0-9.+#_-]+")
_DATE_RANGE_RE = re.compile(r"(20\d{2}[./-]?\d{1,2})\s*(?:-|~|—|–|至|到)\s*(20\d{2}[./-]?\d{1,2}|至今|至今在读|present|now)", re.IGNORECASE)
_INTERNSHIP_EXPLICIT_RE = re.compile(r"(\d{1,2})\s*(?:段|次)\s*(?:实习|工作经历|实训|实践)", re.IGNORECASE)
_PROJECT_EXPLICIT_RE = re.compile(r"(\d{1,2})\s*(?:个|项)\s*(?:项目|课题|作品|实战)", re.IGNORECASE)
_AWARD_EXPLICIT_RE = re.compile(r"(\d{1,2})\s*(?:个|项|次)\s*(?:奖|获奖|荣誉)", re.IGNORECASE)
_MBTI_INLINE_RE = re.compile(r"\b([EI][SN][TF][JP])\b", re.IGNORECASE)
_MBTI_LABEL_RE = re.compile(r"mbti\s*[:：]?\s*([EI][SN][TF][JP])", re.IGNORECASE)
_RULE_PLACEHOLDER_RE = re.compile(r"(规则抽取|自动抽取|每行一条|可编辑)")
_EXPERIENCE_DETAIL_FIELDS = ("internships", "projects", "awards", "open_source", "leadership", "publications")
_EXPERIENCE_ORG_RE = re.compile(
    r"([A-Za-z0-9\u4e00-\u9fff（）()·\-_]{2,40}(?:公司|集团|大学|学院|研究院|研究所|实验室|学校|医院|银行|政府|中心|委员会|Inc|Ltd|Limited))",
    re.IGNORECASE,
)
_EXPERIENCE_BLOCK_ANCHOR_RE = re.compile(r"(实习|项目|课题|系统|平台|岗位|任职|担任|工作经历|就职)", re.IGNORECASE)
_EXPERIENCE_FIELD_ANCHORS: dict[str, re.Pattern[str]] = {
    "internships": re.compile(r"(实习|任职|担任|岗位|就职|公司|单位|部门|工作经历)", re.IGNORECASE),
    "projects": re.compile(r"(项目|系统|平台|课题|开发|搭建|实现|优化)", re.IGNORECASE),
    "awards": re.compile(r"(奖|荣誉|竞赛|奖学金|证书|获奖)", re.IGNORECASE),
    "open_source": re.compile(r"(开源|github|gitee|repo|pull request|issue|贡献)", re.IGNORECASE),
    "leadership": re.compile(r"(组长|负责人|leader|主席|班长|带队|管理)", re.IGNORECASE),
    "publications": re.compile(r"(论文|发表|期刊|会议|专利|著作)", re.IGNORECASE),
}
_MD_IMAGE_LINE_RE = re.compile(r"^!\[[^\]]*\]\([^)]+\)\s*$")
_MD_HEADING_RE = re.compile(r"^#{1,6}\s*")
# Keep student-profile extraction on the globally configured chat model. The
# previous hard-coded glm-4.5 override made this path slower than other AI calls.
_RESUME_EXTRACT_MODEL: str | None = None
_RESUME_FILE_DIRECT_MODEL = "glm-4.5v"
_JSON_BLOCK_RE = re.compile(r"\{[\s\S]*\}$")
_RESUME_SUPPORTED_EXTS = {".pdf", ".docx", ".doc", ".txt"}
_PROFILE_SCHEMA_KEYS = {
    "hard_skills",
    "soft_skills",
    "certificates",
    "experience",
    "experience_details",
    "experience_detail_items",
    "preferences",
    "profile_notes",
    "mbti_type",
}
_PROFILE_BASICS_KEYS = {"hard_skills", "soft_skills", "certificates", "preferences", "mbti_type"}
_PROFILE_INTERNSHIP_KEYS = {"experience", "experience_details", "experience_detail_items"}
_PROFILE_PROJECT_KEYS = {"experience", "experience_details", "experience_detail_items"}
_PROFILE_SUMMARY_KEYS = {"profile_notes"}

logger = logging.getLogger(__name__)


def _to_non_negative_int(value: Any, default: int = 0) -> int:
    try:
        out = int(value)
    except Exception:
        return default
    return max(0, out)


def _count_hits(text: str, keywords: list[str], cap: int) -> int:
    if not text:
        return 0
    lines = [line.strip().lower() for line in str(text).splitlines() if line.strip()]
    if not lines:
        lines = [str(text).lower()]
    hits = 0
    for line in lines:
        if any(kw.lower() in line for kw in keywords):
            hits += 1
    return min(cap, hits)


def _extract_explicit_count(text: str, pattern: re.Pattern[str], cap: int) -> int | None:
    if not text:
        return None
    m = pattern.search(str(text))
    if not m:
        return None
    try:
        value = int(m.group(1))
    except Exception:
        return None
    return min(cap, max(0, value))


def _collect_evidence_lines(
    text: str,
    keywords: list[str],
    limit: int = 3,
    *,
    allow_without_keyword: bool = False,
) -> list[str]:
    if not text:
        return []
    lines = [line.strip() for line in str(text).splitlines() if line.strip()]
    if len(lines) <= 2:
        lines = [seg.strip() for seg in re.split(r"[。；;!?！？\n]+", str(text)) if seg.strip()]
    out: list[str] = []
    seen: set[str] = set()
    for line in lines:
        lower = line.lower()
        if not any(k.lower() in lower for k in keywords):
            continue
        snippet = line[:140]
        if snippet in seen:
            continue
        seen.add(snippet)
        out.append(snippet)
        if len(out) >= limit:
            break
    if out or not allow_without_keyword:
        return out

    # Section text may already be narrowed to internships/projects; when heading
    # is stripped, lines may not explicitly contain keywords. Keep top lines as evidence.
    for line in lines:
        snippet = line[:140]
        if snippet in seen:
            continue
        seen.add(snippet)
        out.append(snippet)
        if len(out) >= limit:
            break
    return out


def _estimate_experience_signals(full_text: str, intern_text: str, proj_text: str, awards_text: str) -> tuple[StudentExperience, dict[str, Any]]:
    intern_explicit = _extract_explicit_count(full_text, _INTERNSHIP_EXPLICIT_RE, cap=10)
    project_explicit = _extract_explicit_count(full_text, _PROJECT_EXPLICIT_RE, cap=15)
    award_explicit = _extract_explicit_count(full_text, _AWARD_EXPLICIT_RE, cap=10)

    intern_section = intern_text or ""
    project_section = proj_text or ""
    awards_section = awards_text or ""

    internships = intern_explicit
    if internships is None:
        section_hits = _count_hits(intern_section, ["实习", "intern", "工作经历", "实践经历", "任职"], cap=10)
        section_ranges = len(_DATE_RANGE_RE.findall(intern_section))
        global_hits = _count_hits(full_text, ["实习", "intern", "工作经历"], cap=6)
        internships = min(10, max(section_hits, section_ranges, global_hits))
        if internships <= 0 and intern_section.strip():
            internships = 1

    projects = project_explicit
    if projects is None:
        section_base = _count_hits(project_section, ["项目", "project", "课题", "作品", "毕业设计", "课程设计"], cap=15)
        section_action = _count_hits(project_section, ["负责", "实现", "搭建", "设计", "优化"], cap=15)
        global_base = _count_projects(full_text)
        projects = min(15, max(section_base, section_action // 2, global_base))
        if projects <= 0 and project_section.strip():
            projects = 1

    awards = award_explicit
    if awards is None:
        awards = min(10, max(_count_awards(awards_section), _count_awards(full_text)))

    open_source = _count_open_source(full_text)
    leadership = _count_leadership(full_text)

    detail = {
        "experience_counter_source": "rule",
        "experience_field_sources": {
            "internships": "rule_explicit" if intern_explicit is not None else "rule_section",
            "projects": "rule_explicit" if project_explicit is not None else "rule_section",
            "awards": "rule_explicit" if award_explicit is not None else "rule_section",
            "open_source": "rule_section",
            "leadership": "rule_section",
        },
        "experience_evidence": {
            "internships": _collect_evidence_lines(
                intern_text or full_text,
                ["实习", "intern", "工作经历", "实践经历"],
                limit=5,
                allow_without_keyword=bool(intern_text and intern_text.strip()),
            ),
            "projects": _collect_evidence_lines(
                proj_text or full_text,
                ["项目", "project", "课题", "作品", "毕业设计", "课程设计"],
                limit=5,
                allow_without_keyword=bool(proj_text and proj_text.strip()),
            ),
            "awards": _collect_evidence_lines(
                awards_text or full_text,
                ["获奖", "奖项", "荣誉", "award", "一等奖", "二等奖", "三等奖"],
                limit=5,
                allow_without_keyword=bool(awards_text and awards_text.strip()),
            ),
            "open_source": _collect_evidence_lines(full_text, ["github", "gitee", "开源", "pull request", "issue"]),
            "leadership": _collect_evidence_lines(full_text, ["组长", "负责人", "leader", "team lead", "带领", "管理", "班长"]),
        },
    }

    exp = StudentExperience(
        internships=_to_non_negative_int(internships),
        projects=_to_non_negative_int(projects),
        awards=_to_non_negative_int(awards),
        open_source=_to_non_negative_int(open_source),
        leadership=_to_non_negative_int(leadership),
    )
    return exp, detail


def _count_projects(text: str) -> int:
    base = _count_hits(text, ["项目", "project", "课题", "作品", "毕业设计", "课程设计"], cap=12)
    line_hits = _count_hits(text, ["负责", "实现", "搭建", "设计", "优化"], cap=12)
    return min(12, max(base, line_hits // 2))


def _count_internships(text: str) -> int:
    base = _count_hits(text, ["实习", "intern", "工作经历", "实践经历", "任职", "工作经验"], cap=6)
    ranged = len(_DATE_RANGE_RE.findall(str(text)))
    return min(6, max(base, ranged))


def _count_awards(text: str) -> int:
    return _count_hits(text, ["获奖", "奖项", "荣誉", "award", "一等奖", "二等奖", "三等奖"], cap=10)


def _count_open_source(text: str) -> int:
    return _count_hits(text, ["github", "gitee", "开源", "open source", "pull request", "issue"], cap=5)


def _count_leadership(text: str) -> int:
    return _count_hits(text, ["组长", "负责人", "leader", "team lead", "带领", "管理", "班长"], cap=5)


def _compute_completeness(profile: StudentProfile, raw_text: str = "") -> float:
    score = 0.0
    score += 15 if profile.hard_skills else 0
    score += 10 if profile.certificates else 0
    score += 15 if profile.experience.projects > 0 else 0
    score += 15 if profile.experience.internships > 0 else 0
    score += 10 if profile.soft_skills else 0
    score += 10 if (raw_text and ("教育" in raw_text or "教育经历" in raw_text)) else (8 if profile.preferences else 0)
    score += 10 if (raw_text and "项目" in raw_text) else (8 if profile.experience.projects > 0 else 0)
    score += 15 if (raw_text and "实习" in raw_text) else (9 if profile.experience.internships > 0 else 0)
    return min(100.0, score)


def _compute_competitiveness(profile: StudentProfile) -> float:
    score = 0.0
    score += min(30.0, len(profile.hard_skills) * 3.0)
    score += min(15.0, len(profile.certificates) * 5.0)
    score += min(25.0, profile.experience.projects * 5.0)
    score += min(20.0, profile.experience.internships * 10.0)
    score += min(10.0, profile.experience.open_source * 5.0)
    score += min(10.0, profile.experience.awards * 3.0)
    score += min(10.0, profile.experience.leadership * 5.0)
    return min(100.0, score)


def _synthesize_profile_notes(profile: StudentProfile) -> str:
    hard = [str(item.mention or "").strip() for item in (profile.hard_skills or []) if str(item.mention or "").strip()][:5]
    soft = [str(item.name or "").strip() for item in (profile.soft_skills or []) if str(item.name or "").strip()][:3]
    preferred = [str(x).strip() for x in (profile.preferences.preferred_job_families or []) if str(x).strip()][:2]

    parts: list[str] = []
    if hard:
        parts.append(f"具备{ '、'.join(hard) }等核心技能")
    if profile.experience.internships > 0 or profile.experience.projects > 0:
        parts.append(
            f"拥有{profile.experience.internships}段实习、{profile.experience.projects}项项目经历"
        )
    if soft:
        parts.append(f"并体现出{ '、'.join(soft) }等综合素质")
    if preferred:
        family_label_map = {
            "backend": "后端",
            "frontend": "前端",
            "ai": "AI算法",
            "data": "数据",
            "qa": "测试",
            "ops": "运维",
            "product": "产品",
            "design": "设计",
        }
        family_text = "、".join([family_label_map.get((_normalize_job_family(x) or x), str(x)) for x in preferred])
        parts.append(f"建议优先冲刺{family_text}方向岗位")
    if not parts:
        return "建议补充项目与实习经历，并完善技能与求职偏好信息，以提升岗位匹配准确性。"
    note = "；".join(parts) + "。"
    return note[:180]


def _dedupe_keep_order(values: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        raw = str(value or "").strip()
        if not raw:
            continue
        key = raw.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(raw)
    return out


def _normalize_job_family(value: str | None) -> str | None:
    raw = str(value or "").strip().lower()
    if not raw:
        return None
    mapping = {
        "后端": "backend",
        "后端开发": "backend",
        "java": "backend",
        "backend": "backend",
        "服务端": "backend",
        "前端": "frontend",
        "前端开发": "frontend",
        "frontend": "frontend",
        "react": "frontend",
        "vue": "frontend",
        "人工智能": "ai",
        "算法": "ai",
        "机器学习": "ai",
        "深度学习": "ai",
        "ai": "ai",
        "aigc": "ai",
        "数据": "data",
        "数据开发": "data",
        "数据分析": "data",
        "数仓": "data",
        "data": "data",
        "测试": "qa",
        "测试开发": "qa",
        "软件测试": "qa",
        "qa": "qa",
        "运维": "ops",
        "云平台": "ops",
        "devops": "ops",
        "sre": "ops",
        "ops": "ops",
        "产品": "product",
        "产品经理": "product",
        "product": "product",
        "设计": "design",
        "ui": "design",
        "ux": "design",
    }
    mapped = mapping.get(raw, raw if raw in ALLOWED_JOB_FAMILIES else None)
    return mapped if mapped in ALLOWED_JOB_FAMILIES else None


def _contains_token(text: str, token: str) -> bool:
    raw_text = normalize_text(text)
    token_raw = normalize_text(token).strip()
    token_norm = normalize_token(token_raw)
    if not token_norm:
        return False
    if re.fullmatch(r"[a-z0-9.+#_-]+", token_norm):
        text_lower = raw_text.lower()
        parts = [p for p in re.split(r"\s+", token_raw.lower()) if p]
        if not parts:
            return False
        if len(parts) > 1:
            pattern = r"[\s\-/_.]*".join(re.escape(p) for p in parts)
            return bool(re.search(pattern, text_lower))
        atom = parts[0]
        return bool(re.search(rf"(?<![a-z0-9.+#_-]){re.escape(atom)}(?![a-z0-9.+#_-])", text_lower))
    return token_norm in normalize_token(raw_text)


def _count_token_occurrence(text: str, token: str) -> int:
    raw_text = normalize_text(text)
    token_raw = normalize_text(token).strip()
    token_norm = normalize_token(token_raw)
    if not token_norm:
        return 0
    if _ASCII_TOKEN_RE.fullmatch(token_norm):
        text_lower = raw_text.lower()
        parts = [p for p in re.split(r"\s+", token_raw.lower()) if p]
        if not parts:
            return 0
        if len(parts) > 1:
            pattern = r"[\s\-/_.]*".join(re.escape(p) for p in parts)
            return len(re.findall(pattern, text_lower))
        atom = parts[0]
        return len(re.findall(rf"(?<![a-z0-9.+#_-]){re.escape(atom)}(?![a-z0-9.+#_-])", text_lower))
    return normalize_token(raw_text).count(token_norm)


def _extract_from_common_list(text: str, candidates: list[str]) -> list[str]:
    out: list[str] = []
    for item in candidates:
        if _contains_token(text, item):
            out.append(item)
    return _dedupe_keep_order(out)


def _extract_preference_hints(text: str) -> StudentPreferences:
    text_norm = normalize_text(text)
    locations = [loc for loc in COMMON_LOCATIONS if loc in text_norm]
    families: list[str] = []
    for raw in [
        "后端",
        "前端",
        "人工智能",
        "算法",
        "数据分析",
        "测试",
        "运维",
        "产品",
        "设计",
    ]:
        if raw in text_norm:
            norm = _normalize_job_family(raw)
            if norm and norm not in families:
                families.append(norm)
    return StudentPreferences(
        preferred_locations=_dedupe_keep_order(locations),
        preferred_job_families=families,
    )


def _extract_mbti_type_from_text(text: str) -> str | None:
    raw_text = str(text or "")
    if not raw_text:
        return None
    label_match = _MBTI_LABEL_RE.search(raw_text)
    if label_match:
        return normalize_mbti_type(label_match.group(1))
    inline = _MBTI_INLINE_RE.findall(raw_text)
    for token in inline:
        normalized = normalize_mbti_type(token)
        if normalized:
            return normalized
    return None


def _safe_list(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    out: list[str] = []
    for value in values:
        raw = str(value or "").strip()
        if raw:
            out.append(raw)
    return _dedupe_keep_order(out)


def _manual_payload_to_text(payload: dict[str, Any] | None) -> str:
    payload = payload or {}
    lines: list[str] = []
    if payload.get("name"):
        lines.append(f"姓名: {payload.get('name')}")
    mbti_type = normalize_mbti_type(payload.get("mbti_type"))
    if mbti_type:
        lines.append(f"MBTI: {mbti_type}")

    hard_skills = _safe_list(payload.get("hard_skills"))
    soft_skills = _safe_list(payload.get("soft_skills"))
    certificates = _safe_list(payload.get("certificates"))
    if hard_skills:
        lines.append("硬技能: " + "、".join(hard_skills))
    if soft_skills:
        lines.append("软技能: " + "、".join(soft_skills))
    if certificates:
        lines.append("证书: " + "、".join(certificates))

    exp = payload.get("experience") or {}
    exp_pairs = [
        ("实习次数", exp.get("internships")),
        ("项目次数", exp.get("projects")),
        ("获奖次数", exp.get("awards")),
        ("论文次数", exp.get("publications")),
        ("开源次数", exp.get("open_source")),
        ("担任负责人次数", exp.get("leadership")),
    ]
    exp_text = [f"{name}:{_to_non_negative_int(value)}" for name, value in exp_pairs if value is not None]
    if exp_text:
        lines.append("经历统计: " + "，".join(exp_text))
    exp_detail_items = _normalize_experience_detail_items(payload.get("experience_detail_items"))
    exp_details = _normalize_experience_details(payload.get("experience_details"))
    detail_labels = {
        "internships": "实习详情",
        "projects": "项目详情",
        "awards": "获奖详情",
        "open_source": "开源详情",
        "leadership": "负责人详情",
        "publications": "论文详情",
    }
    for field, label in detail_labels.items():
        item_lines: list[str] = []
        for item in exp_detail_items.get(field) or []:
            content = str(item.get("content") or "").strip()
            evidence = str(item.get("evidence") or "").strip()
            if content and evidence:
                item_lines.append(content)
            elif content:
                item_lines.append(content)
            elif evidence:
                item_lines.append(evidence)
        detail_lines = item_lines or [str(x).strip() for x in (exp_details.get(field) or []) if str(x).strip()]
        if detail_lines:
            lines.append(f"{label}: " + "；".join(detail_lines[:5]))

    pref = payload.get("preferences") or {}
    pref_locs = _safe_list(pref.get("preferred_locations"))
    pref_fams = _safe_list(pref.get("preferred_job_families"))
    if pref_locs:
        lines.append("意向城市: " + "、".join(pref_locs))
    if pref_fams:
        lines.append("意向方向: " + "、".join(pref_fams))
    if pref.get("target_salary_min") is not None or pref.get("target_salary_max") is not None:
        lines.append(
            f"意向薪资: {pref.get('target_salary_min') or ''}-{pref.get('target_salary_max') or ''}"
        )
    if pref.get("notes"):
        lines.append("补充说明: " + str(pref.get("notes")))
    resume_text = normalize_text(str(payload.get("resume_text") or ""))
    if resume_text:
        lines.append("简历文本补充: " + resume_text[:4000])

    return normalize_text("\n".join(lines))


def _rank_candidates_by_text(text: str, candidates: list[str], limit: int) -> list[str]:
    text_plain = normalize_text(text)
    text_compact = normalize_token(text)
    scored: list[tuple[int, int, str]] = []
    for candidate in _dedupe_keep_order(candidates):
        token = normalize_token(candidate)
        if not token:
            continue
        hits = _count_token_occurrence(text_plain, candidate)
        if hits <= 0:
            continue
        first_pos = text_compact.find(token)
        scored.append((hits, -first_pos, candidate))
    scored.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
    ranked = [x[2] for x in scored][:limit]
    if len(ranked) < limit:
        ranked.extend([x for x in _dedupe_keep_order(candidates) if x not in ranked][: max(0, limit - len(ranked))])
    return ranked[:limit]


def _build_candidate_list(
    text: str,
    *,
    item_type: str,
    manual_items: list[str] | None = None,
    common_items: list[str] | None = None,
    limit: int = 20,
) -> list[str]:
    base = _dedupe_keep_order((manual_items or []) + (common_items or []))
    try:
        mentions = extract_dictionary_mentions(text, item_type, section="candidate")
        base = _dedupe_keep_order([it.get("name_zh") for it in mentions if it.get("name_zh")] + base)
    except Exception:
        pass
    return _rank_candidates_by_text(text=text, candidates=base, limit=limit)


def _looks_like_profile_json(data: dict[str, Any]) -> bool:
    if not isinstance(data, dict):
        return False
    required = {"hard_skills", "soft_skills", "certificates", "experience", "preferences"}
    if not required.issubset(set(data.keys())):
        return False
    if not isinstance(data.get("hard_skills"), list):
        return False
    if not isinstance(data.get("soft_skills"), list):
        return False
    if not isinstance(data.get("certificates"), list):
        return False
    exp = data.get("experience")
    if not isinstance(exp, dict):
        return False
    if not isinstance(data.get("preferences"), dict):
        return False
    return True


def _safe_text_list(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    out: list[str] = []
    for value in values:
        raw = ""
        if isinstance(value, dict):
            raw = str(value.get("name") or value.get("value") or "").strip()
        else:
            raw = str(value or "").strip()
        if raw:
            out.append(raw)
    return _dedupe_keep_order(out)


def _summarize_experience_content(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    if len(raw) <= 64:
        return raw
    for sep in ("。", "；", ";", "，", ",", "：", ":"):
        if sep in raw:
            head = raw.split(sep, 1)[0].strip()
            if 4 <= len(head) <= 72:
                return head
    return raw[:72].strip()


def _experience_item_signature(field: str, content: str, evidence: str = "") -> str:
    text = normalize_text(f"{content}\n{evidence}")
    text = re.sub(r"\s+", "", text).lower()
    if not text:
        return ""
    date_match = _DATE_RANGE_RE.search(text)
    org_match = _EXPERIENCE_ORG_RE.search(text)
    if field == "awards":
        # Awards are often repeated in resume summaries and detail sections.
        text = re.sub(r"(获得|荣获|获|证书|荣誉|奖项|奖励|竞赛|比赛|大赛)", "", text)
        text = re.sub(r"(一等奖|二等奖|三等奖|优秀奖|金奖|银奖|铜奖|省级|国家级|校级|院级)", lambda m: m.group(1), text)
        return f"a:{normalize_token(text)[:80]}"
    if date_match and org_match:
        return f"do:{normalize_token(date_match.group(0))}:{normalize_token(org_match.group(1))[:48]}"
    if org_match:
        return f"o:{normalize_token(org_match.group(1))[:48]}"
    if date_match:
        return f"d:{normalize_token(date_match.group(0))}"
    return f"s:{normalize_token(_summarize_experience_content(text))[:64]}"


def _normalize_experience_detail_items(raw: Any) -> dict[str, list[dict[str, str]]]:
    if not isinstance(raw, dict):
        return {}

    def _to_items(field: str, value: Any) -> list[dict[str, str]]:
        if isinstance(value, str):
            values: list[Any] = [seg.strip() for seg in re.split(r"[\r\n]+", value) if seg.strip()]
        elif isinstance(value, list):
            values = list(value)
        else:
            return []
        out: list[dict[str, str]] = []
        seen: set[str] = set()
        for item in values:
            content = ""
            evidence = ""
            if isinstance(item, dict):
                content = str(
                    item.get("content")
                    or item.get("item")
                    or item.get("summary")
                    or item.get("title")
                    or item.get("name")
                    or ""
                ).strip()
                evidence = str(item.get("evidence") or item.get("proof") or item.get("source_text") or item.get("raw") or "").strip()
            else:
                text = str(item or "").strip()
                content = _summarize_experience_content(text)
                evidence = text
            if not content and not evidence:
                continue
            if not content:
                content = _summarize_experience_content(evidence)
            if not evidence and field != "awards":
                evidence = content
            if len(content) < 2:
                continue
            if field != "awards" and len(evidence) < 4:
                continue
            if _RULE_PLACEHOLDER_RE.search(content) or (evidence and _RULE_PLACEHOLDER_RE.search(evidence)):
                continue
            key = _experience_item_signature(field, content, evidence)
            if key in seen:
                continue
            seen.add(key)
            out.append({"content": content[:180], "evidence": evidence[:300]})
            if len(out) >= 8:
                break
        return out

    out: dict[str, list[dict[str, str]]] = {}
    for field in _EXPERIENCE_DETAIL_FIELDS:
        values = _to_items(field, raw.get(field))
        if values:
            out[field] = values
    return out


def _experience_item_texts(items: list[dict[str, str]] | None) -> list[str]:
    rows = items or []
    out: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        text = str(row.get("content") or row.get("evidence") or "").strip()
        if text:
            out.append(text)
    return out


def _estimate_experience_block_count(field: str, items: list[dict[str, str]] | None) -> int:
    texts = _experience_item_texts(items)
    if not texts:
        return 0

    field_anchor_re = _EXPERIENCE_FIELD_ANCHORS.get(field, _EXPERIENCE_BLOCK_ANCHOR_RE)
    has_anchor = any(
        _DATE_RANGE_RE.search(text)
        or _EXPERIENCE_ORG_RE.search(text)
        or _EXPERIENCE_BLOCK_ANCHOR_RE.search(text)
        or field_anchor_re.search(text)
        for text in texts
    )
    # Generic anti-split: when all lines are unanchored fragments, treat them as one block.
    if (not has_anchor) and len(texts) >= 2:
        return 1

    seen: set[str] = set()
    for text in texts:
        signature = ""
        date_match = _DATE_RANGE_RE.search(text)
        if date_match:
            signature = f"d:{normalize_token(date_match.group(1))}-{normalize_token(date_match.group(2))}"
        else:
            org_match = _EXPERIENCE_ORG_RE.search(text)
            if org_match:
                signature = f"o:{normalize_token(org_match.group(1))[:48]}"
            else:
                head = _summarize_experience_content(text)
                signature = f"s:{normalize_token(head)[:48]}"
        if signature:
            seen.add(signature)
    return len(seen) if seen else len(texts)


def _coerce_llm_experience_count(field: str, raw_count: Any, items: list[dict[str, str]] | None) -> int:
    base = _to_non_negative_int(raw_count)
    block_count = _estimate_experience_block_count(field, items)
    if block_count <= 0:
        return base
    if base <= 0:
        return block_count
    low, high = (base, block_count) if base <= block_count else (block_count, base)
    if low > 0 and high >= (low * 2):
        return low
    return max(base, block_count)


def _detail_items_to_evidence_map(items_map: dict[str, list[dict[str, str]]]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for field in _EXPERIENCE_DETAIL_FIELDS:
        rows = items_map.get(field) or []
        lines = _dedupe_keep_order(
            [
                str(row.get("evidence") or row.get("content") or "").strip()
                for row in rows
                if isinstance(row, dict) and str(row.get("evidence") or row.get("content") or "").strip()
            ]
        )
        if lines:
            out[field] = [line[:280] for line in lines[:8]]
    return out


def _evidence_map_to_detail_items(evidence_map: dict[str, list[str]]) -> dict[str, list[dict[str, str]]]:
    out: dict[str, list[dict[str, str]]] = {}
    for field in _EXPERIENCE_DETAIL_FIELDS:
        lines = [str(line or "").strip() for line in (evidence_map.get(field) or []) if str(line or "").strip()]
        if not lines:
            continue
        items = []
        for line in lines[:8]:
            items.append({"content": _summarize_experience_content(line), "evidence": line[:300]})
        if items:
            out[field] = items
    return out


def _experience_count_with_items(value: Any, items: list[dict[str, str]] | None) -> int:
    base = _to_non_negative_int(value)
    return max(base, len(items or []))


def _normalize_experience_details(raw: Any) -> dict[str, list[str]]:
    if not isinstance(raw, dict):
        return {}

    def _to_lines(value: Any) -> list[str]:
        if isinstance(value, list):
            lines = []
            for item in value:
                if isinstance(item, dict):
                    text = str(item.get("evidence") or item.get("content") or item.get("item") or item.get("summary") or "").strip()
                else:
                    text = str(item or "").strip()
                lines.append(text)
            return [
                line[:280]
                for line in lines
                if line and len(line) >= 4 and not _RULE_PLACEHOLDER_RE.search(line)
            ]
        if isinstance(value, str):
            lines = [seg.strip() for seg in re.split(r"[\r\n]+", value) if seg.strip()]
            return [
                line[:280]
                for line in lines
                if line and len(line) >= 4 and not _RULE_PLACEHOLDER_RE.search(line)
            ]
        return []

    out: dict[str, list[str]] = {}
    for field in _EXPERIENCE_DETAIL_FIELDS:
        vals = _to_lines(raw.get(field))
        if vals:
            out[field] = vals[:8]
    return out


def _normalize_llm_profile_json(data: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(data, dict):
        return None
    root: dict[str, Any] = data
    for key in ("profile", "result", "data", "output"):
        nested = root.get(key)
        if isinstance(nested, dict):
            root = nested
            break

    hard_raw = root.get("hard_skills")
    if hard_raw is None:
        hard_raw = root.get("hardSkills") or root.get("skills")
    soft_raw = root.get("soft_skills")
    if soft_raw is None:
        soft_raw = root.get("softSkills")
    cert_raw = root.get("certificates")
    if cert_raw is None:
        cert_raw = root.get("certs") or root.get("licenses")

    exp_raw = root.get("experience")
    if not isinstance(exp_raw, dict):
        exp_raw = root.get("exp") if isinstance(root.get("exp"), dict) else {}

    pref_raw = root.get("preferences")
    if not isinstance(pref_raw, dict):
        pref_raw = root.get("preference") if isinstance(root.get("preference"), dict) else {}
    if not isinstance(pref_raw, dict):
        pref_raw = root.get("prefs") if isinstance(root.get("prefs"), dict) else {}

    details_raw = root.get("experience_details")
    if not isinstance(details_raw, dict):
        details_raw = root.get("experienceDetails") if isinstance(root.get("experienceDetails"), dict) else {}
    detail_items_raw = root.get("experience_detail_items")
    if not isinstance(detail_items_raw, dict):
        detail_items_raw = root.get("experienceDetailItems") if isinstance(root.get("experienceDetailItems"), dict) else {}

    salary_min_raw = pref_raw.get("target_salary_min")
    if salary_min_raw is None:
        salary_min_raw = pref_raw.get("salary_min")
    if salary_min_raw is None:
        salary_min_raw = pref_raw.get("expect_salary_min")
    salary_max_raw = pref_raw.get("target_salary_max")
    if salary_max_raw is None:
        salary_max_raw = pref_raw.get("salary_max")
    if salary_max_raw is None:
        salary_max_raw = pref_raw.get("expect_salary_max")
    mbti_raw = (
        root.get("mbti_type")
        if root.get("mbti_type") is not None
        else (
            root.get("mbti")
            if root.get("mbti") is not None
            else (
                pref_raw.get("mbti_type")
                if pref_raw.get("mbti_type") is not None
                else pref_raw.get("mbti")
            )
        )
    )
    mbti_type = normalize_mbti_type(mbti_raw)

    normalized_experience_details = _normalize_experience_details(details_raw)
    normalized_detail_items = _normalize_experience_detail_items(detail_items_raw)
    if not normalized_detail_items and normalized_experience_details:
        normalized_detail_items = _evidence_map_to_detail_items(normalized_experience_details)
    if not normalized_experience_details and normalized_detail_items:
        normalized_experience_details = _detail_items_to_evidence_map(normalized_detail_items)

    normalized: dict[str, Any] = {
        "mbti_type": mbti_type,
        "mbti_source": "llm" if mbti_type else None,
        "hard_skills": hard_raw if isinstance(hard_raw, list) else [],
        "soft_skills": soft_raw if isinstance(soft_raw, list) else [],
        "certificates": cert_raw if isinstance(cert_raw, list) else [],
        "experience": {
            "internships": _to_non_negative_int(exp_raw.get("internships")),
            "projects": _to_non_negative_int(exp_raw.get("projects")),
            "awards": _to_non_negative_int(exp_raw.get("awards")),
            "publications": _to_non_negative_int(exp_raw.get("publications")),
            "open_source": _to_non_negative_int(exp_raw.get("open_source")),
            "leadership": _to_non_negative_int(exp_raw.get("leadership")),
        },
        "preferences": {
            "preferred_locations": _safe_text_list(
                pref_raw.get("preferred_locations")
                if pref_raw.get("preferred_locations") is not None
                else (
                    pref_raw.get("locations")
                    if pref_raw.get("locations") is not None
                    else pref_raw.get("preferred_cities")
                )
            ),
            "preferred_job_families": _safe_text_list(
                pref_raw.get("preferred_job_families")
                if pref_raw.get("preferred_job_families") is not None
                else (pref_raw.get("job_families") if pref_raw.get("job_families") is not None else pref_raw.get("directions"))
            ),
            "target_salary_min": _to_non_negative_int(salary_min_raw) if salary_min_raw is not None else None,
            "target_salary_max": _to_non_negative_int(salary_max_raw) if salary_max_raw is not None else None,
            "notes": str(pref_raw.get("notes") or pref_raw.get("remark") or "").strip(),
        },
        "profile_notes": str(root.get("profile_notes") or root.get("summary") or "").strip(),
        "experience_details": normalized_experience_details,
        "experience_detail_items": normalized_detail_items,
    }
    return normalized


def _normalize_resume_text_for_llm(text: str) -> str:
    raw = normalize_text(text)
    if not raw:
        return ""
    lines: list[str] = []
    for row in raw.splitlines():
        line = str(row or "").strip()
        if not line:
            continue
        if _MD_IMAGE_LINE_RE.match(line):
            continue
        line = _MD_HEADING_RE.sub("", line)
        line = re.sub(r"\s+", " ", line).strip()
        if not line:
            continue
        lines.append(line)
    merged: list[str] = []
    for line in lines:
        if (
            merged
            and len(line) <= 12
            and re.match(r"^[A-Za-z0-9%()（）、,.，。\-_/+]+$", line)
            and re.search(r"[A-Za-z0-9%()）]$", merged[-1])
        ):
            merged[-1] = f"{merged[-1]} {line}"
            continue
        merged.append(line)
    return normalize_text("\n".join(merged))


def _student_profile_common_payload(text: str, manual_payload: dict[str, Any] | None = None) -> dict[str, Any] | None:
    text = normalize_text(text)
    manual_payload = manual_payload or {}
    resume_text = _normalize_resume_text_for_llm(text)
    resume_file_path = str(manual_payload.get("resume_file_path") or "").strip()
    resume_filename = str(manual_payload.get("resume_filename") or "").strip()
    resume_file_type = str(manual_payload.get("resume_file_type") or "").strip().upper()
    resume_extract_source = str(manual_payload.get("resume_extract_source") or "").strip()
    manual_text = _manual_payload_to_text(manual_payload)
    if not resume_text and not manual_text and not resume_file_path:
        return None

    manual_hard = _safe_list(manual_payload.get("hard_skills"))
    manual_soft = _safe_list(manual_payload.get("soft_skills"))
    manual_certs = _safe_list(manual_payload.get("certificates"))
    manual_exp_details = _normalize_experience_details(manual_payload.get("experience_details"))
    candidate_context = "\n".join([resume_text, manual_text]).strip()

    candidate_hard = _build_candidate_list(
        candidate_context,
        item_type="hard_skill",
        manual_items=manual_hard,
        common_items=COMMON_HARD_SKILLS,
        limit=120,
    )
    candidate_soft = _build_candidate_list(
        candidate_context,
        item_type="soft_skill",
        manual_items=manual_soft,
        common_items=COMMON_SOFT_SKILLS,
        limit=80,
    )
    candidate_certs = _build_candidate_list(
        candidate_context,
        item_type="certificate",
        manual_items=manual_certs,
        common_items=COMMON_CERTIFICATES,
        limit=80,
    )

    payload = {
        "resume_document": {
            "filename": resume_filename or None,
            "file_type": resume_file_type or None,
            "source": resume_extract_source or None,
            "parser": "zhipu_files_parser_sync" if resume_extract_source == "zhipu_file_api" else "local_extract",
        },
        "resume_text": resume_text[:20000],
        "manual_input": {
            "name": manual_payload.get("name"),
            "mbti_type": normalize_mbti_type(manual_payload.get("mbti_type")),
            "hard_skills": manual_hard[:30],
            "soft_skills": manual_soft[:30],
            "certificates": manual_certs[:30],
            "experience": manual_payload.get("experience") or {},
            "experience_details": {k: v[:5] for k, v in manual_exp_details.items()},
            "experience_detail_items": {
                k: v[:5] for k, v in _normalize_experience_detail_items(manual_payload.get("experience_detail_items")).items()
            },
            "preferences": manual_payload.get("preferences") or {},
            "notes": str(manual_payload.get("notes") or "")[:500],
        },
        "candidate_lists": {
            "hard_skill_hints": candidate_hard[:100],
            "soft_skill_hints": candidate_soft[:60],
            "certificate_hints": candidate_certs[:60],
        },
    }
    if resume_file_path and not payload["resume_text"]:
        try:
            fallback_text, fallback_source = extract_resume_text_smart(
                resume_file_path,
                filename=resume_filename or None,
            )
            fallback_text = _normalize_resume_text_for_llm(fallback_text)
            if fallback_text:
                payload["resume_text"] = fallback_text[:20000]
                payload["resume_document"]["source"] = fallback_source or resume_extract_source or None
                payload["resume_document"]["parser"] = (
                    "zhipu_files_parser_sync" if fallback_source == "zhipu_file_api" else "local_extract"
                )
                logger.info(
                    "简历画像使用文本链路 source=%s text_chars=%s",
                    payload["resume_document"]["source"],
                    len(fallback_text),
                )
        except Exception as e:
            logger.warning("简历文本链路提取失败：%s", e)
    return payload


def _merge_profile_json_parts(parts: list[dict[str, Any] | None]) -> dict[str, Any] | None:
    merged: dict[str, Any] = {}
    for part in parts:
        if not isinstance(part, dict):
            continue
        for key, value in part.items():
            if key in {"experience", "experience_details", "experience_detail_items", "preferences"} and isinstance(value, dict):
                current = merged.get(key)
                if isinstance(current, dict):
                    current.update(value)
                else:
                    merged[key] = dict(value)
            elif key in {"hard_skills", "soft_skills", "certificates"} and isinstance(value, list):
                current_list = merged.get(key)
                if isinstance(current_list, list):
                    current_list.extend(value)
                else:
                    merged[key] = list(value)
            elif value is not None and value != "":
                merged[key] = value
    if not merged:
        return None
    normalized = _normalize_llm_profile_json(merged)
    return normalized if normalized else merged


def _llm_extract_student_profile_four_pass(payload: dict[str, Any]) -> dict[str, Any] | None:
    if not deepseek_json_enabled():
        return None

    resume_text = str(payload.get("resume_text") or "")[:16000]
    manual_input = payload.get("manual_input") if isinstance(payload.get("manual_input"), dict) else {}
    manual_text = _manual_payload_to_text(manual_input)
    doc_info = json.dumps(payload.get("resume_document") or {}, ensure_ascii=False)
    candidates = payload.get("candidate_lists") if isinstance(payload.get("candidate_lists"), dict) else {}
    hard_hints = "、".join(_safe_list(candidates.get("hard_skill_hints"))[:60])
    soft_hints = "、".join(_safe_list(candidates.get("soft_skill_hints"))[:40])
    cert_hints = "、".join(_safe_list(candidates.get("certificate_hints"))[:40])

    def _call(system: str, user: str, trace_context: str, max_tokens: int, expected_keys: set[str]) -> dict[str, Any] | None:
        try:
            data = deepseek_chat_json_sync(
                system,
                user,
                trace_context=trace_context,
                max_tokens=max_tokens,
                expected_root_keys=expected_keys,
            )
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    basics_system = """你是大学生就业画像结构化助手。只输出一个 JSON 对象。
只抽取 hard_skills, soft_skills, certificates, preferences, mbti_type。
规则：简历文本来自整份 Word/PDF 抽取，换行可能破坏上下文；按整份简历理解。hard_skills 最多 28 项，只保留岗位主线、可证明、对求职最关键的技能。每个 hard_skills 项必须是 {"name":"技能名","evidence":"证据","level":"了解|熟悉|熟练|项目实战|可独立交付"}，level 根据技能栏、项目、实习、代码/面试证据判断；没有证据但被明确列出时默认“可独立交付”。每条 evidence 不超过 40 字。证书只写明确证书或语言等级，不把竞赛奖项写进 certificates。preferred_job_families 只能从 backend, frontend, ai, data, qa, ops, product, design 中选。"""
    basics_user = (
        "简历文件上下文：\n" + doc_info
        + "\n\n简历文本：\n" + resume_text
        + "\n\n手动录入：\n" + (manual_text[:3000] if manual_text else "（无）")
        + "\n\n候选硬技能：" + hard_hints
        + "\n候选软技能：" + soft_hints
        + "\n候选证书：" + cert_hints
    )

    internship_system = """你是大学生就业画像结构化助手。只输出一个 JSON 对象。
只抽取实习，固定结构：
{"experience":{"internships":0},"experience_details":{"internships":[]},"experience_detail_items":{"internships":[{"content":"实习总结概括","evidence":"具体做了什么实习"}]}}
规则：输入是整份简历提取文本，不是逐条列表；必须恢复上下文。同一公司/同一岗位/同一时间段只算一段实习，禁止按换行、职责点、技术点拆多条。content 写一行总结；evidence 写具体做了什么实习，不超过 180 字。internships 数量必须等于条目数。"""
    internship_user = "简历文件上下文：\n" + doc_info + "\n\n简历文本：\n" + resume_text + "\n\n手动录入：\n" + (manual_text[:2000] if manual_text else "（无）")

    project_system = """你是大学生就业画像结构化助手。只输出一个 JSON 对象。
只抽取项目和奖项，固定结构：
{"experience":{"projects":0,"awards":0,"publications":0,"open_source":0,"leadership":0},"experience_details":{"projects":[],"awards":[],"publications":[],"open_source":[],"leadership":[]},"experience_detail_items":{"projects":[{"content":"项目总结概括","evidence":"项目具体解释"}],"awards":[{"content":"获得奖项","evidence":""}],"publications":[],"open_source":[],"leadership":[]}}
规则：同一项目名称/系统/课题只算一个项目，禁止按亮点和职责拆成多条。projects.content 写项目总结；projects.evidence 写项目具体解释，不超过 180 字。awards 只写奖项名称；同一奖项多处出现也只能保留一次；awards.evidence 必须为空字符串。没有明确论文/开源/负责人经历就填 0 和空数组。"""
    project_user = "简历文件上下文：\n" + doc_info + "\n\n简历文本：\n" + resume_text + "\n\n手动录入：\n" + (manual_text[:2000] if manual_text else "（无）")

    summary_system = """你是大学生就业画像总结助手。只输出一个 JSON 对象：{"profile_notes":"..."}。
根据整份简历文本和手动录入信息，输出 80-160 字中文总结，必须包含优势技能、实习/项目亮点、建议方向。禁止编造新经历，禁止输出 JSON 以外文字。"""
    summary_user = (
        "简历文件上下文：\n" + doc_info
        + "\n\n简历文本：\n" + resume_text
        + "\n\n手动录入：\n" + (manual_text[:2500] if manual_text else "（无）")
    )

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        future_basics = executor.submit(_call, basics_system, basics_user, "student_profile.extract.basics.deepseek", 1800, _PROFILE_BASICS_KEYS)
        future_internships = executor.submit(_call, internship_system, internship_user, "student_profile.extract.internships.deepseek", 2000, _PROFILE_INTERNSHIP_KEYS)
        future_projects = executor.submit(_call, project_system, project_user, "student_profile.extract.projects_awards.deepseek", 2200, _PROFILE_PROJECT_KEYS)
        future_summary = executor.submit(_call, summary_system, summary_user, "student_profile.extract.summary.deepseek", 600, _PROFILE_SUMMARY_KEYS)
        basics_part = future_basics.result()
        internships_part = future_internships.result()
        projects_part = future_projects.result()
        summary_part = future_summary.result()

    merged = _merge_profile_json_parts([basics_part, internships_part, projects_part, summary_part])
    if not merged:
        return None
    return merged


def _zhipu_chat_url(base_url: str) -> str:
    base = str(base_url or "").strip().rstrip("/")
    if not base:
        return ""
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def _guess_resume_mime(ext: str) -> str:
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


def _collect_chat_content_text(value: Any) -> list[str]:
    out: list[str] = []
    if value is None:
        return out
    if isinstance(value, str):
        text = str(value).strip()
        if text:
            out.append(text)
        return out
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                text = str(item.get("text") or "").strip()
                if text:
                    out.append(text)
                continue
            out.extend(_collect_chat_content_text(item))
        return out
    if isinstance(value, dict):
        for key in ("text", "content", "output_text", "reasoning_content", "arguments"):
            if key in value:
                out.extend(_collect_chat_content_text(value.get(key)))
        return out
    return out


def _extract_json_objects(text: str) -> list[dict[str, Any]]:
    in_str = False
    esc = False
    depth = 0
    start = -1
    out: list[dict[str, Any]] = []
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            continue
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
            continue
        if ch == "}":
            if depth <= 0:
                continue
            depth -= 1
            if depth == 0 and start >= 0:
                snippet = text[start : i + 1]
                try:
                    parsed = json.loads(snippet)
                except Exception:
                    start = -1
                    continue
                if isinstance(parsed, dict):
                    out.append(parsed)
                start = -1
    return out


def _parse_json_from_chat_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    try:
        choice = (payload.get("choices") or [{}])[0]
        message = choice.get("message") or {}
    except Exception:
        message = {}
    parts = _collect_chat_content_text(message.get("content"))
    if not parts:
        parts = _collect_chat_content_text(message.get("reasoning_content"))
    if not parts:
        parts = _collect_chat_content_text(payload.get("output_text"))
    text = normalize_text("\n".join([p for p in parts if p]))
    if not text:
        return None
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    m = _JSON_BLOCK_RE.search(text)
    if m:
        try:
            parsed = json.loads(m.group(0))
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
    candidates = _extract_json_objects(text)
    if candidates:
        return candidates[-1]
    return None


def _llm_extract_student_profile_from_file(
    *,
    system_prompt: str,
    context_payload: dict[str, Any],
    resume_file_path: str,
    resume_filename: str,
    resume_file_type: str,
) -> dict[str, Any] | None:
    cfg = load_effective_llm_config()
    provider = str(cfg.get("provider") or "").strip().lower()
    api_key = str(cfg.get("api_key") or "").strip()
    chat_url = _zhipu_chat_url(str(cfg.get("base_url") or ""))
    if provider != "zhipu" or (not api_key) or (not chat_url):
        return None

    path = Path(str(resume_file_path or "").strip())
    ext = path.suffix.lower()
    if (not path.exists()) or ext not in _RESUME_SUPPORTED_EXTS:
        return None
    file_bytes = path.read_bytes()
    if not file_bytes:
        return None

    file_b64 = base64.b64encode(file_bytes).decode("ascii")
    mime = _guess_resume_mime(ext)
    file_urls: list[tuple[str, str]] = [
        ("base64", file_b64),
        ("data_url", f"data:{mime};base64,{file_b64}"),
    ]
    safe_payload = dict(context_payload or {})
    # Direct file path should rely on the file itself, not intermediate extracted text.
    safe_payload.pop("resume_text", None)
    safe_payload["resume_document"] = dict(safe_payload.get("resume_document") or {})
    safe_payload["resume_document"]["filename"] = resume_filename or safe_payload["resume_document"].get("filename")
    safe_payload["resume_document"]["file_type"] = resume_file_type or safe_payload["resume_document"].get("file_type")
    safe_payload["resume_document"]["source"] = "direct_file_model"
    user_text = (
        "请直接读取上传的简历文件内容并抽取结构化画像。"
        "下面是手动录入与候选关键词提示（仅辅助，不可覆盖文件证据）：\n"
        + json.dumps(safe_payload, ensure_ascii=False)
    )

    timeout = max(60.0, float(cfg.get("timeout_seconds") or 60))
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    retryable_statuses = {429, 500, 502, 503, 504}
    max_attempts = 3
    with httpx.Client(timeout=timeout) as client:
        for url_mode, file_url in file_urls:
            for attempt in range(1, max_attempts + 1):
                request_payload = {
                    "model": _RESUME_FILE_DIRECT_MODEL,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {
                            "role": "user",
                            "content": [
                                {"type": "file_url", "file_url": {"url": file_url}},
                                {"type": "text", "text": user_text},
                            ],
                        },
                    ],
                    "stream": False,
                    "temperature": 0.0,
                    "thinking": {"type": "enabled"},
                    "max_tokens": 2600,
                }
                logger.info(
                    "[STUDENT_PROFILE][FILE_DIRECT_REQUEST] model=%s filename=%s ext=%s bytes=%s url_mode=%s attempt=%s/%s",
                    _RESUME_FILE_DIRECT_MODEL,
                    resume_filename or path.name,
                    ext,
                    len(file_bytes),
                    url_mode,
                    attempt,
                    max_attempts,
                )
                try:
                    resp = client.post(chat_url, headers=headers, json=request_payload)
                    if resp.status_code >= 400:
                        logger.warning(
                            "[STUDENT_PROFILE][FILE_DIRECT_FAIL] model=%s url_mode=%s attempt=%s/%s status=%s body=%s",
                            _RESUME_FILE_DIRECT_MODEL,
                            url_mode,
                            attempt,
                            max_attempts,
                            resp.status_code,
                            (resp.text or "")[:240],
                        )
                        if (resp.status_code in retryable_statuses) and attempt < max_attempts:
                            time.sleep(float(2 ** (attempt - 1)))
                            continue
                        break
                    data = resp.json() if resp.text else {}
                except Exception as e:
                    logger.warning(
                        "[STUDENT_PROFILE][FILE_DIRECT_EXCEPTION] url_mode=%s attempt=%s/%s err=%s",
                        url_mode,
                        attempt,
                        max_attempts,
                        e,
                    )
                    if attempt < max_attempts:
                        time.sleep(float(2 ** (attempt - 1)))
                        continue
                    break
                parsed = _parse_json_from_chat_payload(data)
                if isinstance(parsed, dict):
                    logger.info("[STUDENT_PROFILE][FILE_DIRECT_RESPONSE] url_mode=%s parsed=true", url_mode)
                    return parsed
                logger.warning("[STUDENT_PROFILE][FILE_DIRECT_RESPONSE] url_mode=%s parsed=false", url_mode)
                break
    return None


def _llm_extract_student_profile(text: str, manual_payload: dict[str, Any] | None = None) -> dict[str, Any] | None:
    if not deepseek_json_enabled() and not llm_client.is_enabled():
        return None
    common_payload = _student_profile_common_payload(text, manual_payload)
    if not common_payload:
        return None
    if deepseek_json_enabled():
        four_pass = _llm_extract_student_profile_four_pass(common_payload)
        if four_pass and _looks_like_profile_json(four_pass):
            return four_pass
    text = normalize_text(text)
    manual_payload = manual_payload or {}
    resume_text = _normalize_resume_text_for_llm(text)
    resume_file_path = str(manual_payload.get("resume_file_path") or "").strip()
    resume_filename = str(manual_payload.get("resume_filename") or "").strip()
    resume_file_type = str(manual_payload.get("resume_file_type") or "").strip().upper()
    resume_extract_source = str(manual_payload.get("resume_extract_source") or "").strip()
    manual_text = _manual_payload_to_text(manual_payload)
    if not resume_text and not manual_text and not resume_file_path:
        return None

    manual_hard = _safe_list(manual_payload.get("hard_skills"))
    manual_soft = _safe_list(manual_payload.get("soft_skills"))
    manual_certs = _safe_list(manual_payload.get("certificates"))
    manual_exp_details = _normalize_experience_details(manual_payload.get("experience_details"))
    candidate_context = "\n".join([resume_text, manual_text]).strip()

    candidate_hard = _build_candidate_list(
        candidate_context,
        item_type="hard_skill",
        manual_items=manual_hard,
        common_items=COMMON_HARD_SKILLS,
        limit=120,
    )
    candidate_soft = _build_candidate_list(
        candidate_context,
        item_type="soft_skill",
        manual_items=manual_soft,
        common_items=COMMON_SOFT_SKILLS,
        limit=80,
    )
    candidate_certs = _build_candidate_list(
        candidate_context,
        item_type="certificate",
        manual_items=manual_certs,
        common_items=COMMON_CERTIFICATES,
        limit=80,
    )

    system = """你是大学生就业画像结构化助手。请根据“PDF/DOCX 文件解析文本 + 文件上下文 + 手动录入字段 + 候选关键词列表”抽取结果，并且只输出一个 JSON 对象，禁止输出解释文字。
重要背景：resume_text 是从一整份简历文件抽取出的连续文本，不是逐条记录。解析过程可能把 Word/PDF 中的同一段经历按换行拆散，也可能丢失版式、左右栏和上下文关系。抽取时必须先在语义上还原整份简历，再按同一公司/同一项目/同一奖项合并去重。
必须输出固定 JSON 结构：
{
  "hard_skills": [{"name": "Java", "evidence": "", "level": "项目实战"}],
  "soft_skills": [{"name": "沟通协作", "evidence": "", "strength": "strong"}],
  "certificates": [{"name": "CET-6", "evidence": ""}],
  "experience": {"internships": 0, "projects": 0, "awards": 0, "publications": 0, "open_source": 0, "leadership": 0},
    "experience_details": {"internships": ["同一段经历的一行总结"], "projects": ["同一项目的一行总结"], "awards": ["奖项名称"], "open_source": ["同一段经历的一行总结"], "leadership": ["同一段经历的一行总结"]},
    "experience_detail_items": {"internships": [{"content": "实习总结概括", "evidence": "具体做了什么实习"}], "projects": [{"content": "项目总结概括", "evidence": "项目具体解释"}], "awards": [{"content": "获得奖项", "evidence": ""}], "open_source": [{"content": "一行总结", "evidence": "具体贡献"}], "leadership": [{"content": "一行总结", "evidence": "具体职责"}]},
  "preferences": {"preferred_locations": [], "preferred_job_families": [], "target_salary_min": null, "target_salary_max": null, "notes": ""},
  "profile_notes": "",
  "mbti_type": null
}
规则：
1) 优先按“经历块”抽取，严禁臆造。“经历块”指同一公司/项目/时间段的完整经历。
2) 如果有手动录入，与简历冲突时以“证据更明确”的一方为准。
3) preferred_job_families 只能从 backend, frontend, ai, data, qa, ops, product, design 中选择。
4) experience 字段必须是非负整数，没有信息填 0。
5) hard_skills / soft_skills / certificates 中 name 不能为空，重复项去重。hard_skills.level 只能从：了解、熟悉、熟练、项目实战、可独立交付 中选择；依据技能栏、项目经历、实习经历、代码测评、面试表现判断，没有明确弱证据时默认“可独立交付”。
6) 候选关键词仅作提示，不是上限。文本中明确出现的核心技能（工具/框架/语言/平台/业务系统）要保留，但 hard_skills 最多 28 项，优先保留岗位主线和可证明技能，避免把每个插件/概念都单独展开。
7) 所有经历类字段都必须按“经历块”输出：同一公司/同一岗位/同一时间段算一段实习；同一项目名称/系统/课题算一个项目；同一奖项名称只算一次。禁止把同一经历按换行、职责、技术点、证明句拆成多条。
8) experience_detail_items 语义：internships.content=实习总结概括，internships.evidence=具体做了什么实习；projects.content=项目总结概括，projects.evidence=项目具体解释；awards.content=获得奖项，awards.evidence 必须为空字符串。
9) 去重要求：同一奖项即使在“荣誉奖项/项目描述/自我评价”中多次出现，也只能输出一次；同一实习或项目中多行职责要合并到同一个 evidence，不要拆多条。
10) experience 中各字段计数需与对应条目数一致（例如 internships 等于 experience_detail_items.internships 的条目数）。
11) mbti_type 仅允许 E/I/S/N/T/F/J/P 组合出的 16 型（如 INFP）；无明确证据则填 null。
12) profile_notes 必须输出 80-160 字中文总结，包含“优势技能 + 实习/项目亮点 + 建议方向”，禁止空字符串。
13) 输入中的 resume_document 为文件上下文；若 source=zhipu_file_api，表示文本来自官方文件解析，禁止把 markdown 图片占位符当成经历。
14) 控制输出体积：每条技能 evidence 不超过 40 字；每条实习/项目 evidence 不超过 180 字，只保留关键职责与量化成果；不要复述整段简历。"""
    payload = {
        "resume_document": {
            "filename": resume_filename or None,
            "file_type": resume_file_type or None,
            "source": resume_extract_source or None,
            "parser": "zhipu_files_parser_sync" if resume_extract_source == "zhipu_file_api" else "local_extract",
        },
        "resume_text": resume_text[:20000],
        "manual_input": {
            "name": manual_payload.get("name"),
            "mbti_type": normalize_mbti_type(manual_payload.get("mbti_type")),
            "hard_skills": manual_hard[:30],
            "soft_skills": manual_soft[:30],
            "certificates": manual_certs[:30],
            "experience": manual_payload.get("experience") or {},
            "experience_details": {k: v[:5] for k, v in manual_exp_details.items()},
            "experience_detail_items": {
                k: v[:5] for k, v in _normalize_experience_detail_items(manual_payload.get("experience_detail_items")).items()
            },
            "preferences": manual_payload.get("preferences") or {},
            "notes": str(manual_payload.get("notes") or "")[:500],
        },
        "candidate_lists": {
            "hard_skill_hints": candidate_hard[:100],
            "soft_skill_hints": candidate_soft[:60],
            "certificate_hints": candidate_certs[:60],
        },
    }
    if resume_file_path:
        # Direct-file profile extraction is intentionally disabled; use extracted
        # resume text for the LLM path, then fall back to local rules if needed.
        if not resume_text:
            try:
                fallback_text, fallback_source = extract_resume_text_smart(
                    resume_file_path,
                    filename=resume_filename or None,
                )
                fallback_text = normalize_text(fallback_text)
                if fallback_text:
                    resume_text = fallback_text
                    resume_extract_source = fallback_source or resume_extract_source
                    candidate_context = "\n".join([resume_text, manual_text]).strip()
                    candidate_hard = _build_candidate_list(
                        candidate_context,
                        item_type="hard_skill",
                        manual_items=manual_hard,
                        common_items=COMMON_HARD_SKILLS,
                        limit=120,
                    )
                    candidate_soft = _build_candidate_list(
                        candidate_context,
                        item_type="soft_skill",
                        manual_items=manual_soft,
                        common_items=COMMON_SOFT_SKILLS,
                        limit=80,
                    )
                    candidate_certs = _build_candidate_list(
                        candidate_context,
                        item_type="certificate",
                        manual_items=manual_certs,
                        common_items=COMMON_CERTIFICATES,
                        limit=80,
                    )
                    payload["resume_document"] = {
                        "filename": resume_filename or None,
                        "file_type": resume_file_type or None,
                        "source": resume_extract_source or None,
                        "parser": "zhipu_files_parser_sync" if resume_extract_source == "zhipu_file_api" else "local_extract",
                    }
                    payload["resume_text"] = resume_text[:20000]
                    payload["candidate_lists"] = {
                        "hard_skill_hints": candidate_hard[:100],
                        "soft_skill_hints": candidate_soft[:60],
                        "certificate_hints": candidate_certs[:60],
                    }
                    logger.info(
                        "简历画像使用文本链路 source=%s text_chars=%s",
                        resume_extract_source,
                        len(resume_text),
                    )
            except Exception as e:
                logger.warning("简历文本链路提取失败：%s", e)
    try:
        request_body = json.dumps(payload, ensure_ascii=False)
        if deepseek_json_enabled():
            data = deepseek_chat_json_sync(
                system,
                request_body,
                trace_context="student_profile.extract.primary.deepseek",
                max_tokens=3600,
                expected_root_keys=_PROFILE_SCHEMA_KEYS,
            )
        else:
            data = llm_client.chat_json_sync(
                system,
                request_body,
                trace_context="student_profile.extract.primary",
                max_tokens=2600,
                model_override=_RESUME_EXTRACT_MODEL,
            )
        normalized = _normalize_llm_profile_json(data) if isinstance(data, dict) else None
        if normalized and _looks_like_profile_json(normalized):
            return normalized
    except Exception:
        pass

    # Fallback prompt: plain text input (avoid model复述 large JSON payload).
    compact_system = """你是大学生就业画像结构化助手。只输出一个 JSON 对象，不得输出解释。
重要背景：输入简历文本来自整份 Word/PDF 文件抽取，不是逐条经历列表；换行可能只是版式换行，左右栏和上下文可能丢失。必须按语义合并同一公司、同一项目、同一奖项。
JSON 结构固定为：
{
  "hard_skills": [{"name": "", "evidence": "", "level": "了解"}],
  "soft_skills": [{"name": "", "evidence": "", "strength": "strong"}],
  "certificates": [{"name": "", "evidence": ""}],
  "experience": {"internships": 0, "projects": 0, "awards": 0, "publications": 0, "open_source": 0, "leadership": 0},
    "experience_details": {"internships": [], "projects": [], "awards": [], "open_source": [], "leadership": []},
    "experience_detail_items": {"internships": [{"content": "实习总结概括", "evidence": "具体做了什么实习"}], "projects": [{"content": "项目总结概括", "evidence": "项目具体解释"}], "awards": [{"content": "获得奖项", "evidence": ""}], "open_source": [{"content": "", "evidence": ""}], "leadership": [{"content": "", "evidence": ""}]},
  "preferences": {"preferred_locations": [], "preferred_job_families": [], "target_salary_min": null, "target_salary_max": null, "notes": ""},
  "profile_notes": "",
  "mbti_type": null
}
经历字段要求：按经历块输出，禁止将同一经历按换行、职责、技术点拆成多条；同一奖项多处出现只保留一次；获奖详情只写获得奖项，awards.evidence 为空；experience 计数必须与对应条目数一致。
其中 preferred_job_families 只能取 backend, frontend, ai, data, qa, ops, product, design。
mbti_type 只能是 16 型之一（如 ENTP），无证据填 null。
profile_notes 给出 80-160 字中文总结。"""
    compact_system += "\n输出体积要求：hard_skills 最多 28 项；每项 level 只能是 了解/熟悉/熟练/项目实战/可独立交付；技能 evidence 不超过 40 字；经历 evidence 不超过 180 字；不要复述整段简历。"
    compact_user = (
        "简历文件上下文：\n"
        + json.dumps(
            {
                "filename": resume_filename or None,
                "file_type": resume_file_type or None,
                "source": resume_extract_source or None,
            },
            ensure_ascii=False,
        )
        + "\n\n简历文本（来自 PDF/DOCX 解析）：\n"
        + (resume_text[:16000] if resume_text else "（无）")
        + "\n\n手动录入摘要：\n"
        + (manual_text[:4000] if manual_text else "（无）")
        + "\n\n候选硬技能（优先参考）："
        + "、".join(candidate_hard[:80])
        + "\n候选软技能（优先参考）："
        + "、".join(candidate_soft[:60])
        + "\n候选证书（优先参考）："
        + "、".join(candidate_certs[:60])
        + "\n说明：候选仅提示，不是抽取上限。"
    )
    try:
        if deepseek_json_enabled():
            data = deepseek_chat_json_sync(
                compact_system,
                compact_user,
                trace_context="student_profile.extract.fallback.deepseek",
                max_tokens=3200,
                expected_root_keys=_PROFILE_SCHEMA_KEYS,
            )
        else:
            data = llm_client.chat_json_sync(
                compact_system,
                compact_user,
                trace_context="student_profile.extract.fallback",
                max_tokens=2200,
                model_override=_RESUME_EXTRACT_MODEL,
            )
        normalized = _normalize_llm_profile_json(data) if isinstance(data, dict) else None
        if normalized and _looks_like_profile_json(normalized):
            return normalized
    except Exception:
        pass
    return None


def _manual_skill(
    name: str,
    *,
    evidence: str = "手动录入",
    source_section: str = "manual",
    level: str | None = None,
) -> StudentSkill:
    norm = normalize_to_item(name, "hard_skill", threshold=0.65)
    prof = proficiency_info(level, default=DEFAULT_STUDENT_LEVEL)
    return StudentSkill(
        skill_id=(norm or {}).get("item_id"),
        mention=(norm or {}).get("name_zh") or name,
        level=str(prof["level"]),
        proficiency=str(prof["level"]),
        proficiency_label=str(prof["label"]),
        proficiency_score=float(prof["score"]),
        proficiency_source=source_section,
        evidence=evidence,
        source_section=source_section,
        confidence=(norm or {}).get("confidence"),
        mapping_method=(norm or {}).get("mapping_method") or source_section,
    )


def _manual_soft_skill(
    name: str,
    *,
    evidence: str = "手动录入",
    source_section: str = "manual",
    strength: str = "strong",
) -> StudentSoftSkill:
    norm = normalize_to_item(name, "soft_skill", threshold=0.65)
    val = (strength or "").lower()
    if val not in {"strong", "weak"}:
        val = "weak"
    return StudentSoftSkill(
        soft_skill_id=(norm or {}).get("item_id"),
        name=(norm or {}).get("name_zh") or name,
        evidence=evidence,
        strength=val,
        source_section=source_section,
        confidence=(norm or {}).get("confidence"),
        mapping_method=(norm or {}).get("mapping_method") or source_section,
    )


def _manual_certificate(
    name: str,
    *,
    evidence: str = "手动录入",
    source_section: str = "manual",
) -> StudentCertificate:
    norm = normalize_to_item(name, "certificate", threshold=0.7)
    return StudentCertificate(
        certificate_id=(norm or {}).get("item_id"),
        name=(norm or {}).get("name_zh") or name,
        evidence=evidence,
        source_section=source_section,
        confidence=(norm or {}).get("confidence"),
        mapping_method=(norm or {}).get("mapping_method") or source_section,
    )


def _iter_structured_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    out: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            out.append(item)
        elif isinstance(item, str):
            out.append({"name": item})
    return out


def _profile_from_llm(student_id: str, llm_data: dict[str, Any] | None) -> StudentProfile | None:
    if not llm_data:
        return None

    hard_skills: list[StudentSkill] = []
    seen_hard: set[str] = set()
    for item in _iter_structured_items(llm_data.get("hard_skills")):
        name = str(item.get("name") or item.get("mention") or "").strip()
        if not name:
            continue
        key = name.lower()
        if key in seen_hard:
            continue
        seen_hard.add(key)
        hard_skills.append(
            _manual_skill(
                name,
                evidence=(str(item.get("evidence") or "").strip() or None),
                source_section="llm",
                level=str(item.get("proficiency") or item.get("level") or "").strip() or DEFAULT_STUDENT_LEVEL,
            )
        )

    soft_skills: list[StudentSoftSkill] = []
    seen_soft: set[str] = set()
    for item in _iter_structured_items(llm_data.get("soft_skills")):
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        key = name.lower()
        if key in seen_soft:
            continue
        seen_soft.add(key)
        soft_skills.append(
            _manual_soft_skill(
                name,
                evidence=(str(item.get("evidence") or "").strip() or None),
                source_section="llm",
                strength=str(item.get("strength") or "weak"),
            )
        )

    certs: list[StudentCertificate] = []
    seen_cert: set[str] = set()
    for item in _iter_structured_items(llm_data.get("certificates")):
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        key = name.lower()
        if key in seen_cert:
            continue
        seen_cert.add(key)
        certs.append(
            _manual_certificate(
                name,
                evidence=(str(item.get("evidence") or "").strip() or None),
                source_section="llm",
            )
        )

    exp = llm_data.get("experience") or {}
    pref = llm_data.get("preferences") or {}
    exp_details = _normalize_experience_details(llm_data.get("experience_details"))
    exp_detail_items = _normalize_experience_detail_items(llm_data.get("experience_detail_items"))
    if not exp_detail_items and exp_details:
        exp_detail_items = _evidence_map_to_detail_items(exp_details)
    if not exp_details and exp_detail_items:
        exp_details = _detail_items_to_evidence_map(exp_detail_items)
    mbti_type = normalize_mbti_type(llm_data.get("mbti_type")) or _extract_mbti_type_from_text(
        f"{llm_data.get('profile_notes') or ''}\n{pref.get('notes') or ''}"
    )

    pref_families: list[str] = []
    for raw in _safe_list(pref.get("preferred_job_families")):
        norm = _normalize_job_family(raw)
        if norm and norm not in pref_families:
            pref_families.append(norm)

    profile = StudentProfile(
        student_id=student_id,
        mbti_type=mbti_type,
        mbti_source="llm" if mbti_type else None,
        hard_skills=hard_skills,
        soft_skills=soft_skills,
        certificates=certs,
        experience=StudentExperience(
            internships=_coerce_llm_experience_count("internships", exp.get("internships"), exp_detail_items.get("internships")),
            projects=_coerce_llm_experience_count("projects", exp.get("projects"), exp_detail_items.get("projects")),
            awards=_coerce_llm_experience_count("awards", exp.get("awards"), exp_detail_items.get("awards")),
            publications=_coerce_llm_experience_count("publications", exp.get("publications"), exp_detail_items.get("publications")),
            open_source=_coerce_llm_experience_count("open_source", exp.get("open_source"), exp_detail_items.get("open_source")),
            leadership=_coerce_llm_experience_count("leadership", exp.get("leadership"), exp_detail_items.get("leadership")),
        ),
        preferences=StudentPreferences(
            preferred_locations=_safe_list(pref.get("preferred_locations")),
            preferred_job_families=pref_families,
            target_salary_min=(
                _to_non_negative_int(pref.get("target_salary_min")) if pref.get("target_salary_min") is not None else None
            ),
            target_salary_max=(
                _to_non_negative_int(pref.get("target_salary_max")) if pref.get("target_salary_max") is not None else None
            ),
            notes=str(pref.get("notes") or llm_data.get("profile_notes") or "").strip() or None,
        ),
        profile_notes=str(llm_data.get("profile_notes") or "").strip() or None,
        extraction_meta={
            "experience_counter_source": "llm",
            "llm_profile_used": True,
            "mbti_source": "llm" if mbti_type else None,
            "experience_field_sources": {
                "internships": "llm",
                "projects": "llm",
                "awards": "llm",
                "publications": "llm",
                "open_source": "llm",
                "leadership": "llm",
            },
            "experience_evidence": exp_details,
            "experience_detail_items": exp_detail_items,
        },
    )
    return profile


def _merge_profiles(primary: StudentProfile, secondary: StudentProfile) -> StudentProfile:
    hard_map: dict[str, StudentSkill] = {}
    for item in primary.hard_skills:
        hard_map[(item.mention or "").lower()] = item
    for item in secondary.hard_skills:
        key = (item.mention or "").lower()
        if key and key not in hard_map:
            hard_map[key] = item

    soft_map: dict[str, StudentSoftSkill] = {}
    for item in primary.soft_skills:
        soft_map[(item.name or "").lower()] = item
    for item in secondary.soft_skills:
        key = (item.name or "").lower()
        if key and key not in soft_map:
            soft_map[key] = item

    cert_map: dict[str, StudentCertificate] = {}
    for item in primary.certificates:
        cert_map[(item.name or "").lower()] = item
    for item in secondary.certificates:
        key = (item.name or "").lower()
        if key and key not in cert_map:
            cert_map[key] = item

    fams: list[str] = []
    for raw in list(primary.preferences.preferred_job_families or []) + list(secondary.preferences.preferred_job_families or []):
        norm = _normalize_job_family(raw)
        if norm and norm not in fams:
            fams.append(norm)

    primary_source = str((primary.extraction_meta or {}).get("experience_counter_source") or "primary")
    secondary_source = str((secondary.extraction_meta or {}).get("experience_counter_source") or "secondary")
    primary_has_llm_details = bool(
        isinstance(primary.extraction_meta, dict)
        and (
            primary.extraction_meta.get("llm_profile_used")
            or _normalize_experience_detail_items(primary.extraction_meta.get("experience_detail_items"))
        )
    )

    exp_field_sources: dict[str, str] = {}

    def _pick_exp(field: str) -> int:
        p = _to_non_negative_int(getattr(primary.experience, field, 0))
        s = _to_non_negative_int(getattr(secondary.experience, field, 0))
        if primary_has_llm_details and p > 0:
            exp_field_sources[field] = primary_source
            return p
        if p > 0 and s > 0:
            low, high = (p, s) if p <= s else (s, p)
            if high >= (low * 2):
                if p <= s:
                    exp_field_sources[field] = primary_source
                    return p
                exp_field_sources[field] = secondary_source
                return s
        if p >= s:
            exp_field_sources[field] = primary_source
            return p
        exp_field_sources[field] = secondary_source
        return s

    merged_meta: dict[str, Any] = {}
    if isinstance(secondary.extraction_meta, dict):
        merged_meta.update(secondary.extraction_meta)
    if isinstance(primary.extraction_meta, dict):
        merged_meta.update(primary.extraction_meta)
    merged_meta["experience_field_sources"] = exp_field_sources
    merged_meta["experience_counter_source"] = primary_source if primary_source == secondary_source else "mixed"

    merged_evidence: dict[str, list[str]] = {}
    fields = _EXPERIENCE_DETAIL_FIELDS
    primary_ev = (
        primary.extraction_meta.get("experience_evidence")
        if isinstance(primary.extraction_meta, dict) and isinstance(primary.extraction_meta.get("experience_evidence"), dict)
        else {}
    )
    secondary_ev = (
        secondary.extraction_meta.get("experience_evidence")
        if isinstance(secondary.extraction_meta, dict) and isinstance(secondary.extraction_meta.get("experience_evidence"), dict)
        else {}
    )
    for field in fields:
        if primary_has_llm_details and list(primary_ev.get(field) or []):
            lines = _dedupe_keep_order([str(x or "").strip() for x in list(primary_ev.get(field) or []) if str(x or "").strip()])
        else:
            lines = _dedupe_keep_order(
                [str(x or "").strip() for x in list(primary_ev.get(field) or []) + list(secondary_ev.get(field) or []) if str(x or "").strip()]
            )
        if lines:
            merged_evidence[field] = lines[:8]

    primary_items = (
        _normalize_experience_detail_items(primary.extraction_meta.get("experience_detail_items"))
        if isinstance(primary.extraction_meta, dict)
        else {}
    )
    secondary_items = (
        _normalize_experience_detail_items(secondary.extraction_meta.get("experience_detail_items"))
        if isinstance(secondary.extraction_meta, dict)
        else {}
    )
    merged_detail_items: dict[str, list[dict[str, str]]] = {}
    for field in fields:
        combined = list(primary_items.get(field) or []) if (primary_has_llm_details and list(primary_items.get(field) or [])) else (list(primary_items.get(field) or []) + list(secondary_items.get(field) or []))
        out: list[dict[str, str]] = []
        seen: set[str] = set()
        for row in combined:
            content = str((row or {}).get("content") or "").strip()
            evidence = str((row or {}).get("evidence") or "").strip()
            if not content and not evidence:
                continue
            if not content:
                content = _summarize_experience_content(evidence)
            if not evidence:
                evidence = content
            key = _experience_item_signature(field, content, evidence)
            if key in seen:
                continue
            seen.add(key)
            out.append({"content": content[:180], "evidence": evidence[:300]})
            if len(out) >= 8:
                break
        if out:
            merged_detail_items[field] = out

    if not merged_detail_items and merged_evidence:
        merged_detail_items = _evidence_map_to_detail_items(merged_evidence)
    if not merged_evidence and merged_detail_items:
        merged_evidence = _detail_items_to_evidence_map(merged_detail_items)

    if merged_evidence:
        merged_meta["experience_evidence"] = merged_evidence
    if merged_detail_items:
        merged_meta["experience_detail_items"] = merged_detail_items

    return StudentProfile(
        student_id=primary.student_id,
        mbti_type=primary.mbti_type or secondary.mbti_type,
        mbti_source=primary.mbti_source or secondary.mbti_source,
        hard_skills=list(hard_map.values()),
        soft_skills=list(soft_map.values()),
        certificates=list(cert_map.values()),
        experience=StudentExperience(
            internships=_pick_exp("internships"),
            projects=_pick_exp("projects"),
            awards=_pick_exp("awards"),
            publications=_pick_exp("publications"),
            open_source=_pick_exp("open_source"),
            leadership=_pick_exp("leadership"),
        ),
        preferences=StudentPreferences(
            preferred_locations=_dedupe_keep_order(
                list(primary.preferences.preferred_locations or []) + list(secondary.preferences.preferred_locations or [])
            ),
            preferred_job_families=fams,
            target_salary_min=primary.preferences.target_salary_min
            if primary.preferences.target_salary_min is not None
            else secondary.preferences.target_salary_min,
            target_salary_max=primary.preferences.target_salary_max
            if primary.preferences.target_salary_max is not None
            else secondary.preferences.target_salary_max,
            notes=primary.preferences.notes or secondary.preferences.notes,
        ),
        profile_notes=primary.profile_notes or secondary.profile_notes,
        extraction_meta=merged_meta,
    )


def _build_profile_from_rules(student_id: str, text: str) -> StudentProfile:
    text = normalize_text(text)
    sections = split_resume(text)

    body_text = sections.get("body", "") or text
    skills_text = sections.get("skills", "") or text
    proj_text = sections.get("project", "")
    intern_text = sections.get("internship", "")
    awards_text = sections.get("awards", "")
    cert_text = sections.get("certificates", "")
    self_eval_text = sections.get("self_eval", "")

    hard = extract_dictionary_mentions(
        f"{skills_text}\n{proj_text}\n{intern_text}\n{body_text}",
        "hard_skill",
        section="skills",
    )
    cert = extract_dictionary_mentions(
        f"{cert_text}\n{awards_text}\n{body_text}",
        "certificate",
        section="certificates",
    )
    soft = extract_dictionary_mentions(
        f"{self_eval_text}\n{proj_text}\n{intern_text}\n{body_text}",
        "soft_skill",
        section="self_eval",
    )

    hard_skills: list[StudentSkill] = []
    for it in hard:
        norm = normalize_to_item(it["name_zh"], "hard_skill", threshold=0.70)
        hard_skills.append(
            StudentSkill(
                skill_id=(norm or {}).get("item_id"),
                mention=it["name_zh"],
                evidence=it.get("evidence"),
                source_section=it.get("section"),
                confidence=(norm or {}).get("confidence"),
                mapping_method=(norm or {}).get("mapping_method"),
            )
        )

    certs: list[StudentCertificate] = []
    for it in cert:
        norm = normalize_to_item(it["name_zh"], "certificate", threshold=0.80)
        certs.append(
            StudentCertificate(
                certificate_id=(norm or {}).get("item_id"),
                name=it["name_zh"],
                evidence=it.get("evidence"),
                source_section=it.get("section"),
                confidence=(norm or {}).get("confidence"),
                mapping_method=(norm or {}).get("mapping_method"),
            )
        )

    soft_skills: list[StudentSoftSkill] = []
    for it in soft:
        norm = normalize_to_item(it["name_zh"], "soft_skill", threshold=0.72)
        soft_skills.append(
            StudentSoftSkill(
                soft_skill_id=(norm or {}).get("item_id"),
                name=it["name_zh"],
                evidence=it.get("evidence"),
                strength="weak",
                source_section=it.get("section"),
                confidence=(norm or {}).get("confidence"),
                mapping_method=(norm or {}).get("mapping_method"),
            )
        )

    if len(hard_skills) < 8:
        existing_hard = {normalize_token(item.mention) for item in hard_skills if item.mention}
        for name in _extract_from_common_list(text, COMMON_HARD_SKILLS):
            key = normalize_token(name)
            if not key or key in existing_hard:
                continue
            hard_skills.append(_manual_skill(name))
            existing_hard.add(key)
            if len(hard_skills) >= 10:
                break
    if len(soft_skills) < 5:
        existing_soft = {normalize_token(item.name) for item in soft_skills if item.name}
        for name in _extract_from_common_list(text, COMMON_SOFT_SKILLS):
            key = normalize_token(name)
            if not key or key in existing_soft:
                continue
            soft_skills.append(_manual_soft_skill(name))
            existing_soft.add(key)
            if len(soft_skills) >= 6:
                break
    if len(certs) < 4:
        existing_certs = {normalize_token(item.name) for item in certs if item.name}
        for name in _extract_from_common_list(text, COMMON_CERTIFICATES):
            key = normalize_token(name)
            if not key or key in existing_certs:
                continue
            certs.append(_manual_certificate(name))
            existing_certs.add(key)
            if len(certs) >= 5:
                break

    exp, exp_detail = _estimate_experience_signals(
        full_text=text,
        intern_text=intern_text,
        proj_text=proj_text,
        awards_text=awards_text,
    )
    exp_evidence_map = (
        exp_detail.get("experience_evidence")
        if isinstance(exp_detail, dict) and isinstance(exp_detail.get("experience_evidence"), dict)
        else {}
    )
    if exp_evidence_map:
        exp_detail = dict(exp_detail)
        exp_detail["experience_detail_items"] = _evidence_map_to_detail_items(exp_evidence_map)

    pref = _extract_preference_hints(text)
    mbti_type = _extract_mbti_type_from_text(text)
    if mbti_type:
        exp_detail = dict(exp_detail)
        exp_detail["mbti_source"] = "rule_text"
    notes = ""
    return StudentProfile(
        student_id=student_id,
        mbti_type=mbti_type,
        mbti_source="rule_text" if mbti_type else None,
        hard_skills=hard_skills,
        soft_skills=soft_skills,
        certificates=certs,
        experience=exp,
        preferences=pref,
        profile_notes=notes,
        extraction_meta=exp_detail,
    )


def _build_profile_from_manual(student_id: str, payload: dict[str, Any]) -> StudentProfile:
    preferences_in = payload.get("preferences") or {}
    exp_in = payload.get("experience") or {}
    mbti_type = normalize_mbti_type(payload.get("mbti_type")) or _extract_mbti_type_from_text(
        f"{payload.get('raw_text') or ''}\n{preferences_in.get('notes') or ''}"
    )
    fams: list[str] = []
    for raw in _safe_list(preferences_in.get("preferred_job_families")):
        norm = _normalize_job_family(raw)
        if norm and norm not in fams:
            fams.append(norm)
    experience_details = _normalize_experience_details(payload.get("experience_details"))
    experience_detail_items = _normalize_experience_detail_items(payload.get("experience_detail_items"))
    if not experience_detail_items and experience_details:
        experience_detail_items = _evidence_map_to_detail_items(experience_details)
    if not experience_details and experience_detail_items:
        experience_details = _detail_items_to_evidence_map(experience_detail_items)
    manual_hard_skills = []
    for item in _iter_structured_items(payload.get("hard_skills")):
        name = str(item.get("name") or item.get("mention") or item.get("skill") or "").strip()
        if not name:
            continue
        manual_hard_skills.append(
            _manual_skill(
                name,
                evidence=str(item.get("evidence") or "手动录入"),
                source_section="manual",
                level=str(item.get("proficiency") or item.get("level") or "").strip() or DEFAULT_STUDENT_LEVEL,
            )
        )

    return StudentProfile(
        student_id=student_id,
        mbti_type=mbti_type,
        mbti_source="manual" if mbti_type else None,
        hard_skills=manual_hard_skills or [_manual_skill(x, level=DEFAULT_STUDENT_LEVEL) for x in _safe_list(payload.get("hard_skills"))],
        soft_skills=[_manual_soft_skill(x) for x in _safe_list(payload.get("soft_skills"))],
        certificates=[_manual_certificate(x) for x in _safe_list(payload.get("certificates"))],
        experience=StudentExperience(
            internships=_experience_count_with_items(exp_in.get("internships"), experience_detail_items.get("internships")),
            projects=_experience_count_with_items(exp_in.get("projects"), experience_detail_items.get("projects")),
            awards=_experience_count_with_items(exp_in.get("awards"), experience_detail_items.get("awards")),
            publications=_experience_count_with_items(exp_in.get("publications"), experience_detail_items.get("publications")),
            open_source=_experience_count_with_items(exp_in.get("open_source"), experience_detail_items.get("open_source")),
            leadership=_experience_count_with_items(exp_in.get("leadership"), experience_detail_items.get("leadership")),
        ),
        preferences=StudentPreferences(
            preferred_locations=_safe_list(preferences_in.get("preferred_locations")),
            preferred_job_families=fams,
            target_salary_min=(
                _to_non_negative_int(preferences_in.get("target_salary_min"))
                if preferences_in.get("target_salary_min") is not None
                else None
            ),
            target_salary_max=(
                _to_non_negative_int(preferences_in.get("target_salary_max"))
                if preferences_in.get("target_salary_max") is not None
                else None
            ),
            notes=str(preferences_in.get("notes") or "").strip() or None,
        ),
        profile_notes=str(preferences_in.get("notes") or "").strip() or None,
        extraction_meta={
            "experience_counter_source": "manual",
            "llm_profile_used": False,
            "mbti_source": "manual" if mbti_type else None,
            "experience_field_sources": {
                "internships": "manual",
                "projects": "manual",
                "awards": "manual",
                "publications": "manual",
                "open_source": "manual",
                "leadership": "manual",
            },
            "experience_evidence": experience_details,
            "experience_detail_items": experience_detail_items,
        },
    )


def _apply_manual_overrides(profile: StudentProfile, payload: dict[str, Any] | None) -> StudentProfile:
    payload = payload or {}
    manual_mbti = normalize_mbti_type(payload.get("mbti_type"))
    if manual_mbti:
        profile.mbti_type = manual_mbti
        profile.mbti_source = "manual"
        meta = profile.extraction_meta if isinstance(profile.extraction_meta, dict) else {}
        meta["mbti_source"] = "manual"
        profile.extraction_meta = meta

    exp_in = payload.get("experience") or {}
    if isinstance(exp_in, dict):
        for field in ("internships", "projects", "awards", "publications", "open_source", "leadership"):
            if field in exp_in and exp_in.get(field) is not None:
                setattr(profile.experience, field, _to_non_negative_int(exp_in.get(field)))
                meta = profile.extraction_meta if isinstance(profile.extraction_meta, dict) else {}
                field_sources = dict(meta.get("experience_field_sources") or {})
                field_sources[field] = "manual"
                meta["experience_field_sources"] = field_sources
                meta["experience_counter_source"] = "manual"
                profile.extraction_meta = meta

    manual_details = _normalize_experience_details((payload or {}).get("experience_details"))
    manual_detail_items = _normalize_experience_detail_items((payload or {}).get("experience_detail_items"))
    if manual_detail_items and not manual_details:
        manual_details = _detail_items_to_evidence_map(manual_detail_items)
    if manual_details and not manual_detail_items:
        manual_detail_items = _evidence_map_to_detail_items(manual_details)
    if manual_details or manual_detail_items:
        meta = profile.extraction_meta if isinstance(profile.extraction_meta, dict) else {}
        ev_map = dict(meta.get("experience_evidence") or {})
        items_map = _normalize_experience_detail_items(meta.get("experience_detail_items"))
        field_sources = dict(meta.get("experience_field_sources") or {})
        for field, lines in manual_details.items():
            if lines:
                ev_map[field] = lines
                field_sources[field] = "manual"
        for field, rows in manual_detail_items.items():
            if rows:
                items_map[field] = rows
                field_sources[field] = "manual"
        meta["experience_evidence"] = ev_map
        if items_map:
            meta["experience_detail_items"] = items_map
        meta["experience_field_sources"] = field_sources
        meta["experience_counter_source"] = "manual"
        profile.extraction_meta = meta
        for field in _EXPERIENCE_DETAIL_FIELDS:
            if not hasattr(profile.experience, field):
                continue
            item_count = len(items_map.get(field) or [])
            if item_count > _to_non_negative_int(getattr(profile.experience, field, 0)):
                setattr(profile.experience, field, item_count)
                field_sources[field] = "manual"
        meta["experience_field_sources"] = field_sources
        profile.extraction_meta = meta

    preferences_in = payload.get("preferences") or {}
    if isinstance(preferences_in, dict):
        if preferences_in.get("target_salary_min") is not None:
            profile.preferences.target_salary_min = _to_non_negative_int(preferences_in.get("target_salary_min"))
        if preferences_in.get("target_salary_max") is not None:
            profile.preferences.target_salary_max = _to_non_negative_int(preferences_in.get("target_salary_max"))
        notes = str(preferences_in.get("notes") or "").strip()
        if notes:
            profile.preferences.notes = notes
            profile.profile_notes = notes
    manual_hard = []
    for item in _iter_structured_items((payload or {}).get("hard_skills")):
        name = str(item.get("name") or item.get("mention") or item.get("skill") or "").strip()
        if not name:
            continue
        manual_hard.append(
            _manual_skill(
                name,
                evidence=str(item.get("evidence") or "手动录入"),
                source_section="manual",
                level=str(item.get("proficiency") or item.get("level") or "").strip() or DEFAULT_STUDENT_LEVEL,
            )
        )
    if manual_hard:
        profile.hard_skills = manual_hard
    return profile


def _normalize_profile_skill_proficiency(profile: StudentProfile, *, resume_text: str = "") -> StudentProfile:
    normalized: list[StudentSkill] = []
    for skill in profile.hard_skills or []:
        data = skill.model_dump()
        prof = infer_student_proficiency_from_evidence(str(skill.mention or ""), data, resume_text)
        data["level"] = prof["level"]
        data["proficiency"] = prof["level"]
        data["proficiency_label"] = prof["label"]
        data["proficiency_score"] = prof["score"]
        data["proficiency_source"] = data.get("proficiency_source") or prof.get("source") or data.get("source_section") or "profile"
        normalized.append(StudentSkill(**data))
    profile.hard_skills = normalized
    return profile


def build_student_profile_from_manual(student_id: str, payload: dict[str, Any]) -> StudentProfile:
    raw_text = normalize_text(payload.get("raw_text") or "")
    if not raw_text:
        raw_text = _manual_payload_to_text(payload)

    ai_first_profile = generate_student_profile_from_text(
        student_id=student_id,
        text=raw_text,
        persist=False,
        manual_payload=payload,
    )
    manual_profile = _build_profile_from_manual(student_id, payload)
    profile = _merge_profiles(ai_first_profile, manual_profile)
    profile = _apply_manual_overrides(profile, payload)
    profile = _normalize_profile_skill_proficiency(profile, resume_text=raw_text)
    profile.completeness_score = _compute_completeness(profile, raw_text)
    profile.competitiveness_score = _compute_competitiveness(profile)

    db.upsert_student_profile(student_id, profile_json=json.dumps(profile.model_dump(), ensure_ascii=False), updated_at=now_iso())
    return profile


def generate_student_profile_from_latest_resume(
    student_id: str,
    *,
    require_llm: bool = False,
    manual_payload: dict[str, Any] | None = None,
) -> StudentProfile:
    files = db.list_student_files(student_id)
    if not files:
        raise ValueError("No resume file uploaded for this student")
    latest = files[0]
    path = latest["path"]
    ext = str(path).rsplit(".", 1)[-1].lower() if "." in str(path) else ""
    if ext not in {"pdf", "docx", "doc", "txt"}:
        raise ValueError("Unsupported resume format, only pdf/docx are allowed")
    merged_manual_payload = dict(manual_payload or {})
    if path and not merged_manual_payload.get("resume_file_path"):
        merged_manual_payload["resume_file_path"] = path
    if latest.get("filename") and not merged_manual_payload.get("resume_filename"):
        merged_manual_payload["resume_filename"] = latest.get("filename")
    if ext and not merged_manual_payload.get("resume_file_type"):
        merged_manual_payload["resume_file_type"] = str(ext).upper()
    text, text_source = extract_resume_text_smart(path, filename=str(latest.get("filename") or ""))
    if not normalize_text(text):
        raise ValueError("Resume text extraction failed")
    merged_manual_payload["resume_extract_source"] = text_source
    return generate_student_profile_from_text(
        student_id=student_id,
        text=text,
        manual_payload=merged_manual_payload,
        require_llm=require_llm,
    )


def generate_student_profile_from_text(
    student_id: str,
    text: str,
    persist: bool = True,
    manual_payload: dict[str, Any] | None = None,
    require_llm: bool = False,
) -> StudentProfile:
    text = normalize_text(text)
    manual_payload = manual_payload or {}
    manual_text = _manual_payload_to_text(manual_payload)
    ai_context_text = text or manual_text

    rule_profile = _build_profile_from_rules(student_id, ai_context_text)
    # Keep raw resume text for LLM extraction so direct-file fallback can correctly
    # detect empty resume text and trigger extract_resume_text_smart from file.
    llm_profile = _profile_from_llm(student_id, _llm_extract_student_profile(text, manual_payload=manual_payload))
    if require_llm and not llm_profile:
        raise ValueError("llm_profile_extract_failed_or_disabled")

    profile = _merge_profiles(llm_profile, rule_profile) if llm_profile else rule_profile
    manual_profile = _build_profile_from_manual(student_id, manual_payload) if manual_payload else None
    if manual_profile:
        profile = _merge_profiles(profile, manual_profile)
        profile = _apply_manual_overrides(profile, manual_payload)

    note_text = str(profile.profile_notes or "").strip()
    if (not note_text) or _RULE_PLACEHOLDER_RE.search(note_text):
        synthesized = _synthesize_profile_notes(profile)
        profile.profile_notes = synthesized
        if not str(profile.preferences.notes or "").strip():
            profile.preferences.notes = synthesized

    score_text = text or manual_text
    profile.completeness_score = _compute_completeness(profile, score_text)
    profile.competitiveness_score = _compute_competitiveness(profile)
    meta = dict(profile.extraction_meta or {})
    meta["llm_enabled"] = bool(llm_client.is_enabled())
    meta["llm_profile_used"] = bool(llm_profile)
    meta["manual_input_used"] = bool(manual_payload)
    profile.extraction_meta = meta

    if persist:
        profile = _normalize_profile_skill_proficiency(profile, resume_text=score_text)
        db.upsert_student_profile(student_id, profile_json=json.dumps(profile.model_dump(), ensure_ascii=False), updated_at=now_iso())
    return profile
