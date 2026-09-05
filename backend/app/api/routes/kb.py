from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Query

from app.db import sqlite as db
from app.services.kb import build_kb_index, search_kb
from app.services.kb_materializer import materialize_kb_from_db
from app.utils.ids import gen_id, now_iso

router = APIRouter()


@router.get("/search")
def kb_search(
    q: str = Query(..., description="search query"),
    top_k: int = Query(default=5, ge=1, le=20),
    use_embedding: bool = Query(default=True, description="Enable embedding rerank"),
) -> dict[str, Any]:
    items = search_kb(q, top_k=top_k, use_embedding=use_embedding)
    return {"items": items, "query": q, "top_k": top_k, "use_embedding": use_embedding}


@router.post("/rebuild")
def kb_rebuild() -> dict[str, Any]:
    res = build_kb_index()
    return {"ok": True, **res}


@router.post("/rebuild_task")
def kb_rebuild_task() -> dict[str, Any]:
    """Create an async task to rebuild KB index."""
    db.init_db()
    task_id = gen_id("TASK", 12)
    db.create_task(
        {
            "task_id": task_id,
            "task_type": "REBUILD_KB_INDEX",
            "payload_json": "{}",
            "status": "PENDING",
            "progress": 0.0,
            "result_json": None,
            "error": None,
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }
    )
    return {"ok": True, "task_id": task_id}


@router.post("/materialize")
def kb_materialize(body: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = body or {}
    materialized = materialize_kb_from_db(
        max_roles=int(payload.get("max_roles") or 300),
        max_jobs_per_role=int(payload.get("max_jobs_per_role") or 3),
        clear_generated=bool(payload.get("clear_generated", True)),
    )
    if bool(payload.get("rebuild_index", True)):
        indexed = build_kb_index(kb_dir=payload.get("kb_dir"))
    else:
        indexed = None
    return {"ok": True, "materialized": materialized, "indexed": indexed}


@router.post("/materialize_task")
def kb_materialize_task(body: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = body or {}
    db.init_db()
    task_id = gen_id("TASK", 12)
    db.create_task(
        {
            "task_id": task_id,
            "task_type": "MATERIALIZE_KB_FROM_DB",
            "payload_json": json.dumps(
                {
                    "max_roles": int(payload.get("max_roles") or 300),
                    "max_jobs_per_role": int(payload.get("max_jobs_per_role") or 3),
                    "clear_generated": bool(payload.get("clear_generated", True)),
                    "rebuild_index": bool(payload.get("rebuild_index", True)),
                    "kb_dir": payload.get("kb_dir"),
                },
                ensure_ascii=False,
            ),
            "status": "PENDING",
            "progress": 0.0,
            "result_json": None,
            "error": None,
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }
    )
    return {"ok": True, "task_id": task_id}
