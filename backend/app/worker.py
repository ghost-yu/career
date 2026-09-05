from __future__ import annotations

"""Simple SQLite-based worker for batch tasks.

Why this exists
---------------
The competition requires processing 10k job postings.
Generating job profiles + building graph/index can be heavy.

Instead of introducing Celery/Redis, this repository provides:
  - a minimal `tasks` table
  - a polling worker process

Run it locally:
  cd backend
  uvicorn app.main:app --reload
  # in another terminal
  python -m app.worker

Or with docker-compose:
  docker compose up --build worker
"""

import csv
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
from pathlib import Path
from typing import Any, Callable

from app.core.config import settings
from app.db import sqlite as db
from app.services.graph_builder import rebuild_graph_from_profiles
from app.services.job_profile import generate_job_profile
from app.services.retrieval import build_job_index
from app.services.role_builder import build_roles_from_profiles
from app.services.role_graph import role_graph
from app.services.role_retrieval import build_role_index
from app.services.kb import build_kb_index
from app.services.kb_materializer import materialize_kb_from_db
from app.utils.ids import gen_id, now_iso
from app.utils.ingest import coerce_sheet_name, map_row, read_excel_any


_COMPUTER_KEYWORDS = [
    "计算机", "软件", "互联网", "信息化", "it", "ai", "人工智能", "算法", "数据", "大数据", "云", "网络", "安全",
    "前端", "后端", "全栈", "测试", "运维", "开发", "编程", "数据库", "机器学习", "深度学习", "java", "python",
    "golang", "c++", "c#", "node", "react", "vue", "android", "ios", "devops", "k8s", "docker",
]


def _is_computer_related(mapped: dict[str, Any]) -> bool:
    text = " ".join(
        [
            str(mapped.get("title") or ""),
            str(mapped.get("description") or ""),
            str(mapped.get("industry") or ""),
            str(mapped.get("company_intro") or ""),
            str(mapped.get("job_code") or ""),
        ]
    ).lower()
    if not text.strip():
        return False
    return any(k in text for k in _COMPUTER_KEYWORDS)


def _update(task_id: str, **kwargs: Any) -> None:
    kwargs.setdefault("updated_at", now_iso())
    db.update_task(task_id, **kwargs)


