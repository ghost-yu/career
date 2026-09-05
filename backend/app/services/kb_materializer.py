from __future__ import annotations

import shutil
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.db import sqlite as db
from app.services.role_graph import role_graph


def _term_list(items: Any, *, limit: int = 12) -> list[str]:
    out: list[str] = []
    for item in items or []:
        if isinstance(item, dict):
            name = str(item.get("name") or item.get("mention") or item.get("skill_id") or "").strip()
        else:
            name = str(item or "").strip()
        if not name:
            continue
        out.append(name)
        if len(out) >= limit:
            break
    return out


def _safe_family_name(value: str) -> str:
    raw = (value or "").strip().lower()
    if not raw:
        return "unknown"
    return "".join(ch if (ch.isalnum() or ch in {"_", "-"}) else "_" for ch in raw)


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _role_doc(role: dict[str, Any], profile: dict[str, Any], sample_jobs: list[dict[str, Any]]) -> str:
    role_id = str(role.get("role_id") or "")
    title = str(role.get("title_rep") or role.get("base_role") or role_id)
    family = str(role.get("job_family") or "")
    level = str(role.get("level_label") or "")
    role_key = str(role.get("role_key") or "")
    hard_skills = _term_list(profile.get("top_hard_skills"), limit=16)
    soft_skills = _term_list(profile.get("top_soft_skills"), limit=10)
    certs = _term_list(profile.get("top_certificates"), limit=8)

    salary_stats = profile.get("salary_stats") or {}
    salary_line = "n/a"
    if isinstance(salary_stats, dict) and salary_stats:
        salary_line = ", ".join(f"{k}={salary_stats.get(k)}" for k in ["count", "median_min", "median_max"] if k in salary_stats)

    lines = [
        f"# {title}",
        "",
        f"- role_id: `{role_id}`",
        f"- role_key: `{role_key}`",
        f"- job_family: `{family}`",
        f"- level_label: `{level}`",
        f"- salary_stats: {salary_line}",
        "",
        "## Core Hard Skills",
    ]
    lines.extend([f"- {s}" for s in hard_skills] or ["- (none)"])
    lines.append("")
    lines.append("## Core Soft Skills")
    lines.extend([f"- {s}" for s in soft_skills] or ["- (none)"])
    lines.append("")
    lines.append("## Certificates")
    lines.extend([f"- {s}" for s in certs] or ["- (none)"])
    lines.append("")
    lines.append("## Sample Job Postings")
    if sample_jobs:
        for job in sample_jobs:
            lines.append(f"- {job.get('title') or '(untitled)'} ({job.get('company_name') or 'unknown_company'})")
    else:
        lines.append("- (none)")
    lines.append("")
    lines.append("## Role Paths")
    try:
        vertical = role_graph.get_vertical_path(role_id) or []
        switches = role_graph.get_switch_paths(role_id, top_k=4, max_hops=2) or []
    except Exception:
        vertical = []
        switches = []
    if vertical:
        lines.append("### Vertical")
        for node in vertical:
            lines.append(f"- {node.get('title') or node.get('role_id')}")
    if switches:
        lines.append("")
        lines.append("### Switch")
        for seq in switches[:4]:
            names = [str(x.get("title") or x.get("role_id") or "").strip() for x in seq]
            names = [x for x in names if x]
            if len(names) >= 2:
                lines.append(f"- {' -> '.join(names)}")
    if not vertical and not switches:
        lines.append("- (not available)")
    lines.append("")
    return "\n".join(lines)


def _family_doc(family: str, roles: list[dict[str, Any]], top_skills: list[str]) -> str:
    lines = [
        f"# Job Family: {family}",
        "",
        f"- role_count: {len(roles)}",
        "",
        "## Roles",
    ]
    for role in roles:
        title = str(role.get("title_rep") or role.get("base_role") or role.get("role_id") or "").strip()
        role_id = str(role.get("role_id") or "").strip()
        level = str(role.get("level_label") or "").strip()
        lines.append(f"- {title} ({level}) [`{role_id}`]")
    lines.append("")
    lines.append("## Top Skills")
    lines.extend([f"- {s}" for s in top_skills] or ["- (none)"])
    lines.append("")
    return "\n".join(lines)


def materialize_kb_from_db(
    *,
    max_roles: int = 300,
    max_jobs_per_role: int = 3,
    clear_generated: bool = True,
) -> dict[str, Any]:
    """Create generated KB docs from role/job data for downstream retrieval."""

    db.init_db()

    kb_root = Path(settings.kb_dir)
    generated_dir = kb_root / "generated"
    roles_dir = generated_dir / "roles"
    families_dir = generated_dir / "job_families"

    if clear_generated and generated_dir.exists():
        shutil.rmtree(generated_dir, ignore_errors=True)
    roles_dir.mkdir(parents=True, exist_ok=True)
    families_dir.mkdir(parents=True, exist_ok=True)

    roles = db.list_roles(limit=max(1, int(max_roles)), offset=0)
    family_roles: dict[str, list[dict[str, Any]]] = defaultdict(list)
    family_skills: dict[str, Counter[str]] = defaultdict(Counter)

    role_docs = 0
    for role in roles:
        role_id = str(role.get("role_id") or "").strip()
        if not role_id:
            continue
        family = str(role.get("job_family") or "unknown").strip() or "unknown"
        family_roles[family].append(role)

        rp = db.get_role_profile(role_id)
        profile = (rp or {}).get("profile") or {}
        for skill in _term_list(profile.get("top_hard_skills"), limit=24):
            family_skills[family][skill] += 1

        member_ids = db.list_role_members(role_id)[: max(1, int(max_jobs_per_role))]
        sample_jobs: list[dict[str, Any]] = []
        for job_id in member_ids:
            job = db.get_job(job_id) or {}
            if job:
                sample_jobs.append(job)

        content = _role_doc(role, profile, sample_jobs)
        _write_text(roles_dir / f"{role_id}.md", content)
        role_docs += 1

    family_docs = 0
    for family, family_role_list in family_roles.items():
        top_skills = [name for name, _ in family_skills.get(family, Counter()).most_common(20)]
        doc = _family_doc(family, family_role_list, top_skills)
        _write_text(families_dir / f"{_safe_family_name(family)}.md", doc)
        family_docs += 1

    index_lines = [
        "# Generated Knowledge Base",
        "",
        "This directory is generated from local DB role/job data.",
        "",
        f"- roles_docs: {role_docs}",
        f"- family_docs: {family_docs}",
        "",
        "## Directories",
        "- `roles/`: one file per role",
        "- `job_families/`: one file per job family",
        "",
    ]
    _write_text(generated_dir / "README.md", "\n".join(index_lines))

    return {
        "kb_dir": str(kb_root),
        "generated_dir": str(generated_dir),
        "roles_docs": role_docs,
        "family_docs": family_docs,
        "roles_scanned": len(roles),
    }

