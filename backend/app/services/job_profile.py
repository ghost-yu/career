from __future__ import annotations

import json
import re
from typing import Any

from app.db import sqlite as db
from app.schemas.job import BasicRequirements, CertificateMention, JobProfile, SkillMention, SoftSkillMention
from app.services.mention_extractor import extract_dictionary_mentions
from app.services.llm import llm_client
from app.services.skill_proficiency import DEFAULT_JOB_LEVEL, infer_required_proficiency_from_text, proficiency_info
from app.services.normalization import normalize_to_item
from app.services.sectioning import split_jd
from app.utils.text import normalize_text
from app.utils.ids import now_iso


_EDU_PATTERNS = [
    (re.compile(r"博士"), "博士"),
    (re.compile(r"硕士|研究生"), "硕士"),
    (re.compile(r"本科"), "本科"),
    (re.compile(r"大专|专科"), "大专"),
]

_EXP_RE = re.compile(r"(\d+)\s*年")

_SALES_TITLE_HINTS = [
    "销售",
    "商务拓展",
    "业务拓展",
    "bd",
    "客户经理",
    "渠道经理",
    "大客户",
    "销售顾问",
    "销售代表",
    "account manager",
    "sales",
]

_SALES_FALLBACK_HARD_SKILL_PATTERNS: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r"\bcrm\b|客户关系管理|salesforce", re.I), "CRM", "must_low"),
    (re.compile(r"\bexcel\b|office|wps|数据透视表|vlookup|xlookup", re.I), "Excel", "must_low"),
    (re.compile(r"\bpower\s*bi\b|tableau|\bsql\b", re.I), "数据分析", "must_low"),
    (re.compile(r"招投标|标书|投标|招标", re.I), "招投标管理", "must_low"),
    (re.compile(r"报价|成本核算|报价单|毛利", re.I), "报价与成本核算", "must_low"),
    (re.compile(r"渠道管理|经销商|代理商|渠道拓展", re.I), "渠道管理", "must_low"),
    (re.compile(r"客户开发|客户维护|客户拜访|客户管理", re.I), "客户管理", "must_low"),
    (re.compile(r"售前方案|方案设计|解决方案|技术方案", re.I), "解决方案设计", "must_low"),
    (re.compile(r"\bsap\b|\berp\b", re.I), "ERP/SAP", "must_low"),
    (re.compile(r"\bcad\b|autocad", re.I), "CAD", "plus"),
    (re.compile(r"英语|英文", re.I), "商务英语", "plus"),
    (re.compile(r"配电|低压|高压|电气|自动化|plc", re.I), "电气产品知识", "must_low"),
]


def infer_job_family(title: str) -> str:
    t = (title or "").lower()
    if any(k in t for k in _SALES_TITLE_HINTS):
        return "sales"
    if any(k in t for k in ["实施", "交付", "部署", "驻场"]):
        return "implementation"
    if any(k in t for k in ["技术支持", "售前", "售后", "客户支持"]):
        return "support"
    if any(k in t for k in ["安全", "攻防", "渗透", "漏洞"]):
        return "security"
    if any(k in t for k in ["嵌入式", "单片机", "arm", "驱动", "固件"]):
        return "embedded"
    if any(k in t for k in ["android", "ios", "flutter", "移动开发", "鸿蒙"]):
        return "mobile"
    if any(k in t for k in ["前端", "frontend", "react", "vue"]):
        return "frontend"
    if any(k in t for k in ["后端", "backend", "java", "python", "golang", "go", "c++", "spring", "node"]):
        return "backend"
    if any(k in t for k in ["算法", "机器学习", "深度学习", "ai", "aigc", "nlp", "cv"]):
        return "ai"
    if any(k in t for k in ["研究员", "科研", "实验室", "博士后", "research"]):
        return "research"
    if any(k in t for k in ["数据", "data", "bi", "数仓", "大数据"]):
        return "data"
    if any(k in t for k in ["测试", "qa", "质量", "自动化测试"]):
        return "qa"
    if any(k in t for k in ["产品", "pm", "product"]):
        return "product"
    if any(k in t for k in ["运维", "devops", "sre", "云平台"]):
        return "ops"
    if any(k in t for k in ["ui", "ux", "视觉", "交互", "设计"]):
        return "design"
    return "general"

