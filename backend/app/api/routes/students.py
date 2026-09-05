from __future__ import annotations

import json
import os
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status

from app.core.auth import ROLE_STUDENT, get_current_user
from app.core.personal_access import create_personal_student

from app.core.config import settings
from app.db import sqlite as db
from app.schemas.student import StudentCreate, StudentProfile
from app.services.mbti import get_mbti_questions, score_mbti_answers
from app.services.resume_batch import import_competition_resumes_with_ai
from app.services.resume_agent import generate_ai_resume
from app.services.synthetic_students import seed_synthetic_students
from app.services.student_profile import (
    build_student_profile_from_manual,
    generate_student_profile_from_latest_resume,
    generate_student_profile_from_text,
)
from app.utils.ids import gen_id, now_iso
from app.utils.labels import enrich_student_profile_labels
from app.utils.text import normalize_text

router = APIRouter()
ALLOWED_RESUME_EXTS = {".pdf", ".docx"}
EXPERIENCE_DETAIL_FIELDS = ("internships", "projects", "awards", "open_source", "leadership", "publications")


def _is_rule_placeholder_line(line: str) -> bool:
    text = str(line or "").strip()
    if not text:
        return True
    return any(token in text for token in ["规则抽取", "自动抽取", "每行一条", "可编辑"])


def _to_text_list(value: Any, *, limit: int = 30) -> list[str]:
    if isinstance(value, str):
        values = [x.strip() for x in value.replace("\r", "\n").split("\n")]
    elif isinstance(value, list):
        values = []
        for item in value:
            if isinstance(item, dict):
                values.append(
                    str(
                        item.get("name")
                        or item.get("value")
                        or item.get("evidence")
                        or item.get("content")
                        or ""
                    ).strip()
                )
            else:
                values.append(str(item).strip())
    else:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        if not raw:
            continue
        key = raw.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(raw)
        if len(out) >= limit:
            break
    return out


def _experience_item_key(field: str, content: str, evidence: str) -> str:
    text = normalize_text(f"{content}\n{evidence}")
    text = "".join(text.lower().split())
    if field == "awards":
        for token in ("获得", "荣获", "证书", "荣誉", "奖项", "奖励", "竞赛", "比赛", "大赛"):
            text = text.replace(token, "")
    return text[:120]


def _to_experience_detail_items(value: Any, *, field: str = "", limit: int = 8) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in value:
        content = ""
        evidence = ""
        if isinstance(item, dict):
            content = normalize_text(
                str(
                    item.get("content")
                    or item.get("item")
                    or item.get("summary")
                    or item.get("title")
                    or item.get("name")
                    or ""
                )
            )
            evidence = normalize_text(
                str(item.get("evidence") or item.get("proof") or item.get("source_text") or item.get("raw") or "")
            )
        else:
            text = normalize_text(str(item or ""))
            content = text
            evidence = text
        if not content and not evidence:
            continue
        if not content:
            content = evidence[:80]
        if not evidence and field != "awards":
            evidence = content
        if _is_rule_placeholder_line(content) or (evidence and _is_rule_placeholder_line(evidence)):
            continue
        key = _experience_item_key(field, content, evidence)
        if key in seen:
            continue
        seen.add(key)
        out.append({"content": content[:180], "evidence": evidence[:300]})
        if len(out) >= limit:
            break
    return out


