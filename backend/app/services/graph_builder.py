from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Dict, List, Tuple

from app.db import sqlite as db
from app.services.graph_store import graph_store


_LEVEL_ORDER = [
    ("intern", ["实习", "intern"]),
    ("junior", ["初级", "助理", "junior", "jr"]),
    ("mid", ["中级", "工程师", "mid"]),
    ("senior", ["高级", "资深", "senior", "sr"]),
    ("lead", ["主管", "组长", "leader"]),
    ("manager", ["经理", "manager"]),
    ("director", ["总监", "director"]),
]


def _level_rank(title: str) -> int:
    t = (title or "").lower()
    for i, (_, kws) in enumerate(_LEVEL_ORDER):
        if any(kw.lower() in t for kw in kws):
            return i
    return 2  # default mid


def _base_role(title: str) -> str:
    t = title or ""
    # remove typical level tokens
    for _, kws in _LEVEL_ORDER:
        for kw in kws:
            t = re.sub(re.escape(kw), "", t, flags=re.I)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _job_skills_set(job_profile: dict[str, Any]) -> set[str]:
    s = set()
    for js in job_profile.get("hard_skills", []):
        sid = (js.get("skill_id") or "").strip()
        m = (js.get("mention") or "").strip()
        if sid:
            s.add(sid)
        elif m:
            s.add(m)
    return s


def rebuild_graph_from_profiles(limit: int | None = None) -> dict[str, Any]:
    # Load jobs and job_profiles
    # For demo, iterate jobs list; in production you'd query profiles table directly.
    jobs = db.list_jobs(limit=limit or 5000, offset=0)
    # Add nodes
    job_profiles: dict[str, dict[str, Any]] = {}
    for j in jobs:
        jp = db.get_job_profile(j["job_id"])
        if not jp:
            continue
        job_profiles[j["job_id"]] = jp["profile"]
        graph_store.upsert_job_node(j["job_id"], {"title": j.get("title"), "job_family": jp["profile"].get("job_family")})

    # Vertical edges: group by (job_family, base_role)
    groups: dict[tuple[str, str], list[str]] = defaultdict(list)
    for job_id, prof in job_profiles.items():
        jf = prof.get("job_family") or "general"
        base = _base_role(db.get_job(job_id).get("title") if db.get_job(job_id) else "")
        groups[(jf, base)].append(job_id)

    for (jf, base), job_ids in groups.items():
        # sort by level rank, then connect chain
        job_ids_sorted = sorted(job_ids, key=lambda jid: _level_rank(db.get_job(jid).get("title") if db.get_job(jid) else ""))
        for a, b in zip(job_ids_sorted, job_ids_sorted[1:]):
            graph_store.upsert_edge(a, b, "NEXT_LEVEL", {"weight": 1.0, "job_family": jf})

    # Switch edges: skill overlap
    ids = list(job_profiles.keys())
    skills_map = {jid: _job_skills_set(job_profiles[jid]) for jid in ids}

    for src in ids:
        src_sk = skills_map[src]
        if not src_sk:
            continue
        sims = []
        for dst in ids:
            if src == dst:
                continue
            dst_sk = skills_map[dst]
            if not dst_sk:
                continue
            inter = len(src_sk & dst_sk)
            union = len(src_sk | dst_sk)
            jacc = inter / union if union else 0.0
            if jacc > 0:
                sims.append((jacc, dst))
        sims.sort(reverse=True)
        for w, dst in sims[:8]:
            graph_store.upsert_edge(src, dst, "SWITCH_TO", {"weight": float(w)})

    return {"nodes": len(graph_store.g.nodes), "edges": len(graph_store.g.edges)}