def _normalize_family(raw: str | None, fallback: str) -> str:
    val = str(raw or "").strip().lower()
    if not val:
        return fallback
    canonical = {
        "backend",
        "frontend",
        "ai",
        "data",
        "qa",
        "ops",
        "product",
        "design",
        "implementation",
        "support",
        "security",
        "embedded",
        "mobile",
        "research",
        "sales",
        "general",
    }
    if val in canonical:
        return val
    mapping = {
        "后端": "backend",
        "后端开发": "backend",
        "java": "backend",
        "服务端": "backend",
        "前端": "frontend",
        "前端开发": "frontend",
        "人工智能": "ai",
        "算法": "ai",
        "机器学习": "ai",
        "深度学习": "ai",
        "aigc": "ai",
        "数据": "data",
        "数据开发": "data",
        "数据分析": "data",
        "数仓": "data",
        "测试": "qa",
        "质量": "qa",
        "测试开发": "qa",
        "运维": "ops",
        "云平台": "ops",
        "devops": "ops",
        "sre": "ops",
        "产品": "product",
        "产品经理": "product",
        "设计": "design",
        "ui": "design",
        "ux": "design",
        "实施": "implementation",
        "交付": "implementation",
        "技术支持": "support",
        "售前": "support",
        "售后": "support",
        "安全": "security",
        "嵌入式": "embedded",
        "移动开发": "mobile",
        "科研": "research",
        "研究": "research",
        "销售": "sales",
        "商务": "sales",
        "商务拓展": "sales",
        "客户经理": "sales",
        "渠道销售": "sales",
        "bd": "sales",
    }
    return mapping.get(val, fallback)


def _is_sales_like(title: str, text: str) -> bool:
    src = f"{title}\n{text}".lower()
    return any(k in src for k in _SALES_TITLE_HINTS)


def _fallback_sales_hard_skills(
    *,
    title: str,
    family: str,
    req_text: str,
    plus_text: str,
    resp_text: str,
    desc: str,
    existing_mentions: set[str],
) -> list[SkillMention]:
    text = "\n".join([title, req_text, plus_text, resp_text, desc])
    sales_like = family == "sales" or _is_sales_like(title, text)
    support_like = family in {"support", "implementation"} and any(
        kw in text for kw in ["客户", "售前", "售后", "方案", "现场", "项目交付"]
    )
    if not sales_like and not support_like:
        return []

    out: list[SkillMention] = []
    for pat, mention, importance in _SALES_FALLBACK_HARD_SKILL_PATTERNS:
        if not pat.search(text):
            continue
        key = mention.strip().lower()
        if not key or key in existing_mentions:
            continue
        norm = normalize_to_item(mention, "hard_skill", threshold=0.55)
        out.append(
            SkillMention(
                skill_id=(norm or {}).get("item_id"),
                mention=(norm or {}).get("name_zh") or mention,
                importance=importance,
                evidence="规则兜底抽取",
                source_section="fallback_rule",
                confidence=(norm or {}).get("confidence"),
                mapping_method=(norm or {}).get("mapping_method") or "rule_keyword",
            )
        )
        existing_mentions.add(key)
        if len(out) >= 10:
            break

    return out


