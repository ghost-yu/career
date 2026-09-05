from __future__ import annotations

import json
import os
from typing import Any

from fastapi import APIRouter, File, Query, UploadFile

from app.core.config import settings
from app.db import sqlite as db
from app.schemas.job import BasicRequirements, CertificateMention, JobIn, JobProfile, SkillMention, SoftSkillMention
from app.schemas.task import TaskCreate
from app.services.job_profile import generate_job_profile
from app.services.retrieval import build_job_index
from app.utils.ids import gen_id, now_iso
from app.utils.ingest import coerce_sheet_name
from app.utils.labels import enrich_job_labels

router = APIRouter()


def _coerce_hard_skills(raw_items: Any) -> list[SkillMention]:
    out: list[SkillMention] = []
    for item in raw_items if isinstance(raw_items, list) else []:
        if isinstance(item, str):
            name = str(item).strip()
            if name:
                out.append(SkillMention(mention=name, importance="must_low"))
            continue
        if not isinstance(item, dict):
            continue
        mention = str(item.get("mention") or item.get("name") or item.get("skill") or "").strip()
        if not mention:
            continue
        importance = str(item.get("importance") or "must_low").strip().lower()
        if importance not in {"must", "plus", "must_low"}:
            importance = "must_low"
        out.append(
            SkillMention(
                skill_id=str(item.get("skill_id") or "").strip() or None,
                mention=mention,
                importance=importance,  # type: ignore[arg-type]
                level=str(item.get("level") or "").strip() or None,
                evidence=str(item.get("evidence") or "").strip() or None,
                source_section=str(item.get("source_section") or "").strip() or None,
            )
        )
    return out


def _coerce_soft_skills(raw_items: Any) -> list[SoftSkillMention]:
    out: list[SoftSkillMention] = []
    for item in raw_items if isinstance(raw_items, list) else []:
        if isinstance(item, str):
            name = str(item).strip()
            if name:
                out.append(SoftSkillMention(name=name, importance="must_low"))
            continue
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("mention") or "").strip()
        if not name:
            continue
        importance = str(item.get("importance") or "must_low").strip().lower()
        if importance not in {"must", "plus", "must_low"}:
            importance = "must_low"
        out.append(
            SoftSkillMention(
                soft_skill_id=str(item.get("soft_skill_id") or "").strip() or None,
                name=name,
                importance=importance,  # type: ignore[arg-type]
                evidence=str(item.get("evidence") or "").strip() or None,
                source_section=str(item.get("source_section") or "").strip() or None,
            )
        )
    return out


def _coerce_certificates(raw_items: Any) -> list[CertificateMention]:
    out: list[CertificateMention] = []
    for item in raw_items if isinstance(raw_items, list) else []:
        if isinstance(item, str):
            name = str(item).strip()
            if name:
                out.append(CertificateMention(name=name, importance="plus"))
            continue
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("mention") or "").strip()
        if not name:
            continue
        importance = str(item.get("importance") or "plus").strip().lower()
        if importance not in {"must", "plus", "must_low"}:
            importance = "plus"
        out.append(
            CertificateMention(
                certificate_id=str(item.get("certificate_id") or "").strip() or None,
                name=name,
                importance=importance,  # type: ignore[arg-type]
                evidence=str(item.get("evidence") or "").strip() or None,
                source_section=str(item.get("source_section") or "").strip() or None,
            )
        )
    return out


def _coerce_basic_requirements(raw: Any) -> BasicRequirements:
    basic = raw if isinstance(raw, dict) else {}
    location = basic.get("location")
    location_list = [str(x).strip() for x in location] if isinstance(location, list) else ([str(location).strip()] if location else [])
    experience_years_min = basic.get("experience_years_min")
    if experience_years_min is None:
        experience_years_min = basic.get("experience")
    try:
        exp = int(experience_years_min) if experience_years_min is not None else None
    except Exception:
        exp = None
    return BasicRequirements(
        education=str(basic.get("education") or "").strip() or None,
        major=[str(x).strip() for x in (basic.get("major") or []) if str(x).strip()] if isinstance(basic.get("major"), list) else [],
        experience_years_min=exp,
        location=[x for x in location_list if x],
    )


