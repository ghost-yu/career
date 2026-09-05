from __future__ import annotations

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.core.config import settings
from app.db import sqlite as db
from app.services.evaluation import (
    PROFILE_CSV_FIELDS,
    SKILL_CSV_FIELDS,
    compute_profile_accuracy,
    compute_skill_match_accuracy,
    export_profile_label_rows,
    export_skill_match_label_rows,
    read_csv_rows_from_bytes,
    read_csv_rows_from_path,
    split_csv_arg,
    write_csv,
)
from app.services.job_profile import generate_job_profile
from app.services.scoring import score
from app.services.student_profile import generate_student_profile_from_latest_resume
from app.utils.ids import gen_id, now_iso
from app.utils.ingest import coerce_sheet_name, map_row, read_excel_any

router = APIRouter()

_JOB_FILTER_KEYWORDS = [
    "计算机", "软件", "互联网", "信息化", "it", "ai", "人工智能", "算法", "数据", "大数据", "云", "网络", "安全",
    "前端", "后端", "全栈", "测试", "运维", "开发", "编程", "数据库", "机器学习", "深度学习", "java", "python",
    "golang", "c++", "c#", "node", "react", "vue", "android", "ios", "devops", "k8s", "docker",
]


def _default_eval_dir() -> Path:
    p = Path(settings.data_dir) / "eval"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _coerce_id_list(value: Any) -> list[str]:
    if isinstance(value, list):
        raw = value
    else:
        raw = split_csv_arg(value)
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        text = str(item or "").strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def _run_concurrent(items: list[Any], workers: int, fn) -> dict[str, Any]:
    total = len(items)
    ok = 0
    failed = 0
    skipped = 0
    samples: list[dict[str, Any]] = []
    if not items:
        return {"total": 0, "ok": 0, "failed": 0, "skipped": 0, "samples": []}

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="eval-batch") as executor:
        futures = {executor.submit(fn, item): item for item in items}
        for fut in as_completed(futures):
            item = futures[fut]
            try:
                result = fut.result()
            except Exception as exc:
                result = {"ok": False, "item": item, "error": str(exc)}
            if result.get("skipped"):
                skipped += 1
            elif result.get("ok"):
                ok += 1
            else:
                failed += 1
            if len(samples) < 20:
                samples.append(result)
    return {"total": total, "ok": ok, "failed": failed, "skipped": skipped, "samples": samples}


def _safe_stem(filename: str, fallback: str) -> str:
    stem = Path(filename or "").stem.strip() or fallback
    stem = re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", stem, flags=re.UNICODE).strip("._")
    return stem[:80] or fallback


def _is_relevant_job(mapped: dict[str, Any]) -> bool:
    text = " ".join(
        str(mapped.get(k) or "")
        for k in ("title", "description", "industry", "company_intro", "job_code")
    ).lower()
    if not text.strip():
        return False
    return any(keyword in text for keyword in _JOB_FILTER_KEYWORDS)


