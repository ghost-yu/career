from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from statistics import mean
from typing import Any

from app.db import sqlite as db
from app.services.career_taxonomy import LEVELS, title_for, track_label
from app.services.dictionary_cache import dictionary_cache
from app.services.job_profile import infer_job_family
from app.utils.ids import gen_id, now_iso

_LEVEL_HINTS = [
    ("director", ["总监", "负责人", "总负责人", "director"]),
    ("lead", ["架构师", "技术负责人", "组长", "leader", "主管", "专家"]),
    ("senior", ["高级", "资深", "senior", "sr"]),
    ("mid", ["工程师", "顾问", "产品经理", "设计师", "研究员"]),
    ("junior", ["实习", "应届", "校招", "初级", "助理", "junior", "jr"]),
]

_IT_EXCLUDE = ["分子", "植物", "混凝土", "农药", "测序", "农业", "生物", "化工", "预制构件"]


def _normalize_family(value: str | None, title: str) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"general", "", "none"}:
        raw = infer_job_family(title)
    alias = {
        "support": "support",
        "implementation": "implementation",
        "security": "security",
        "embedded": "embedded",
        "mobile": "mobile",
        "research": "research",
    }
    return alias.get(raw, raw or "general")


def detect_level(title: str) -> str:
    t = (title or "").lower()
    for lvl, kws in _LEVEL_HINTS:
        if any(kw.lower() in t for kw in kws):
            return lvl
    return "mid"


def is_it_like_job(title: str, description: str, industry: str | None = None) -> bool:
    text = f"{title}\n{description}\n{industry or ''}".lower()
    if any(kw.lower() in text for kw in _IT_EXCLUDE):
        return False
    pos = ["软件", "前端", "后端", "java", "python", "测试", "实施", "交付", "技术支持", "算法", "数据", "运维", "产品", "设计", "嵌入式", "android", "ios", "研发", "开发"]
    return any(kw.lower() in text for kw in pos)


def _skill_name(item_id: str, mention: str) -> str:
    snap = dictionary_cache.get_snapshot(force=False)
    for it in snap.items:
        if it.get("item_id") == item_id:
            return it.get("name_zh") or it.get("name_en") or mention or item_id
    return mention or item_id


def build_roles_from_profiles(limit: int | None = None, clear_existing: bool = True) -> dict[str, Any]:
    db.init_db()
    if clear_existing:
        db.clear_roles()

    groups: dict[tuple[str, str], dict[str, Any]] = {}
    scanned = 0
    used = 0

    for job in db.iter_jobs(batch_size=500):
        if limit is not None and scanned >= int(limit):
            break
        scanned += 1
        jp = db.get_job_profile(job["job_id"])
        if not jp:
            continue
        profile = jp.get("profile") or {}
        if not is_it_like_job(job.get("title") or "", job.get("description") or "", job.get("industry")):
            continue
        family = _normalize_family(profile.get("job_family"), job.get("title") or "")
        if family == "general":
            continue
        level = detect_level(job.get("title") or "")
        key = (family, level)
        used += 1
        g = groups.setdefault(key, {
            "family": family,
            "level": level,
            "jobs": [],
            "skill_counts": Counter(),
            "soft_counts": Counter(),
            "cert_counts": Counter(),
            "salary_min": [],
            "salary_max": [],
            "cities": Counter(),
            "industries": Counter(),
        })
        g["jobs"].append(job["job_id"])
        if job.get("salary_min") is not None:
            try:
                g["salary_min"].append(int(job["salary_min"]))
            except Exception:
                pass
        if job.get("salary_max") is not None:
            try:
                g["salary_max"].append(int(job["salary_max"]))
            except Exception:
                pass
        if job.get("location"):
            city = str(job["location"]).split("·")[0].split("-")[0].strip()
            if city:
                g["cities"][city] += 1
        if job.get("industry"):
            for part in re.split(r"[,/，]", str(job["industry"])):
                part = part.strip()
                if part:
                    g["industries"][part] += 1
        for hs in profile.get("hard_skills") or []:
            sid = (hs.get("skill_id") or hs.get("mention") or "").strip()
            if sid:
                g["skill_counts"][sid] += 2 if (hs.get("importance") == "must") else 1
        for ss in profile.get("soft_skills") or []:
            sid = (ss.get("soft_skill_id") or ss.get("name") or "").strip()
            if sid:
                g["soft_counts"][sid] += 1
        for ct in profile.get("certificates") or []:
            sid = (ct.get("certificate_id") or ct.get("name") or "").strip()
            if sid:
                g["cert_counts"][sid] += 1

    created = 0
    for family, _meta in sorted({(k[0], 0) for k in groups.keys()}):
        pass
    for family in sorted({k[0] for k in groups.keys()}):
        for level in LEVELS:
            key = (family, level)
            g = groups.get(key)
            rid = gen_id("ROLE", 10)
            title = title_for(family, level)
            db.upsert_role({
                "role_id": rid,
                "role_key": f"{family}::{level}",
                "job_family": family,
                "base_role": track_label(family),
                "level_label": level,
                "title_rep": title,
                "created_at": now_iso(),
                "updated_at": now_iso(),
            })
            created += 1
            jobs = (g or {}).get("jobs") or []
            for jid in jobs:
                db.add_role_member(rid, jid)
            skill_counts: Counter[str] = (g or {}).get("skill_counts") or Counter()
            soft_counts: Counter[str] = (g or {}).get("soft_counts") or Counter()
            cert_counts: Counter[str] = (g or {}).get("cert_counts") or Counter()
            prof = {
                "job_family": family,
                "job_family_label": track_label(family),
                "level_label": level,
                "title": title,
                "member_count": len(jobs),
                "sample_job_ids": jobs[:8],
                "top_hard_skills": [
                    {"skill_id": sid, "name": _skill_name(sid, sid), "freq": int(freq)}
                    for sid, freq in skill_counts.most_common(12)
                ],
                "top_soft_skills": [
                    {"soft_skill_id": sid, "name": _skill_name(sid, sid), "freq": int(freq)}
                    for sid, freq in soft_counts.most_common(8)
                ],
                "top_certificates": [
                    {"certificate_id": sid, "name": _skill_name(sid, sid), "freq": int(freq)}
                    for sid, freq in cert_counts.most_common(6)
                ],
                "salary_stats": {
                    "min_avg": int(mean((g or {}).get("salary_min") or [0])) if (g or {}).get("salary_min") else None,
                    "max_avg": int(mean((g or {}).get("salary_max") or [0])) if (g or {}).get("salary_max") else None,
                },
                "top_cities": [{"name": name, "count": count} for name, count in ((g or {}).get("cities") or Counter()).most_common(5)],
                "top_industries": [{"name": name, "count": count} for name, count in ((g or {}).get("industries") or Counter()).most_common(5)],
                "source_member_count": len(jobs),
                "is_virtual": False if g else True,
            }
            db.upsert_role_profile(rid, json.dumps(prof, ensure_ascii=False), updated_at=now_iso())
    return {"scanned_jobs": scanned, "used_jobs": used, "roles": created}
