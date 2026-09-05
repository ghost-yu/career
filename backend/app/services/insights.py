from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.db import sqlite as db
from app.services.dictionary_cache import dictionary_cache
from app.services.kb import load_kb_index, search_kb
from app.services.role_graph import role_graph
from app.utils.labels import job_family_label


_SKILL_NAME_CACHE: dict[str, str] | None = None


def _skill_names() -> dict[str, str]:
    global _SKILL_NAME_CACHE
    if _SKILL_NAME_CACHE is None:
        snap = dictionary_cache.get_snapshot(force=True)
        _SKILL_NAME_CACHE = {
            it.get("item_id") or "": it.get("name_zh") or it.get("name_en") or it.get("item_id") or ""
            for it in snap.items
            if it.get("item_id")
        }
    return _SKILL_NAME_CACHE


def _salary_band(value: int | None) -> str:
    if value is None:
        return "未知"
    if value < 8000:
        return "8k以下"
    if value < 12000:
        return "8k-12k"
    if value < 20000:
        return "12k-20k"
    if value < 30000:
        return "20k-30k"
    return "30k以上"


def _safe_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except Exception:
        return None




def _ensure_role_graph_loaded() -> None:
    try:
        if getattr(role_graph, 'g', None) is not None and role_graph.g.number_of_nodes() == 0 and db.count_roles() > 0:
            role_graph.rebuild()
    except Exception:
        pass


def _report_export_runtime_ready() -> bool:
    """Check whether report export dependencies are importable at runtime."""
    try:
        import docx  # noqa: F401
        import reportlab  # noqa: F401
        return True
    except Exception:
        return False

def build_market_overview(top_n: int = 10) -> dict[str, Any]:
    jobs = db.list_jobs(limit=100000, offset=0)
    roles = db.list_roles(limit=5000, offset=0)

    city_counter: Counter[str] = Counter()
    industry_counter: Counter[str] = Counter()
    family_counter: Counter[str] = Counter()
    salary_counter: Counter[str] = Counter()
    company_type_counter: Counter[str] = Counter()
    company_size_counter: Counter[str] = Counter()

    for job in jobs:
        if job.get("location"):
            city = str(job["location"]).split("·")[0].split("-")[0].strip()
            if city:
                city_counter[city] += 1
        if job.get("industry"):
            for item in str(job["industry"]).replace("/", ",").split(","):
                item = item.strip()
                if item:
                    industry_counter[item] += 1
        if job.get("company_type"):
            company_type_counter[str(job["company_type"]).strip()] += 1
        if job.get("company_size"):
            company_size_counter[str(job["company_size"]).strip()] += 1
        mid_salary = None
        if job.get("salary_min") is not None and job.get("salary_max") is not None:
            mid_salary = int((int(job["salary_min"]) + int(job["salary_max"])) / 2)
        else:
            mid_salary = _safe_int(job.get("salary_min") or job.get("salary_max"))
        salary_counter[_salary_band(mid_salary)] += 1

    for role in roles:
        family_counter[str(role.get("job_family") or "general")] += 1

    skill_names = _skill_names()
    hard_counter: Counter[str] = Counter()
    soft_counter: Counter[str] = Counter()
    cert_counter: Counter[str] = Counter()

    for role in roles:
        rp = db.get_role_profile(role["role_id"])
        if not rp:
            continue
        profile = rp.get("profile") or {}
        for item in (profile.get("top_hard_skills") or [])[:20]:
            sid = item.get("skill_id") or item.get("name")
            if sid:
                hard_counter[skill_names.get(sid, item.get("name") or sid)] += int(item.get("freq") or 1)
        for item in (profile.get("top_soft_skills") or [])[:12]:
            sid = item.get("soft_skill_id") or item.get("name")
            if sid:
                soft_counter[skill_names.get(sid, item.get("name") or sid)] += int(item.get("freq") or 1)
        for item in (profile.get("top_certificates") or [])[:12]:
            sid = item.get("certificate_id") or item.get("name")
            if sid:
                cert_counter[skill_names.get(sid, item.get("name") or sid)] += int(item.get("freq") or 1)

    return {
        "counts": {
            "jobs": db.count_jobs(),
            "job_profiles": db.count_job_profiles(),
            "roles": db.count_roles(),
            "role_members": db.count_role_members(),
            "students": db.count_students(),
            "reports": db.count_reports(),
        },
        "top_cities": [{"name": k, "count": v} for k, v in city_counter.most_common(top_n)],
        "top_industries": [{"name": k, "count": v} for k, v in industry_counter.most_common(top_n)],
        "top_job_families": [{"name": k, "label": job_family_label(k), "count": v} for k, v in family_counter.most_common(top_n)],
        "salary_bands": [{"name": k, "count": v} for k, v in salary_counter.most_common()],
        "top_company_types": [{"name": k, "count": v} for k, v in company_type_counter.most_common(top_n)],
        "top_company_sizes": [{"name": k, "count": v} for k, v in company_size_counter.most_common(top_n)],
        "top_hard_skills": [{"name": k, "count": v} for k, v in hard_counter.most_common(top_n)],
        "top_soft_skills": [{"name": k, "count": v} for k, v in soft_counter.most_common(top_n)],
        "top_certificates": [{"name": k, "count": v} for k, v in cert_counter.most_common(top_n)],
    }