@router.post("/eval/import_student_resumes")
async def import_student_resumes(
    files: list[UploadFile] = File(...),
    student_id_prefix: str = Form("STU"),
    overwrite_existing: bool = Form(True),
    require_llm: bool = Form(False),
    workers: int = Form(8),
) -> dict[str, Any]:
    workers = max(1, min(32, int(workers or 8)))
    prefix = re.sub(r"[^A-Za-z0-9_]", "", str(student_id_prefix or "STU")) or "STU"
    saved: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for idx, file in enumerate(files or [], start=1):
        filename = file.filename or f"resume_{idx}.docx"
        ext = os.path.splitext(filename)[1].lower()
        if ext not in {".docx", ".pdf"}:
            skipped.append({"filename": filename, "reason": "unsupported_resume_format"})
            continue
        student_id = f"{prefix}{idx:03d}"
        if (not overwrite_existing) and db.get_student_profile(student_id):
            skipped.append({"filename": filename, "student_id": student_id, "reason": "profile_exists"})
            continue
        student_name = _safe_stem(filename, f"学生{idx:03d}")
        resumes_dir = Path(settings.data_dir) / "resumes" / student_id
        resumes_dir.mkdir(parents=True, exist_ok=True)
        file_id = gen_id("FILE", 10)
        path = resumes_dir / f"{file_id}{ext}"
        content = await file.read()
        path.write_bytes(content)
        db.upsert_student(student_id, student_name, created_at=now_iso())
        db.insert_student_file(file_id, student_id, filename, str(path), created_at=now_iso())
        saved.append({"student_id": student_id, "student_name": student_name, "filename": filename, "path": str(path)})

    def _profile_task(item: dict[str, Any]) -> dict[str, Any]:
        student_id = str(item["student_id"])
        profile = generate_student_profile_from_latest_resume(student_id, require_llm=require_llm)
        return {
            "ok": True,
            "student_id": student_id,
            "filename": item.get("filename"),
            "hard_skills": len(profile.hard_skills or []),
            "soft_skills": len(profile.soft_skills or []),
            "certificates": len(profile.certificates or []),
        }

    profile_summary = _run_concurrent(saved, workers, _profile_task)
    return {
        "ok": True,
        "uploaded": len(saved),
        "skipped_uploads": skipped,
        "student_ids": [x["student_id"] for x in saved],
        "workers": workers,
        "profiles": profile_summary,
    }


@router.post("/eval/import_jobs_excel")
async def import_jobs_excel(
    file: UploadFile = File(...),
    sheet_name: str = Form("0"),
    computer_only: bool = Form(True),
    auto_generate_profiles: bool = Form(True),
    only_missing: bool = Form(True),
    workers: int = Form(12),
) -> dict[str, Any]:
    workers = max(1, min(32, int(workers or 12)))
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in {".xlsx", ".xls"}:
        raise HTTPException(status_code=400, detail="excel_file_required")

    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    upload_path = upload_dir / f"{gen_id('UP', 10)}{ext}"
    upload_path.write_bytes(await file.read())

    df = read_excel_any(str(upload_path), sheet_name=coerce_sheet_name(sheet_name))
    job_ids: list[str] = []
    skipped_empty = 0
    skipped_non_computer = 0

    for idx, row in enumerate(df.to_dict(orient="records"), start=1):
        mapped = map_row(row)
        if not mapped.get("title") and not mapped.get("description"):
            skipped_empty += 1
            continue
        if computer_only and not _is_relevant_job(mapped):
            skipped_non_computer += 1
            continue
        job_id = str(mapped.get("job_id") or "").strip()
        if not job_id:
            job_code = str(mapped.get("job_code") or "").strip()
            job_id = f"{job_code}_{idx}" if job_code else gen_id("J", 10)
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
        job_ids.append(job_id)

    profile_summary = {"total": 0, "ok": 0, "failed": 0, "skipped": 0, "samples": []}
    if auto_generate_profiles:
        def _job_profile_task(job_id: str) -> dict[str, Any]:
            if only_missing and db.get_job_profile(job_id):
                return {"ok": True, "skipped": True, "job_id": job_id, "reason": "profile_exists"}
            profile = generate_job_profile(job_id)
            return {
                "ok": True,
                "job_id": job_id,
                "hard_skills": len(profile.hard_skills or []),
                "soft_skills": len(profile.soft_skills or []),
                "certificates": len(profile.certificates or []),
            }

        profile_summary = _run_concurrent(job_ids, workers, _job_profile_task)

    return {
        "ok": True,
        "filename": file.filename,
        "path": str(upload_path),
        "detected_total": int(len(df.index)),
        "inserted": len(job_ids),
        "skipped_empty": skipped_empty,
        "skipped_non_computer": skipped_non_computer,
        "job_ids": job_ids,
        "workers": workers,
        "profiles": profile_summary,
    }