def _llm_extract_job_hints(title: str, description: str) -> dict[str, Any] | None:
    if not llm_client.is_enabled() or not (title or description):
        return None
    system = """你是岗位画像结构化助手。请根据职位名称与岗位详情抽取岗位画像提示信息，并严格只输出一个 JSON 对象。
要求：
1. 只抽取文本中有依据的信息。
2. job_family 只能从 backend, frontend, ai, data, qa, ops, product, design, implementation, support, security, embedded, mobile, research, sales, general 中选择。
3. hard_skills 输出对象数组，每项包含 name 和 level；level 只能是 了解/熟悉/熟练/项目实战/可独立交付。soft_skills / certificates 只输出名称数组。
4. education 只输出：博士/硕士/本科/大专 之一或 null。
5. experience_years_min 输出整数或 null。
JSON 结构：
{
  "job_family": "backend",
  "hard_skills": [{"name": "Java", "level": "项目实战"}, {"name": "Spring Boot", "level": "熟练"}],
  "soft_skills": ["沟通能力", "学习能力"],
  "certificates": ["软考中级"],
  "education": "本科",
  "experience_years_min": 1,
  "tags": ["应届友好", "出差"]
}
"""
    user = f"职位名称：{title}\n岗位详情：{description[:16000]}"
    try:
        data = llm_client.chat_json_sync(system, user, trace_context="job_profile.extract_hints")
        if isinstance(data, dict):
            return data
    except Exception:
        return None
    return None


