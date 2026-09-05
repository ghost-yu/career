from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from app.db import sqlite as db
from app.services.role_builder import build_roles_from_profiles
from app.services.role_graph import role_graph
from app.services.role_retrieval import build_role_index, search_roles
from app.utils.labels import enrich_role_labels

router = APIRouter()


def _ensure_role_graph_loaded() -> None:
    try:
        if role_graph.g.number_of_nodes() == 0 and db.count_roles() > 0:
            role_graph.rebuild()
    except Exception:
        pass


@router.get("")
def list_roles(job_family: str | None = None, q: str | None = None, limit: int = 50, offset: int = 0) -> dict[str, Any]:
    items = [enrich_role_labels(x) for x in db.list_roles(job_family=job_family, q=q, limit=limit, offset=offset)]
    return {"items": items, "limit": limit, "offset": offset}


@router.get("/search")
def search(
    q: str,
    top_k: int = Query(default=10, ge=1, le=50),
    use_embedding: bool = Query(default=True, description="Enable embedding rerank"),
) -> dict[str, Any]:
    return {
        "query": q,
        "items": [enrich_role_labels(x) for x in search_roles(q, top_k=top_k, use_embedding=use_embedding)],
        "use_embedding": use_embedding,
    }


@router.post("/rebuild")
def rebuild(clear_existing: bool = True, limit: int | None = None, rebuild_graph: bool = True, build_index: bool = True) -> dict[str, Any]:
    summary = build_roles_from_profiles(limit=limit, clear_existing=clear_existing)
    out: dict[str, Any] = {"roles": summary}
    if rebuild_graph:
        out["role_graph"] = role_graph.rebuild()
    if build_index:
        out["role_index"] = build_role_index()
    return out


@router.post("/index/build")
def build_index(limit: int = 5000) -> dict[str, Any]:
    return build_role_index(limit=limit)


@router.get("/{role_id}")
def get_role(role_id: str, switch_top_k: int = 5) -> dict[str, Any]:
    _ensure_role_graph_loaded()
    r = db.get_role(role_id)
    if not r:
        return {"error": "not_found"}
    rp = db.get_role_profile(role_id)
    if rp and isinstance(rp.get("profile"), dict):
        rp = dict(rp)
        rp["profile"] = enrich_role_labels(rp.get("profile"))
    members = db.list_role_members(role_id)
    member_jobs = []
    for job_id in members[:12]:
        job = db.get_job(job_id)
        if job:
            member_jobs.append(job)
    return {
        "role": enrich_role_labels(r),
        "profile": rp,
        "members": members[:20],
        "member_count": len(members),
        "member_jobs": member_jobs,
        "vertical_path": role_graph.get_vertical_path(role_id, max_hops=6),
        "switch_paths": role_graph.get_switch_paths_explained(role_id, top_k=switch_top_k, max_hops=2),
    }