def list_featured_roles(top_k: int = 10, job_family: str | None = None) -> list[dict[str, Any]]:
    _ensure_role_graph_loaded()
    roles = db.list_roles(job_family=job_family, limit=5000, offset=0)
    items: list[dict[str, Any]] = []
    for role in roles:
        rp = db.get_role_profile(role["role_id"])
        if not rp:
            continue
        profile = rp.get("profile") or {}
        members = db.list_role_members(role["role_id"])
        try:
            switch_paths = role_graph.get_switch_paths(role["role_id"], top_k=3, max_hops=2)
        except Exception:
            switch_paths = []
        try:
            vertical_path = role_graph.get_vertical_path(role["role_id"], max_hops=5)
        except Exception:
            vertical_path = []
        items.append(
            {
                **role,
                "member_count": len(members),
                "salary_stats": profile.get("salary_stats") or {},
                "top_hard_skills": (profile.get("top_hard_skills") or [])[:8],
                "top_soft_skills": (profile.get("top_soft_skills") or [])[:6],
                "top_certificates": (profile.get("top_certificates") or [])[:6],
                "sample_job_ids": (profile.get("sample_job_ids") or [])[:3],
                "switch_path_count": len(switch_paths),
                "vertical_depth": len(vertical_path),
            }
        )
    items.sort(key=lambda x: (x.get("member_count") or 0, x.get("switch_path_count") or 0), reverse=True)
    return items[:top_k]


def get_role_cockpit(role_id: str, switch_top_k: int = 5) -> dict[str, Any] | None:
    _ensure_role_graph_loaded()
    role = db.get_role(role_id)
    if not role:
        return None
    rp = db.get_role_profile(role_id)
    members = db.list_role_members(role_id)
    member_jobs = []
    for job_id in members[:10]:
        job = db.get_job(job_id)
        if job:
            member_jobs.append(job)
    return {
        "role": role,
        "profile": rp,
        "member_count": len(members),
        "member_jobs": member_jobs,
        "vertical_path": role_graph.get_vertical_path(role_id, max_hops=6),
        "switch_paths": role_graph.get_switch_paths_explained(role_id, top_k=switch_top_k, max_hops=2),
    }