def _dedupe_tags(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        raw = str(value or "").strip()
        if not raw:
            continue
        key = raw.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(raw)
    return out[:12]


def _extract_education(text: str) -> str | None:
    for pat, label in _EDU_PATTERNS:
        if pat.search(text):
            return label
    return None


def _extract_experience_years_min(text: str) -> int | None:
    m = _EXP_RE.search(text)
    if not m:
        return None
    try:
        n = int(m.group(1))
        return max(0, n)
    except Exception:
        return None


def generate_job_profile(job_id: str) -> JobProfile:
    job = db.get_job(job_id)
    if not job:
        raise ValueError(f"Job not found: {job_id}")

    desc = normalize_text(job.get("description") or "")
    sections = split_jd(desc)

    req_text = sections.get("requirements", "")
    plus_text = sections.get("plus", "")
    resp_text = sections.get("responsibilities", "")

    hard_req = extract_dictionary_mentions(req_text, "hard_skill", section="requirements")
    hard_plus = extract_dictionary_mentions(plus_text, "hard_skill", section="plus")
    hard_resp = extract_dictionary_mentions(resp_text, "hard_skill", section="responsibilities")

    soft_req = extract_dictionary_mentions(req_text, "soft_skill", section="requirements")
    soft_plus = extract_dictionary_mentions(plus_text, "soft_skill", section="plus")
    soft_resp = extract_dictionary_mentions(resp_text, "soft_skill", section="responsibilities")

    cert_req = extract_dictionary_mentions(req_text, "certificate", section="requirements")
    cert_plus = extract_dictionary_mentions(plus_text, "certificate", section="plus")

    hard_skills: list[SkillMention] = []
    for it in hard_req:
        norm = normalize_to_item(it["name_zh"], "hard_skill", threshold=0.70)
        hard_skills.append(
            SkillMention(
                skill_id=(norm or {}).get("item_id"),
                mention=it["name_zh"],
                importance="must",
                evidence=it.get("evidence"),
                source_section=it.get("section"),
                confidence=(norm or {}).get("confidence"),
                mapping_method=(norm or {}).get("mapping_method"),
            )
        )
    for it in hard_plus:
        norm = normalize_to_item(it["name_zh"], "hard_skill", threshold=0.70)
        hard_skills.append(
            SkillMention(
                skill_id=(norm or {}).get("item_id"),
                mention=it["name_zh"],
                importance="plus",
                evidence=it.get("evidence"),
                source_section=it.get("section"),
                confidence=(norm or {}).get("confidence"),
                mapping_method=(norm or {}).get("mapping_method"),
            )
        )
    for it in hard_resp:
        # responsibilities implies ability, but not always a strict requirement
        norm = normalize_to_item(it["name_zh"], "hard_skill", threshold=0.70)
        hard_skills.append(
            SkillMention(
                skill_id=(norm or {}).get("item_id"),
                mention=it["name_zh"],
                importance="must_low",
                evidence=it.get("evidence"),
                source_section=it.get("section"),
                confidence=(norm or {}).get("confidence"),
                mapping_method=(norm or {}).get("mapping_method"),
            )
        )

    # de-dup by mention+importance
    seen = set()
    hard_skills_dedup = []
    for s in hard_skills:
        key = (s.mention, s.importance)
        if key in seen:
            continue
        seen.add(key)
        hard_skills_dedup.append(s)

    soft_skills: list[SoftSkillMention] = []
    for it in soft_req:
        norm = normalize_to_item(it["name_zh"], "soft_skill", threshold=0.72)
        soft_skills.append(
            SoftSkillMention(
                soft_skill_id=(norm or {}).get("item_id"),
                name=it["name_zh"],
                importance="must",
                evidence=it.get("evidence"),
                source_section=it.get("section"),
                confidence=(norm or {}).get("confidence"),
                mapping_method=(norm or {}).get("mapping_method"),
            )
        )
    for it in soft_plus:
        norm = normalize_to_item(it["name_zh"], "soft_skill", threshold=0.72)
        soft_skills.append(
            SoftSkillMention(
                soft_skill_id=(norm or {}).get("item_id"),
                name=it["name_zh"],
                importance="plus",
                evidence=it.get("evidence"),
                source_section=it.get("section"),
                confidence=(norm or {}).get("confidence"),
                mapping_method=(norm or {}).get("mapping_method"),
            )
        )
    for it in soft_resp:
        norm = normalize_to_item(it["name_zh"], "soft_skill", threshold=0.72)
        soft_skills.append(
            SoftSkillMention(
                soft_skill_id=(norm or {}).get("item_id"),
                name=it["name_zh"],
                importance="must_low",
                evidence=it.get("evidence"),
                source_section=it.get("section"),
                confidence=(norm or {}).get("confidence"),
                mapping_method=(norm or {}).get("mapping_method"),
            )
        )

    certs: list[CertificateMention] = []
    for it in cert_req:
        norm = normalize_to_item(it["name_zh"], "certificate", threshold=0.80)
        certs.append(
            CertificateMention(
                certificate_id=(norm or {}).get("item_id"),
                name=it["name_zh"],
                importance="must",
                evidence=it.get("evidence"),
                source_section=it.get("section"),
                confidence=(norm or {}).get("confidence"),
                mapping_method=(norm or {}).get("mapping_method"),
            )
        )
    for it in cert_plus:
        norm = normalize_to_item(it["name_zh"], "certificate", threshold=0.80)
        certs.append(
            CertificateMention(
                certificate_id=(norm or {}).get("item_id"),
                name=it["name_zh"],
                importance="plus",
                evidence=it.get("evidence"),
                source_section=it.get("section"),
                confidence=(norm or {}).get("confidence"),
                mapping_method=(norm or {}).get("mapping_method"),
            )
        )

    # basic requirements from req_text + job fields
    edu = _extract_education(req_text) or _extract_education(desc)
    exp = _extract_experience_years_min(req_text) or _extract_experience_years_min(desc)
    locs = []
    if job.get("location"):
        locs = [job["location"]]
    basic = BasicRequirements(education=edu, experience_years_min=exp, location=locs)

    llm_hints = _llm_extract_job_hints(job.get("title") or "", desc)
    if llm_hints:
        existing_hard = {str(x.mention).lower() for x in hard_skills_dedup}
        for name in llm_hints.get("hard_skills") or []:
            raw = str((name or {}).get("name") if isinstance(name, dict) else name or "").strip()
            if not raw or raw.lower() in existing_hard:
                continue
            norm = normalize_to_item(raw, "hard_skill", threshold=0.60)
            level_raw = (name or {}).get("level") if isinstance(name, dict) else None
            prof = proficiency_info(level_raw, default=DEFAULT_JOB_LEVEL)
            hard_skills_dedup.append(
                SkillMention(
                    skill_id=(norm or {}).get("item_id"),
                    mention=(norm or {}).get("name_zh") or raw,
                    importance="must_low",
                    level=str(prof["level"]),
                    proficiency=str(prof["level"]),
                    proficiency_label=str(prof["label"]),
                    proficiency_score=float(prof["score"]),
                    evidence="LLM补充抽取",
                    source_section="llm",
                    confidence=(norm or {}).get("confidence"),
                    mapping_method=(norm or {}).get("mapping_method") or "llm",
                )
            )
            existing_hard.add(raw.lower())

        existing_soft = {str(x.name).lower() for x in soft_skills}
        for name in llm_hints.get("soft_skills") or []:
            raw = str(name or "").strip()
            if not raw or raw.lower() in existing_soft:
                continue
            norm = normalize_to_item(raw, "soft_skill", threshold=0.60)
            soft_skills.append(
                SoftSkillMention(
                    soft_skill_id=(norm or {}).get("item_id"),
                    name=(norm or {}).get("name_zh") or raw,
                    importance="must_low",
                    evidence="LLM补充抽取",
                    source_section="llm",
                    confidence=(norm or {}).get("confidence"),
                    mapping_method=(norm or {}).get("mapping_method") or "llm",
                )
            )
            existing_soft.add(raw.lower())

        existing_cert = {str(x.name).lower() for x in certs}
        for name in llm_hints.get("certificates") or []:
            raw = str(name or "").strip()
            if not raw or raw.lower() in existing_cert:
                continue
            norm = normalize_to_item(raw, "certificate", threshold=0.60)
            certs.append(
                CertificateMention(
                    certificate_id=(norm or {}).get("item_id"),
                    name=(norm or {}).get("name_zh") or raw,
                    importance="plus",
                    evidence="LLM补充抽取",
                    source_section="llm",
                    confidence=(norm or {}).get("confidence"),
                    mapping_method=(norm or {}).get("mapping_method") or "llm",
                )
            )
            existing_cert.add(raw.lower())

        if not basic.education and llm_hints.get("education"):
            basic.education = llm_hints.get("education")
        if basic.experience_years_min is None and llm_hints.get("experience_years_min") is not None:
            try:
                basic.experience_years_min = int(llm_hints.get("experience_years_min"))
            except Exception:
                pass

    family = _normalize_family((llm_hints or {}).get("job_family"), infer_job_family(job.get("title") or ""))
    existing_mentions = {
        str(item.mention or "").strip().lower()
        for item in hard_skills_dedup
        if str(item.mention or "").strip()
    }
    hard_skills_dedup.extend(
        _fallback_sales_hard_skills(
            title=str(job.get("title") or ""),
            family=family,
            req_text=req_text,
            plus_text=plus_text,
            resp_text=resp_text,
            desc=desc,
            existing_mentions=existing_mentions,
        )
    )
    for item in hard_skills_dedup:
        if not item.level:
            prof = infer_required_proficiency_from_text(item.mention, f"{job.get('title') or ''}\n{desc}\n{item.evidence or ''}", default=DEFAULT_JOB_LEVEL)
            item.level = str(prof["level"])
            item.proficiency = str(prof["level"])
            item.proficiency_label = str(prof["label"])
            item.proficiency_score = float(prof["score"])

    profile = JobProfile(
        job_id=job_id,
        hard_skills=hard_skills_dedup,
        soft_skills=soft_skills,
        certificates=certs,
        basic_requirements=basic,
        tags=_dedupe_tags((llm_hints or {}).get("tags") or []),
        job_family=family,
    )
    db.upsert_job_profile(job_id, profile_json=json.dumps(profile.model_dump(), ensure_ascii=False), updated_at=now_iso())
    return profile