def handle_ingest_jobs_file(task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    path = payload.get("path")
    encoding = payload.get("encoding") or "utf-8"
    if not path or not os.path.exists(path):
        raise FileNotFoundError(path)

    ext = os.path.splitext(path)[1].lower()

    inserted = 0
    total = 0
    skipped_empty = 0
    skipped_non_computer = 0
    computer_only = bool(payload.get("computer_only", True))

    def insert_one(row: dict[str, Any]) -> None:
        nonlocal inserted, skipped_empty, skipped_non_computer
        # map fields
        mapped = map_row(row, field_map=payload.get("field_map"))
        title = mapped.get("title")
        desc = mapped.get("description")
        if not title and not desc:
            skipped_empty += 1
            return

        if computer_only and not _is_computer_related(mapped):
            skipped_non_computer += 1
            return

        job_id = mapped.get("job_id")
        if not job_id:
            # try job_code; otherwise random
            jc = (mapped.get("job_code") or "").strip()
            if jc:
                job_id = f"{jc}_{inserted+1}"
            else:
                job_id = gen_id("J", 10)

        db.insert_job(
            {
                "job_id": job_id,
                "title": mapped.get("title") or "",
                "location": mapped.get("location"),
                "salary_min": mapped.get("salary_min"),
                "salary_max": mapped.get("salary_max"),
                "salary_period": mapped.get("salary_period"),
                "company_name": mapped.get("company_name"),
                "industry": mapped.get("industry"),
                "company_size": mapped.get("company_size"),
                "company_type": mapped.get("company_type"),
                "job_code": mapped.get("job_code"),
                "description": mapped.get("description"),
                "company_intro": mapped.get("company_intro"),
                "updated_date": mapped.get("updated_date"),
                "source_url": mapped.get("source_url"),
                "raw_json": json.dumps(row, ensure_ascii=False),
            }
        )
        inserted += 1

    # detect approximate total quickly (for progress)
    try:
        with open(path, "r", encoding=encoding, errors="ignore") as f:
            if ext == ".csv":
                total = sum(1 for _ in f) - 1
            elif ext in {".jsonl", ".ndjson"}:
                total = sum(1 for _ in f)
            elif ext == ".json":
                # unknown until loaded
                total = 0
            elif ext in {".xlsx", ".xls"}:
                total = 0
    except Exception:
        total = 0

    if ext == ".csv":
        with open(path, "r", encoding=encoding, errors="ignore", newline="") as f:
            reader = csv.DictReader(f)
            for idx, row in enumerate(reader, start=1):
                insert_one(row)
                if idx % 200 == 0:
                    prog = (idx / total) if total > 0 else 0.0
                    _update(task_id, progress=float(min(0.99, prog)))
    elif ext in {".jsonl", ".ndjson"}:
        with open(path, "r", encoding=encoding, errors="ignore") as f:
            for idx, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                if isinstance(row, dict):
                    insert_one(row)
                if idx % 200 == 0:
                    prog = (idx / total) if total > 0 else 0.0
                    _update(task_id, progress=float(min(0.99, prog)))
    elif ext == ".json":
        with open(path, "r", encoding=encoding, errors="ignore") as f:
            data = json.load(f)
        if isinstance(data, dict):
            data = data.get("items") or data.get("data") or []
        if not isinstance(data, list):
            raise ValueError("JSON root must be list or {items:[...]} ")
        total = len(data)
        for idx, row in enumerate(data, start=1):
            if isinstance(row, dict):
                insert_one(row)
            if idx % 200 == 0:
                prog = (idx / total) if total > 0 else 0.0
                _update(task_id, progress=float(min(0.99, prog)))
    elif ext in {".xlsx", ".xls"}:
        sheet_name = coerce_sheet_name(payload.get("sheet_name", 0))
        df = read_excel_any(path, sheet_name=sheet_name)
        total = int(len(df.index))
        for idx, row in enumerate(df.to_dict(orient="records"), start=1):
            insert_one(row)
            if idx % 200 == 0:
                prog = (idx / total) if total > 0 else 0.0
                _update(task_id, progress=float(min(0.99, prog)))
    else:
        raise ValueError(f"Unsupported file type: {ext}. Please use csv/json/jsonl/xlsx, or install xlrd for xls.")

    return {
        "inserted": inserted,
        "path": path,
        "detected_total": total,
        "computer_only": computer_only,
        "skipped_empty": skipped_empty,
        "skipped_non_computer": skipped_non_computer,
    }


def handle_bulk_generate_job_profiles(task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    only_missing = bool(payload.get("only_missing", True))
    limit = payload.get("limit")
    requested_workers = int(payload.get("workers") or settings.job_profile_bulk_workers or 1)
    max_workers = max(1, int(settings.job_profile_bulk_workers_max or 16))
    workers = max(1, min(requested_workers, max_workers))

    total_jobs = db.count_jobs()
    scanned = 0
    generated = 0
    failed = 0
    candidate_job_ids: list[str] = []

    for j in db.iter_jobs(batch_size=200):
        if limit is not None and scanned >= int(limit):
            break
        scanned += 1
        existing = db.get_job_profile(j["job_id"])
        existing_profile = (existing or {}).get("profile") if isinstance(existing, dict) else None
        has_any_signal = bool(
            isinstance(existing_profile, dict)
            and (
                len(existing_profile.get("hard_skills") or [])
                or len(existing_profile.get("soft_skills") or [])
                or len(existing_profile.get("certificates") or [])
            )
        )
        if only_missing and existing and has_any_signal:
            # still progress by scanned
            if scanned % 50 == 0:
                denom = int(limit) if limit is not None else max(1, total_jobs)
                _update(task_id, progress=float(min(0.2, 0.2 * scanned / denom)))
            continue
        candidate_job_ids.append(str(j["job_id"]))

    total_candidates = len(candidate_job_ids)
    if not total_candidates:
        _update(task_id, progress=0.99)
        return {
            "scanned": scanned,
            "generated": generated,
            "failed": failed,
            "targeted": total_candidates,
            "workers": workers,
            "only_missing": only_missing,
        }

    if workers <= 1:
        for idx, job_id in enumerate(candidate_job_ids, start=1):
            try:
                generate_job_profile(job_id)
                generated += 1
            except Exception:
                failed += 1
            if idx % 20 == 0:
                _update(task_id, progress=float(min(0.99, 0.2 + 0.79 * (idx / total_candidates))))
    else:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="job-profile") as executor:
            futures = {executor.submit(generate_job_profile, job_id): job_id for job_id in candidate_job_ids}
            done = 0
            for fut in as_completed(futures):
                done += 1
                try:
                    fut.result()
                    generated += 1
                except Exception:
                    failed += 1
                if done % max(20, workers * 2) == 0:
                    _update(task_id, progress=float(min(0.99, 0.2 + 0.79 * (done / total_candidates))))

    return {
        "scanned": scanned,
        "generated": generated,
        "failed": failed,
        "targeted": total_candidates,
        "workers": workers,
        "only_missing": only_missing,
    }


def handle_build_job_index(task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    limit = int(payload.get("limit") or 10000)
    _update(task_id, progress=0.3)
    res = build_job_index(limit=limit)
    _update(task_id, progress=0.9)
    return res


def handle_rebuild_job_graph(task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    limit = payload.get("limit")
    _update(task_id, progress=0.3)
    res = rebuild_graph_from_profiles(limit=limit)
    _update(task_id, progress=0.9)
    return res


def handle_rebuild_roles_and_role_graph(task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    clear_existing = bool(payload.get("clear_existing", True))
    limit = payload.get("limit")
    build_idx = bool(payload.get("build_index", True))

    _update(task_id, progress=0.1)
    roles_summary = build_roles_from_profiles(limit=limit, clear_existing=clear_existing)
    _update(task_id, progress=0.6)
    graph_summary = role_graph.rebuild()
    idx_summary = None
    if build_idx:
        _update(task_id, progress=0.8)
        idx_summary = build_role_index(limit=5000)

    return {"roles": roles_summary, "role_graph": graph_summary, "role_index": idx_summary}


def handle_build_role_index(task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    limit = int(payload.get("limit") or 5000)
    _update(task_id, progress=0.3)
    res = build_role_index(limit=limit)
    _update(task_id, progress=0.9)
    return res




def handle_rebuild_kb_index(task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    kb_dir = payload.get("kb_dir")
    _update(task_id, progress=0.2)
    res = build_kb_index(kb_dir=kb_dir)
    _update(task_id, progress=0.9)
    return res


def handle_materialize_kb_from_db(task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    _update(task_id, progress=0.2)
    materialized = materialize_kb_from_db(
        max_roles=int(payload.get("max_roles") or 300),
        max_jobs_per_role=int(payload.get("max_jobs_per_role") or 3),
        clear_generated=bool(payload.get("clear_generated", True)),
    )
    _update(task_id, progress=0.75)
    if bool(payload.get("rebuild_index", True)):
        indexed = build_kb_index(kb_dir=payload.get("kb_dir"))
    else:
        indexed = None
    _update(task_id, progress=0.95)
    return {"materialized": materialized, "indexed": indexed}

HANDLERS: dict[str, Callable[[str, dict[str, Any]], dict[str, Any]]] = {
    "INGEST_JOBS_FILE": handle_ingest_jobs_file,
    "BULK_GENERATE_JOB_PROFILES": handle_bulk_generate_job_profiles,
    "BUILD_JOB_INDEX": handle_build_job_index,
    "REBUILD_JOB_GRAPH": handle_rebuild_job_graph,
    "REBUILD_ROLES_AND_ROLE_GRAPH": handle_rebuild_roles_and_role_graph,
    "BUILD_ROLE_INDEX": handle_build_role_index,
    "REBUILD_KB_INDEX": handle_rebuild_kb_index,
    "MATERIALIZE_KB_FROM_DB": handle_materialize_kb_from_db,
}


def process_one(task: dict[str, Any]) -> None:
    task_id = task["task_id"]
    task_type = task["task_type"]
    try:
        payload = json.loads(task.get("payload_json") or "{}")
    except Exception:
        payload = {}

    handler = HANDLERS.get(task_type)
    if not handler:
        raise ValueError(f"Unknown task_type: {task_type}")

    _update(task_id, status="RUNNING", progress=float(task.get("progress") or 0.0))
    result = handler(task_id, payload)
    _update(task_id, status="SUCCESS", progress=1.0, result_json=json.dumps(result, ensure_ascii=False), error=None)


def main() -> None:
    db.init_db()
    print(f"[worker] started. sqlite={settings.sqlite_path} poll={settings.worker_poll_seconds}s")
    while True:
        task = db.claim_next_task()
        if not task:
            time.sleep(float(settings.worker_poll_seconds))
            continue
        task_id = task["task_id"]
        try:
            process_one(task)
            print(f"[worker] ✅ {task_id} {task['task_type']}")
        except Exception as e:
            _update(task_id, status="FAILED", progress=float(task.get("progress") or 0.0), error=str(e))
            print(f"[worker] ❌ {task_id} {task['task_type']} err={e}")


if __name__ == "__main__":
    main()