def build_competition_readiness() -> dict[str, Any]:
    _ensure_role_graph_loaded()
    roles = db.list_roles(limit=5000, offset=0)
    roles_with_switch_2plus = 0
    roles_with_vertical_2plus = 0
    detailed_samples: list[dict[str, Any]] = []
    for role in roles:
        role_id = role["role_id"]
        try:
            vertical = role_graph.get_vertical_path(role_id, max_hops=6)
        except Exception:
            vertical = []
        try:
            switches = role_graph.get_switch_paths(role_id, top_k=3, max_hops=2)
        except Exception:
            switches = []
        if len(vertical) >= 2:
            roles_with_vertical_2plus += 1
        if len(switches) >= 2:
            roles_with_switch_2plus += 1
            if len(detailed_samples) < 5:
                detailed_samples.append(
                    {
                        "role_id": role_id,
                        "title": role.get("title_rep") or role.get("base_role"),
                        "paths": switches[:2],
                    }
                )

    job_profiles_count = db.count_job_profiles()
    student_profiles_count = db.count_student_profiles()
    reports_count = db.count_reports()
    export_runtime_ready = _report_export_runtime_ready()

    return {
        "requirements": {
            "job_profiles_at_least_10": job_profiles_count >= 10,
            "roles_at_least_10": db.count_roles() >= 10,
            "roles_with_vertical_paths_at_least_5": roles_with_vertical_2plus >= 5,
            "roles_with_switch_paths_at_least_5": roles_with_switch_2plus >= 5,
            "students_profile_supported": student_profiles_count > 0,
            "report_generate_supported": job_profiles_count > 0 and student_profiles_count > 0,
            "report_export_supported": export_runtime_ready,
        },
        "metrics": {
            "job_profiles": job_profiles_count,
            "roles": db.count_roles(),
            "roles_with_vertical_paths": roles_with_vertical_2plus,
            "roles_with_switch_paths": roles_with_switch_2plus,
            "student_profiles": student_profiles_count,
            "reports": reports_count,
            "report_export_runtime_ready": export_runtime_ready,
        },
        "sample_switch_roles": detailed_samples,
    }


def build_kb_readiness() -> dict[str, Any]:
    kb_root = Path(settings.kb_dir)
    kb_root_exists = kb_root.exists() and kb_root.is_dir()
    all_docs: list[Path] = []
    generated_docs: list[Path] = []
    if kb_root_exists:
        for p in kb_root.rglob("*"):
            if not p.is_file():
                continue
            if p.suffix.lower() not in {".md", ".txt"}:
                continue
            all_docs.append(p)
            if "generated" in {x.lower() for x in p.parts}:
                generated_docs.append(p)

    kb_doc_count = len(all_docs)
    generated_doc_count = len(generated_docs)
    kb_index_path = Path(settings.kb_vector_index_path)
    kb_index_exists = kb_index_path.exists() and kb_index_path.is_file()
    kb_index_loadable = bool(kb_index_exists and load_kb_index())

    search_smoke_hits = 0
    search_smoke_titles: list[str] = []
    if kb_index_loadable:
        try:
            smoke_rows = search_kb("职业规划", top_k=3, use_embedding=False)
            search_smoke_hits = len(smoke_rows)
            search_smoke_titles = [str(x.get("title") or "").strip() for x in smoke_rows if str(x.get("title") or "").strip()][:3]
        except Exception:
            search_smoke_hits = 0
            search_smoke_titles = []

    requirements = {
        "kb_root_accessible": kb_root_exists,
        "kb_docs_at_least_20": kb_doc_count >= 20,
        "kb_generated_docs_present": generated_doc_count >= 5,
        "kb_vector_index_present": kb_index_exists,
        "kb_vector_index_loadable": kb_index_loadable,
        "kb_search_available": search_smoke_hits > 0,
        "kb_ready_for_match_report": kb_index_loadable and search_smoke_hits > 0 and kb_doc_count > 0,
    }
    metrics = {
        "kb_root": str(kb_root),
        "kb_docs": kb_doc_count,
        "kb_generated_docs": generated_doc_count,
        "kb_vector_index_path": str(kb_index_path),
        "kb_vector_index_size_bytes": int(kb_index_path.stat().st_size) if kb_index_exists else 0,
        "kb_search_smoke_hits": search_smoke_hits,
    }
    return {
        "requirements": requirements,
        "metrics": metrics,
        "sample_titles": search_smoke_titles,
    }