def _coerce_profile_hint_payload(body: dict[str, Any] | None) -> dict[str, Any]:
    body = body or {}
    payload: dict[str, Any] = {}

    for key in ("name", "mbti_type", "raw_text", "resume_text", "notes"):
        value = body.get(key)
        if value is None:
            continue
        text = normalize_text(str(value))
        if text:
            payload[key] = text

    for key in ("hard_skills", "soft_skills", "certificates"):
        values = _to_text_list(body.get(key), limit=40)
        if values:
            payload[key] = values

    details_in = body.get("experience_details") if isinstance(body.get("experience_details"), dict) else {}
    detail_items_in = body.get("experience_detail_items") if isinstance(body.get("experience_detail_items"), dict) else {}
    flat_detail_map = {
        "internships": body.get("internships_details"),
        "projects": body.get("projects_details"),
        "awards": body.get("awards_details"),
        "open_source": body.get("open_source_details"),
        "leadership": body.get("leadership_details"),
        "publications": body.get("publications_details"),
    }
    flat_detail_items_map = {
        "internships": body.get("internships_items"),
        "projects": body.get("projects_items"),
        "awards": body.get("awards_items"),
        "open_source": body.get("open_source_items"),
        "leadership": body.get("leadership_items"),
        "publications": body.get("publications_items"),
    }
    detail_items_payload: dict[str, list[dict[str, str]]] = {}
    for field in EXPERIENCE_DETAIL_FIELDS:
        values = _to_experience_detail_items(detail_items_in.get(field), field=field, limit=8) if isinstance(detail_items_in, dict) else []
        if not values:
            values = _to_experience_detail_items(flat_detail_items_map.get(field), field=field, limit=8)
        if values:
            detail_items_payload[field] = values
    if detail_items_payload:
        payload["experience_detail_items"] = detail_items_payload

    detail_payload: dict[str, list[str]] = {}
    for field in EXPERIENCE_DETAIL_FIELDS:
        values = _to_text_list(details_in.get(field), limit=8) if isinstance(details_in, dict) else []
        if not values:
            values = _to_text_list(flat_detail_map.get(field), limit=8)
        if not values and detail_items_payload.get(field):
            values = _to_text_list(
                [item.get("evidence") or item.get("content") for item in (detail_items_payload.get(field) or [])],
                limit=8,
            )
        values = [line for line in values if len(str(line).strip()) >= 4 and not _is_rule_placeholder_line(str(line))]
        if values:
            detail_payload[field] = values
    if detail_payload:
        payload["experience_details"] = detail_payload

    exp_in = body.get("experience") if isinstance(body.get("experience"), dict) else {}
    exp_payload: dict[str, int] = {}
    for field in ("internships", "projects", "awards", "publications", "open_source", "leadership"):
        raw = exp_in.get(field) if isinstance(exp_in, dict) else body.get(field)
        count = None
        try:
            if raw is not None:
                count = max(0, int(raw))
        except Exception:
            count = None
        if count is None:
            count = len(detail_items_payload.get(field) or detail_payload.get(field) or [])
        exp_payload[field] = int(count)
    payload["experience"] = exp_payload

    pref_in = body.get("preferences") if isinstance(body.get("preferences"), dict) else {}
    preferred_locations = _to_text_list(pref_in.get("preferred_locations"), limit=12) or _to_text_list(
        body.get("preferred_locations"),
        limit=12,
    )
    preferred_job_families = _to_text_list(pref_in.get("preferred_job_families"), limit=12) or _to_text_list(
        body.get("preferred_job_families"),
        limit=12,
    )
    target_salary_min = pref_in.get("target_salary_min")
    if target_salary_min is None:
        target_salary_min = body.get("target_salary_min")
    target_salary_max = pref_in.get("target_salary_max")
    if target_salary_max is None:
        target_salary_max = body.get("target_salary_max")
    notes = str(pref_in.get("notes") or body.get("notes") or "").strip()

    pref_payload: dict[str, Any] = {}
    if preferred_locations:
        pref_payload["preferred_locations"] = preferred_locations
    if preferred_job_families:
        pref_payload["preferred_job_families"] = preferred_job_families
    try:
        if target_salary_min is not None:
            pref_payload["target_salary_min"] = max(0, int(target_salary_min))
    except Exception:
        pass
    try:
        if target_salary_max is not None:
            pref_payload["target_salary_max"] = max(0, int(target_salary_max))
    except Exception:
        pass
    if notes:
        pref_payload["notes"] = notes
    if pref_payload:
        payload["preferences"] = pref_payload
    return payload


