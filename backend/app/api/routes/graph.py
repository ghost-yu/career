from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from app.services.graph_builder import rebuild_graph_from_profiles
from app.services.graph_store import graph_store
from app.services.role_graph import role_graph

router = APIRouter()


@router.post("/rebuild")
def rebuild(limit: int | None = None) -> dict[str, Any]:
    """Rebuild **job-level** graph (NetworkX/Neo4j depending on config)."""
    return rebuild_graph_from_profiles(limit=limit)


@router.get("/job/{job_id}/vertical_path")
def vertical(job_id: str, max_hops: int = 6) -> dict[str, Any]:
    return {"job_id": job_id, "path": graph_store.get_vertical_path(job_id, max_hops=max_hops)}


@router.get("/job/{job_id}/switch_paths")
def switch(job_id: str, top_k: int = Query(default=5, ge=1, le=20)) -> dict[str, Any]:
    return {"job_id": job_id, "paths": graph_store.get_switch_paths(job_id, top_k=top_k)}


# --------------------
# Role-level graph API
# --------------------


@router.post("/role/rebuild")
def rebuild_role_graph(limit_roles: int | None = None) -> dict[str, Any]:
    return role_graph.rebuild(limit_roles=limit_roles)


@router.get("/role/{role_id}/vertical_path")
def role_vertical(role_id: str, max_hops: int = 6) -> dict[str, Any]:
    return {"role_id": role_id, "path": role_graph.get_vertical_path(role_id, max_hops=max_hops)}


@router.get("/role/{role_id}/switch_paths")
def role_switch(role_id: str, top_k: int = Query(default=5, ge=1, le=20), max_hops: int = Query(default=2, ge=1, le=3)) -> dict[str, Any]:
    return {"role_id": role_id, "paths": role_graph.get_switch_paths(role_id, top_k=top_k, max_hops=max_hops)}


@router.get("/role/{role_id}/switch_paths_explained")
def role_switch_explained(role_id: str, top_k: int = Query(default=5, ge=1, le=20), max_hops: int = Query(default=2, ge=1, le=3)) -> dict[str, Any]:
    return {"role_id": role_id, "paths": role_graph.get_switch_paths_explained(role_id, top_k=top_k, max_hops=max_hops)}