@router.post("/eval/batch_run")
def batch_run_eval_pipeline(body: dict[str, Any] | None = None) -> dict[str, Any]:
    body = body or {}
    student_ids = _coerce_id_list(body.get("student_ids") or body.get("students"))
    job_ids = _coerce_id_list(body.get("job_ids") or body.get("jobs"))
    workers = max(1, min(32, int(body.get("workers") or 12)))
    only_missing = bool(body.get("only_missing", True))
    run_job_profiles = bool(body.get("run_job_profiles", True))
    run_student_profiles = bool(body.get("run_student_profiles", True))
    run_matches = bool(body.get("run_matches", True))
    use_cache = bool(body.get("use_cache", False))
    use_semantic_review = bool(body.get("use_semantic_review", False))

    if not student_ids and (run_student_profiles or run_matches):
        raise HTTPException(status_code=400, detail="student_ids_required")
    if not job_ids and (run_job_profiles or run_matches):
        raise HTTPException(status_code=400, detail="job_ids_required")

    started_at = datetime.now().isoformat(timespec="seconds")
    summary: dict[str, Any] = {
        "ok": True,
        "started_at": started_at,
        "workers": workers,
        "student_count": len(student_ids),
        "job_count": len(job_ids),
        "pair_count": len(student_ids) * len(job_ids),
        "options": {
            "only_missing": only_missing,
            "run_job_profiles": run_job_profiles,
            "run_student_profiles": run_student_profiles,
            "run_matches": run_matches,
            "use_cache": use_cache,
            "use_semantic_review": use_semantic_review,
        },
    }

    if run_job_profiles:
        def _job_task(job_id: str) -> dict[str, Any]:
            if only_missing and db.get_job_profile(job_id):
                return {"ok": True, "skipped": True, "job_id": job_id, "reason": "profile_exists"}
            if not db.get_job(job_id):
                return {"ok": False, "job_id": job_id, "error": "job_not_found"}
            profile = generate_job_profile(job_id)
            return {
                "ok": True,
                "job_id": job_id,
                "hard_skills": len(profile.hard_skills or []),
                "soft_skills": len(profile.soft_skills or []),
                "certificates": len(profile.certificates or []),
            }

        summary["job_profiles"] = _run_concurrent(job_ids, workers, _job_task)

    if run_student_profiles:
        def _student_task(student_id: str) -> dict[str, Any]:
            if only_missing and db.get_student_profile(student_id):
                return {"ok": True, "skipped": True, "student_id": student_id, "reason": "profile_exists"}
            if not db.get_student(student_id):
                return {"ok": False, "student_id": student_id, "error": "student_not_found"}
            profile = generate_student_profile_from_latest_resume(student_id)
            return {
                "ok": True,
                "student_id": student_id,
                "hard_skills": len(profile.hard_skills or []),
                "soft_skills": len(profile.soft_skills or []),
                "certificates": len(profile.certificates or []),
            }

        summary["student_profiles"] = _run_concurrent(student_ids, workers, _student_task)

    if run_matches:
        pairs = [(student_id, job_id) for student_id in student_ids for job_id in job_ids]

        def _match_task(pair: tuple[str, str]) -> dict[str, Any]:
            student_id, job_id = pair
            if only_missing and db.get_match_cache(student_id, job_id):
                return {
                    "ok": True,
                    "skipped": True,
                    "student_id": student_id,
                    "job_id": job_id,
                    "reason": "match_cache_exists",
                }
            result = score(
                student_id,
                job_id,
                use_cache=use_cache,
                use_semantic_review=use_semantic_review,
            ).model_dump()
            dimensions = result.get("dimension_scores") or {}
            return {
                "ok": True,
                "student_id": student_id,
                "job_id": job_id,
                "overall_score": result.get("overall_score"),
                "basic": (dimensions.get("basic") or {}).get("score"),
                "skills": (dimensions.get("skills") or {}).get("score"),
                "qualities": (dimensions.get("qualities") or {}).get("score"),
                "potential": (dimensions.get("potential") or {}).get("score"),
            }

        summary["matches"] = _run_concurrent(pairs, workers, _match_task)

    summary["finished_at"] = datetime.now().isoformat(timespec="seconds")
    summary["json_preview"] = json.dumps(
        {
            "job_profiles": summary.get("job_profiles", {}),
            "student_profiles": summary.get("student_profiles", {}),
            "matches": summary.get("matches", {}),
        },
        ensure_ascii=False,
    )[:2000]
    return summary