@router.post("/ingest")
def ingest_jobs(jobs: list[JobIn], auto_generate_profile: bool = Query(default=True)) -> dict[str, Any]:
    """Direct ingest (sync) for small batches."""
    generated = 0
    failed: list[dict[str, str]] = []
    for j in jobs:
        db.insert_job(
            {
                "job_id": j.job_id,
                "title": j.title,
                "location": j.location,
                "salary_min": j.salary_min,
                "salary_max": j.salary_max,
                "salary_period": j.salary_period,
                "company_name": j.company_name,
                "industry": j.industry,
                "company_size": j.company_size,
                "company_type": j.company_type,
                "job_code": j.job_code,
                "description": j.description,
                "company_intro": j.company_intro,
                "updated_date": j.updated_date,
                "source_url": j.source_url,
                "raw_json": json.dumps(j.raw or {}, ensure_ascii=False),
            }
        )
        if auto_generate_profile:
            try:
                generate_job_profile(j.job_id)
                generated += 1
            except Exception as exc:
                failed.append({"job_id": j.job_id, "error": str(exc)})
    return {
        "ok": True,
        "count": len(jobs),
        "profile_generated": generated,
        "profile_failed": failed,
    }


@router.post("/ingest_file")
async def ingest_jobs_file(
    file: UploadFile = File(...),
    encoding: str = "utf-8",
    sheet_name: str | int | None = 0,
    computer_only: bool = True,
    auto_generate_profiles: bool = True,
    profile_only_missing: bool = True,
    profile_workers: int = Query(default=4, ge=1, le=16),
) -> dict[str, Any]:
    """Upload a CSV/JSON file then create an async ingest task.

    Why async?
    ---------
    10k rows ingestion is better handled as a background task with progress.
    Run the worker: `python -m app.worker` or `docker compose up worker`.
    """

    os.makedirs(settings.upload_dir, exist_ok=True)
    ext = os.path.splitext(file.filename or "")[1].lower() or ".csv"
    upload_id = gen_id("UP", 10)
    path = os.path.join(settings.upload_dir, f"{upload_id}{ext}")
    content = await file.read()
    with open(path, "wb") as f:
        f.write(content)

    # create ingest task
    task_id = gen_id("TASK", 12)
    task = {
        "task_id": task_id,
        "task_type": "INGEST_JOBS_FILE",
        "payload_json": json.dumps(
            {
                "path": path,
                "encoding": encoding,
                "filename": file.filename,
                "sheet_name": coerce_sheet_name(sheet_name),
                "computer_only": computer_only,
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
    db.create_task(task)

    profile_task_id: str | None = None
    if auto_generate_profiles:
        profile_task_id = gen_id("TASK", 12)
        db.create_task(
            {
                "task_id": profile_task_id,
                "task_type": "BULK_GENERATE_JOB_PROFILES",
                "payload_json": json.dumps({"only_missing": profile_only_missing, "limit": None, "workers": profile_workers}, ensure_ascii=False),
                "status": "PENDING",
                "progress": 0.0,
                "result_json": None,
                "error": None,
                "created_at": now_iso(),
                "updated_at": now_iso(),
            }
        )

    return {
        "ok": True,
        "task_id": task_id,
        "profile_task_id": profile_task_id,
        "path": path,
    }


@router.get("")
def list_jobs(q: str | None = None, location: str | None = None, limit: int = 50, offset: int = 0) -> dict[str, Any]:
    rows = [enrich_job_labels(r) for r in db.list_jobs(q=q, location=location, limit=limit, offset=offset)]
    return {"items": rows, "limit": limit, "offset": offset}


@router.get("/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    job = db.get_job(job_id)
    if not job:
        return {"error": "not_found"}
    prof = db.get_job_profile(job_id)
    if prof and isinstance(prof.get("profile"), dict):
        prof = {**prof, "profile": {**prof.get("profile", {}), "job_family_label": __import__("app.utils.labels", fromlist=["job_family_label"]).job_family_label((prof.get("profile") or {}).get("job_family"))}}
    return {"job": enrich_job_labels(job), "profile": prof}


@router.post("/{job_id}/profile/generate")
def gen_job_profile(job_id: str) -> dict[str, Any]:
    profile = generate_job_profile(job_id)
    return {"ok": True, "profile": profile.model_dump()}


@router.post("/profiles/bulk_generate")
def bulk_generate_profiles(
    only_missing: bool = True,
    limit: int | None = None,
    workers: int = Query(default=4, ge=1, le=16),
) -> dict[str, Any]:
    """Create a background task to generate job profiles for many postings."""

    task_id = gen_id("TASK", 12)
    task = {
        "task_id": task_id,
        "task_type": "BULK_GENERATE_JOB_PROFILES",
        "payload_json": json.dumps({"only_missing": only_missing, "limit": limit, "workers": workers}, ensure_ascii=False),
        "status": "PENDING",
        "progress": 0.0,
        "result_json": None,
        "error": None,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    db.create_task(task)
    return {"ok": True, "task_id": task_id}


@router.post("/profiles/import_ai")
def import_ai_profiles(body: dict[str, Any]) -> dict[str, Any]:
    rows = body.get("items") if isinstance(body.get("items"), list) else body.get("rows")
    if not isinstance(rows, list):
        return {"error": "items(list) required"}

    imported = 0
    failed: list[dict[str, Any]] = []
    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            failed.append({"index": idx, "error": "row_not_object"})
            continue
        profile_raw = row.get("profile") if isinstance(row.get("profile"), dict) else row
        job_id = str(
            row.get("job_id")
            or profile_raw.get("job_id")
            or row.get("id")
            or profile_raw.get("id")
            or ""
        ).strip()
        if not job_id:
            failed.append({"index": idx, "error": "missing_job_id"})
            continue
        if not db.get_job(job_id):
            failed.append({"index": idx, "job_id": job_id, "error": "job_not_found"})
            continue
        try:
            profile = JobProfile(
                job_id=job_id,
                hard_skills=_coerce_hard_skills(profile_raw.get("hard_skills")),
                soft_skills=_coerce_soft_skills(profile_raw.get("soft_skills")),
                certificates=_coerce_certificates(profile_raw.get("certificates")),
                basic_requirements=_coerce_basic_requirements(profile_raw.get("basic_requirements")),
                tags=[str(x).strip() for x in (profile_raw.get("tags") or []) if str(x).strip()] if isinstance(profile_raw.get("tags"), list) else [],
                job_family=str(profile_raw.get("job_family") or "").strip() or None,
            )
            db.upsert_job_profile(job_id, profile_json=json.dumps(profile.model_dump(), ensure_ascii=False), updated_at=now_iso())
            imported += 1
        except Exception as e:
            failed.append({"index": idx, "job_id": job_id, "error": str(e)})

    return {
        "ok": True,
        "total": len(rows),
        "imported": imported,
        "failed_count": len(failed),
        "failed": failed[:100],
    }


@router.post("/index/build")
def build_index(limit: int = 5000) -> dict[str, Any]:
    return build_job_index(limit=limit)


@router.post("/pipeline/full_rebuild")
def full_rebuild(limit: int | None = None, profile_workers: int = Query(default=4, ge=1, le=16)) -> dict[str, Any]:
    """Create a *sequence* of tasks for a full pipeline rebuild.

    Order matters; the worker will process tasks in created_at order.

    Pipeline steps:
      1) generate job profiles
      2) rebuild role catalog + role graph + role index
      3) build job retrieval index
      4) rebuild job-level graph

    Note: this is a minimal substitute for Celery/LangGraph orchestration.
    """

    task_ids = []

    def _new(task_type: str, payload: dict[str, Any]) -> str:
        tid = gen_id("TASK", 12)
        db.create_task(
            {
                "task_id": tid,
                "task_type": task_type,
                "payload_json": json.dumps(payload, ensure_ascii=False),
                "status": "PENDING",
                "progress": 0.0,
                "result_json": None,
                "error": None,
                "created_at": now_iso(),
                "updated_at": now_iso(),
            }
        )
        return tid

    task_ids.append(_new("BULK_GENERATE_JOB_PROFILES", {"only_missing": True, "limit": limit, "workers": profile_workers}))
    task_ids.append(_new("REBUILD_ROLES_AND_ROLE_GRAPH", {"clear_existing": True, "limit": limit, "build_index": True}))
    task_ids.append(_new("BUILD_JOB_INDEX", {"limit": limit or 10000}))
    task_ids.append(_new("REBUILD_JOB_GRAPH", {"limit": limit}))
    task_ids.append(_new("MATERIALIZE_KB_FROM_DB", {"max_roles": 300, "max_jobs_per_role": 3, "clear_generated": True, "rebuild_index": True}))
    task_ids.append(_new("REBUILD_KB_INDEX", {}))

    return {"ok": True, "task_ids": task_ids}