def _sanitize_hints_for_latest_resume(hints: dict[str, Any], *, merge_manual_hints: bool) -> dict[str, Any]:
    if merge_manual_hints:
        return dict(hints or {})
    safe: dict[str, Any] = {}
    hints = hints or {}
    # 从“最新简历生成画像”默认只保留低风险偏好字段，避免旧手动经历污染。
    mbti_type = normalize_text(str(hints.get("mbti_type") or ""))
    if mbti_type:
        safe["mbti_type"] = mbti_type
    preferences = hints.get("preferences")
    if isinstance(preferences, dict) and preferences:
        safe["preferences"] = dict(preferences)
    name = normalize_text(str(hints.get("name") or ""))
    if name:
        safe["name"] = name
    return safe


def _load_or_init_profile(student_id: str) -> StudentProfile:
    current = db.get_student_profile(student_id) or {}
    raw_profile = current.get("profile")
    if isinstance(raw_profile, dict):
        payload = dict(raw_profile)
        payload["student_id"] = student_id
        try:
            return StudentProfile.model_validate(payload)
        except Exception:
            pass
    return StudentProfile(student_id=student_id)


@router.get("")
def list_students(
    q: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    conn = db.get_conn()
    keyword = str(q or "").strip()
    clauses: list[str] = []
    params: list[Any] = []
    if keyword:
        like = f"%{keyword}%"
        clauses.append("(student_id LIKE ? OR COALESCE(name, '') LIKE ?)")
        params.extend([like, like])
    if user.get('role') == ROLE_STUDENT:
        clauses.append("student_id IN (SELECT student_id FROM student_owners WHERE user_id=?)")
        params.append(user['user_id'])
    where_sql = (' WHERE ' + ' AND '.join(clauses)) if clauses else ''

    total_row = conn.execute(
        f"SELECT COUNT(1) AS c FROM students{where_sql}",
        params,
    ).fetchone()
    total = int(total_row["c"]) if total_row else 0

    rows = conn.execute(
        f"SELECT student_id, name, created_at FROM students{where_sql} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (*params, limit, offset),
    ).fetchall()
    items = []
    for r in rows:
        item = dict(r)
        prof = db.get_student_profile(item["student_id"])
        if prof:
            p = prof.get("profile") or {}
            item["completeness_score"] = p.get("completeness_score")
            item["competitiveness_score"] = p.get("competitiveness_score")
        items.append(item)
    return {"items": items, "limit": limit, "offset": offset, "total": total, "q": keyword or None}


@router.post("")
def create_student(payload: StudentCreate, user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    if user.get('role') == ROLE_STUDENT:
        create_personal_student(user, payload.student_id, payload.name)
    else:
        db.upsert_student(payload.student_id, payload.name, created_at=now_iso())
    return {"ok": True, "student_id": payload.student_id}


@router.put("/{student_id}")
def update_student(student_id: str, body: dict[str, Any]) -> dict[str, Any]:
    current = db.get_student(student_id)
    if not current:
        db.upsert_student(student_id, body.get("name"), created_at=now_iso())
    else:
        db.upsert_student(student_id, body.get("name", current.get("name")), created_at=current.get("created_at") or now_iso())
    return {"ok": True, "student_id": student_id}


@router.post("/seed_synthetic")
def seed_students(body: dict[str, Any]) -> dict[str, Any]:
    count = int(body.get('count') or 30)
    overwrite_existing = bool(body.get('overwrite_existing', False))
    items = seed_synthetic_students(count=count, overwrite_existing=overwrite_existing, use_llm_expand=bool(body.get('use_llm_expand', False)))
    return {"ok": True, "count": len(items), "items": items}


@router.post("/batch/import_competition_resumes")
def batch_import_competition_resumes(body: dict[str, Any] | None = None) -> dict[str, Any]:
    body = body or {}
    return import_competition_resumes_with_ai(
        source_root=body.get("source_root"),
        student_id_prefix=str(body.get("student_id_prefix") or "STU"),
        overwrite_existing=bool(body.get("overwrite_existing", True)),
        limit=body.get("limit"),
        require_llm=bool(body.get("require_llm", False)),
    )


@router.get("/mbti/questions")
def list_mbti_questions() -> dict[str, Any]:
    items = get_mbti_questions()
    return {
        "items": items,
        "total": len(items),
        "source": "MBTI-master/MBTI-master/data/questions.json",
    }


@router.get("/{student_id}")
def get_student(student_id: str) -> dict[str, Any]:
    s = db.get_student(student_id)
    if not s:
        return {"error": "not_found"}
    prof = db.get_student_profile(student_id)
    files = db.list_student_files(student_id)
    reports = db.list_reports(student_id, limit=10)
    if prof and prof.get("profile"):
        prof = dict(prof)
        prof["profile"] = enrich_student_profile_labels(prof.get("profile"))
    return {"student": s, "profile": prof, "files": files, "reports": reports}


@router.get("/{student_id}/reports")
def student_reports(student_id: str, limit: int = 20) -> dict[str, Any]:
    return {"items": db.list_reports(student_id, limit=limit)}


@router.post("/{student_id}/resume/upload")
async def upload_resume(student_id: str, file: UploadFile = File(...)) -> dict[str, Any]:
    if not db.get_student(student_id):
        db.upsert_student(student_id, name=None, created_at=now_iso())

    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_RESUME_EXTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "unsupported_resume_format", "message": "Only pdf/docx resume files are supported"},
        )

    file_id = gen_id("FILE", 10)
    resumes_dir = os.path.join(settings.data_dir, "resumes", student_id)
    os.makedirs(resumes_dir, exist_ok=True)
    path = os.path.join(resumes_dir, f"{file_id}{ext}")
    content = await file.read()
    with open(path, "wb") as f:
        f.write(content)

    db.insert_student_file(file_id=file_id, student_id=student_id, filename=file.filename or "resume", path=path, created_at=now_iso())
    return {"ok": True, "file_id": file_id, "path": path}