@router.post("/eval/skill_match/export")
def export_skill_match_labels(body: dict[str, Any] | None = None) -> dict[str, Any]:
    body = body or {}
    students = split_csv_arg(body.get("students"))
    jobs = split_csv_arg(body.get("jobs"))

    rows, pair_count = export_skill_match_label_rows(students=students, jobs=jobs)

    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    out_name = str(body.get("out_name") or f"skill_match_labels_{ts}.csv").strip() or f"skill_match_labels_{ts}.csv"
    out_path = (_default_eval_dir() / out_name).resolve()
    write_csv(out_path, SKILL_CSV_FIELDS, rows)

    return {
        "ok": True,
        "pair_count": pair_count,
        "row_count": len(rows),
        "out_csv": str(out_path),
        "sample_rows": rows[:10],
    }


@router.post("/eval/profile/export")
def export_profile_labels(body: dict[str, Any] | None = None) -> dict[str, Any]:
    body = body or {}
    students = split_csv_arg(body.get("students"))
    jobs = split_csv_arg(body.get("jobs"))
    random_jobs = max(0, int(body.get("random_jobs") or 0))
    random_students = max(0, int(body.get("random_students") or 0))
    seed = int(body.get("seed") or 42)

    rows, sampled_jobs, sampled_students = export_profile_label_rows(
        random_jobs=random_jobs,
        random_students=random_students,
        seed=seed,
        jobs=jobs,
        students=students,
    )

    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    out_name = str(body.get("out_name") or f"profile_labels_{ts}.csv").strip() or f"profile_labels_{ts}.csv"
    out_path = (_default_eval_dir() / out_name).resolve()
    write_csv(out_path, PROFILE_CSV_FIELDS, rows)

    return {
        "ok": True,
        "job_sample": sampled_jobs,
        "student_sample": sampled_students,
        "job_filter_count": len(jobs),
        "student_filter_count": len(students),
        "row_count": len(rows),
        "out_csv": str(out_path),
        "sample_rows": rows[:10],
    }


@router.post("/eval/skill_match/compute")
async def compute_skill_match_from_upload(file: UploadFile = File(...)) -> dict[str, Any]:
    data = await file.read()
    rows = read_csv_rows_from_bytes(data)
    result = compute_skill_match_accuracy(rows)
    result["source"] = {"type": "upload", "filename": file.filename}
    return result


@router.post("/eval/profile/compute")
async def compute_profile_from_upload(file: UploadFile = File(...)) -> dict[str, Any]:
    data = await file.read()
    rows = read_csv_rows_from_bytes(data)
    result = compute_profile_accuracy(rows)
    result["source"] = {"type": "upload", "filename": file.filename}
    return result


@router.post("/eval/skill_match/compute_from_path")
def compute_skill_match_from_path(body: dict[str, Any]) -> dict[str, Any]:
    path = str(body.get("csv_path") or "").strip()
    if not path:
        raise HTTPException(status_code=400, detail="csv_path_required")
    rows = read_csv_rows_from_path(path)
    result = compute_skill_match_accuracy(rows)
    result["source"] = {"type": "path", "csv_path": str(Path(path).expanduser().resolve())}
    return result


@router.post("/eval/profile/compute_from_path")
def compute_profile_from_path(body: dict[str, Any]) -> dict[str, Any]:
    path = str(body.get("csv_path") or "").strip()
    if not path:
        raise HTTPException(status_code=400, detail="csv_path_required")
    rows = read_csv_rows_from_path(path)
    result = compute_profile_accuracy(rows)
    result["source"] = {"type": "path", "csv_path": str(Path(path).expanduser().resolve())}
    return result