@router.post("/{student_id}/resume/ai_generate")
def ai_generate_resume(student_id: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    if not db.get_student(student_id):
        db.upsert_student(student_id, (body or {}).get("name"), created_at=now_iso())
    try:
        data = generate_ai_resume(student_id, body)
    except ValueError as e:
        message = str(e)
        code = "resume_ai_generate_failed"
        if message == "student_not_found":
            code = "student_not_found"
        elif message == "resume_text_not_found":
            code = "resume_not_found"
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": code, "message": message},
        ) from e
    return {"ok": True, **data}


@router.post("/{student_id}/profile/generate_from_latest_resume")
def gen_profile(student_id: str, body: dict[str, Any] | None = None, require_llm: bool = False) -> dict[str, Any]:
    body = body or {}
    merged_hint_mode = bool(body.get("merge_manual_hints", False))
    manual_hints = _sanitize_hints_for_latest_resume(
        _coerce_profile_hint_payload(body),
        merge_manual_hints=merged_hint_mode,
    )
    try:
        prof = generate_student_profile_from_latest_resume(
            student_id,
            require_llm=require_llm,
            manual_payload=manual_hints,
        )
    except ValueError as e:
        message = str(e)
        if "Unsupported resume format" in message:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "unsupported_resume_format", "message": message},
            ) from e
        if "No resume file uploaded" in message:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "resume_not_found", "message": message},
            ) from e
        if "extraction failed" in message:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "resume_extract_failed", "message": message},
            ) from e
        if "llm_profile_extract_failed_or_disabled" in message:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "llm_required_failed", "message": message},
            ) from e
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "profile_generate_failed", "message": message},
        ) from e
    data = enrich_student_profile_labels(prof.model_dump())
    return {"ok": True, "profile": data}


@router.post("/{student_id}/profile/generate_from_text")
def gen_profile_from_text_route(student_id: str, body: dict[str, Any]) -> dict[str, Any]:
    if not db.get_student(student_id):
        db.upsert_student(student_id, body.get("name"), created_at=now_iso())
    text = normalize_text(body.get("text") or "")
    prof = generate_student_profile_from_text(
        student_id,
        text,
        manual_payload=_coerce_profile_hint_payload(body),
    )
    data = enrich_student_profile_labels(prof.model_dump())
    return {"ok": True, "profile": data}


@router.post("/{student_id}/profile/manual")
def save_manual_profile(student_id: str, body: dict[str, Any]) -> dict[str, Any]:
    if not db.get_student(student_id):
        db.upsert_student(student_id, body.get("name"), created_at=now_iso())
    elif body.get("name"):
        current = db.get_student(student_id)
        db.upsert_student(student_id, body.get("name"), created_at=(current or {}).get("created_at") or now_iso())

    profile = build_student_profile_from_manual(student_id, body)
    data = enrich_student_profile_labels(profile.model_dump())
    return {"ok": True, "profile": data}


@router.post("/{student_id}/mbti/submit")
def submit_mbti_answers(student_id: str, body: dict[str, Any]) -> dict[str, Any]:
    answers_raw = body.get("answers")
    if not isinstance(answers_raw, list):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "mbti_answers_required", "message": "answers must be an array"},
        )

    questions = get_mbti_questions()
    if not questions:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "mbti_question_bank_unavailable", "message": "MBTI question bank is unavailable"},
        )

    if len(answers_raw) != len(questions):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "mbti_answer_count_mismatch",
                "message": f"Expect {len(questions)} answers, got {len(answers_raw)}",
            },
        )

    normalized_answers: list[str] = []
    for idx, (raw_answer, question) in enumerate(zip(answers_raw, questions), start=1):
        answer = str(raw_answer or "").strip().upper()
        expected = {
            str((question.get("choice_a") or {}).get("value") or "").strip().upper(),
            str((question.get("choice_b") or {}).get("value") or "").strip().upper(),
        }
        if answer not in expected:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "mbti_answer_invalid",
                    "message": f"Question {idx} answer is invalid",
                },
            )
        normalized_answers.append(answer)

    try:
        score = score_mbti_answers(normalized_answers)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "mbti_score_failed", "message": str(e)},
        ) from e

    if not db.get_student(student_id):
        db.upsert_student(student_id, body.get("name"), created_at=now_iso())
    elif body.get("name"):
        current = db.get_student(student_id)
        db.upsert_student(student_id, body.get("name"), created_at=(current or {}).get("created_at") or now_iso())

    profile = _load_or_init_profile(student_id)
    profile.mbti_type = str(score.get("mbti_type") or "").strip().upper() or None
    profile.mbti_source = "questionnaire" if profile.mbti_type else None
    meta = profile.extraction_meta if isinstance(profile.extraction_meta, dict) else {}
    meta = dict(meta)
    meta["mbti_source"] = profile.mbti_source
    meta["mbti_questionnaire"] = {
        "question_count": len(questions),
        "answered_count": len(normalized_answers),
        "answer_counts": score.get("answer_counts") or {},
        "dimension_scores": score.get("dimension_scores") or [],
    }
    profile.extraction_meta = meta

    updated_at = now_iso()
    db.upsert_student_profile(
        student_id,
        profile_json=json.dumps(profile.model_dump(), ensure_ascii=False),
        updated_at=updated_at,
    )
    data = enrich_student_profile_labels(profile.model_dump())
    return {
        "ok": True,
        "mbti_type": profile.mbti_type,
        "mbti_source": profile.mbti_source,
        "answered_count": len(normalized_answers),
        "question_count": len(questions),
        "dimension_scores": score.get("dimension_scores") or [],
        "profile": data,
    }
