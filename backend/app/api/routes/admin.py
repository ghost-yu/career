from __future__ import annotations

import json
from collections import defaultdict, deque
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile

from app.core.auth import get_current_user, hash_password
from app.core.config import settings
from app.db import sqlite as db
from app.schemas.dictionary import BulkUpsertRequest
from app.schemas.task import TaskCreate
from app.services.insights import build_competition_readiness
from app.services.job_profile import generate_job_profile
from app.services.llm import llm_client
from app.services.llm_runtime import list_provider_presets, runtime_llm_status, save_runtime_llm_config
from app.utils.ids import gen_id, now_iso
from app.utils.ingest import coerce_sheet_name, preview_excel

router = APIRouter()

VALID_STRATEGIES = {"balanced", "skill_first", "location_first", "salary_first"}


def _safe_load_json(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        v = json.loads(value)
        return v if isinstance(v, dict) else {}
    except Exception:
        return {}



def _read_json_log_tail(path: str, limit: int = 20) -> list[dict[str, Any]]:
    file_path = Path(path)
    if not file_path.exists():
        return []
    rows: deque[str] = deque(maxlen=max(1, int(limit)))
    with file_path.open('r', encoding='utf-8', errors='ignore') as fh:
        for line in fh:
            raw = line.strip()
            if raw:
                rows.append(raw)
    items: list[dict[str, Any]] = []
    for raw in reversed(list(rows)):
        try:
            parsed = json.loads(raw)
            items.append(parsed if isinstance(parsed, dict) else {'message': raw})
        except Exception:
            items.append({'message': raw})
    return items

def _extract_strategy(meta: dict[str, Any]) -> str:
    s = str(meta.get("strategy") or "").strip().lower()
    return s if s in VALID_STRATEGIES else "unspecified"


def _enqueue_task(task_type: str, payload: dict[str, Any]) -> str:
    task_id = gen_id("TASK", 12)
    db.create_task(
        {
            "task_id": task_id,
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
    return task_id


@router.get("/summary")
def summary() -> dict[str, Any]:
    task_counts = db.task_status_counts()
    recent_tasks = db.list_tasks(limit=8, offset=0)
    recent_jobs = db.list_jobs(limit=6, offset=0)
    recent_roles = db.list_roles(limit=6, offset=0)
    readiness = build_competition_readiness()
    return {
        "counts": {
            "jobs": db.count_jobs(),
            "job_profiles": db.count_job_profiles(),
            "roles": db.count_roles(),
            "role_members": db.count_role_members(),
            "students": db.count_students(),
            "student_profiles": db.count_student_profiles(),
            "student_events": db.count_student_events(),
            "reports": db.count_reports(),
        },
        "tasks": task_counts,
        "recent_tasks": recent_tasks,
        "recent_jobs": recent_jobs,
        "recent_roles": recent_roles,
        "readiness": readiness,
        "llm": runtime_llm_status(mask_secret=True),
    }


@router.get("/llm/providers")
def llm_providers() -> dict[str, Any]:
    return {"items": list_provider_presets()}


@router.get("/llm/config")
def get_llm_config() -> dict[str, Any]:
    return runtime_llm_status(mask_secret=True)


@router.post("/llm/config")
def set_llm_config(body: dict[str, Any]) -> dict[str, Any]:
    cfg = save_runtime_llm_config(body)
    return {"ok": True, **runtime_llm_status(mask_secret=True), "saved_provider": cfg.get("provider")}


@router.post("/llm/test")
def test_llm_connection() -> dict[str, Any]:
    return llm_client.test_connection_sync()


@router.post("/llm/chat_debug")
def llm_chat_debug(body: dict[str, Any]) -> dict[str, Any]:
    system = str(body.get("system") or "You are a concise assistant.").strip() or "You are a concise assistant."
    user_message = str(body.get("message") or "").strip() or "1+1 = ?"
    json_mode = bool(body.get("json_mode", False))
    try:
        if json_mode:
            data = llm_client.chat_json_sync(
                system,
                user_message,
                trace_context="admin.llm.chat_debug.json",
            )
            return {
                "ok": True,
                "json_mode": True,
                "provider": llm_client.runtime_config().get("provider"),
                "model": llm_client.runtime_config().get("model"),
                "result": data,
            }
        resp = llm_client.chat_sync(
            system,
            user_message,
            trace_context="admin.llm.chat_debug.text",
        )
        return {
            "ok": True,
            "json_mode": False,
            "provider": llm_client.runtime_config().get("provider"),
            "model": llm_client.runtime_config().get("model"),
            "result": resp.text,
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail={"code": "llm_chat_debug_failed", "message": str(exc)}) from exc


@router.post("/llm/chain_verify")
async def verify_ai_chain(request: Request, body: dict[str, Any], user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    llm_result = llm_client.test_connection_sync()

    student_id = str(body.get("student_id") or "").strip()
    if not student_id:
        rows = db.get_conn().execute("SELECT student_id FROM students ORDER BY created_at DESC LIMIT 1").fetchall()
        student_id = str(rows[0]["student_id"]) if rows else "S001"
    if not db.get_student(student_id):
        db.upsert_student(student_id, name="AI Chain Verify", created_at=now_iso())

    message = str(body.get("message") or "请推荐一个适合我的职业方向").strip() or "请推荐一个适合我的职业方向"
    chat_payload = {"student_id": student_id, "message": message}
    cookie = request.cookies.get(settings.auth_cookie_name)

    call_ok = False
    status_code = 0
    agent_result: dict[str, Any] = {}
    call_error: str | None = None

    try:
        transport = httpx.ASGITransport(app=request.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://internal.local") as client:
            resp = await client.post(
                "/chat/agent",
                json=chat_payload,
                cookies={settings.auth_cookie_name: cookie} if cookie else None,
            )
        status_code = int(resp.status_code)
        call_ok = 200 <= status_code < 300
        try:
            payload = resp.json()
            agent_result = payload if isinstance(payload, dict) else {"raw": resp.text}
        except Exception:
            agent_result = {"raw": resp.text}
    except Exception as e:
        call_error = str(e)

    session_id = str(agent_result.get("session_id") or "").strip()
    session_row = db.get_chat_session(session_id) if session_id else None
    message_rows = db.list_chat_messages(session_id, limit=10, offset=0) if session_id else []
    persisted_ok = bool(session_row) and len(message_rows) >= 2

    if llm_result.get("ok") and call_ok and persisted_ok and str(agent_result.get("agent_mode") or "").lower() == "llm":
        chain_status = "connected_llm_active"
        chain_message = "连通成功且LLM生效"
    elif llm_result.get("ok") and call_ok:
        chain_status = "connected_degraded"
        chain_message = "连通成功但降级"
    else:
        chain_status = "connect_failed"
        chain_message = "连通失败"

    return {
        "ok": chain_status != "connect_failed",
        "status": chain_status,
        "status_message": chain_message,
        "checked_at": now_iso(),
        "requested_by": str(user.get("username") or user.get("user_id") or ""),
        "llm_test": llm_result,
        "agent_call": {
            "ok": call_ok,
            "status_code": status_code,
            "error": call_error,
            "session_id": session_id,
            "agent_mode": agent_result.get("agent_mode"),
            "agent_reason": agent_result.get("agent_reason"),
            "result_type": agent_result.get("type"),
        },
        "persistence": {
            "ok": persisted_ok,
            "session_found": bool(session_row),
            "message_count": len(message_rows),
        },
        "request": chat_payload,
    }



@router.get("/logs/llm")
def llm_logs(limit: int = Query(default=20, ge=1, le=100)) -> dict[str, Any]:
    return {
        'items': _read_json_log_tail(settings.llm_audit_log_path, limit=limit),
        'path': settings.llm_audit_log_path,
    }


@router.get("/logs/llm/model_calls")
def llm_model_call_logs(limit: int = Query(default=20, ge=1, le=100)) -> dict[str, Any]:
    raw = _read_json_log_tail(settings.llm_audit_log_path, limit=max(60, limit * 4))
    items = [it for it in raw if str(it.get("event") or "").strip() == "model_call"][:limit]
    return {"items": items, "path": settings.llm_audit_log_path}


@router.get("/logs/app")
def app_logs(limit: int = Query(default=20, ge=1, le=100)) -> dict[str, Any]:
    return {
        'items': _read_json_log_tail(settings.app_log_path, limit=limit),
        'path': settings.app_log_path,
    }

@router.get("/eval/guide")
def eval_guide() -> dict[str, Any]:
    return {
        "skill_match_accuracy": {
            "target": 0.80,
            "steps": [
                "抽样学生与岗位配对，导出关键技能标注表。",
                "在人工标注列中补充真实结果。",
                "运行准确率脚本，对比系统判断与人工判断。",
            ],
            "commands": [
                "python scripts/eval/export_skill_match_label_sheet.py --students S001,S002 --jobs J001,J002 --out label.csv",
                "python scripts/eval/compute_skill_match_accuracy.py --in label.csv",
            ],
        },
        "profile_accuracy": {
            "target": 0.90,
            "steps": [
                "随机抽取岗位画像与学生画像，导出系统预测字段。",
                "对抽样记录补充人工真值字段。",
                "运行画像准确率脚本，核对技能、证书和偏好字段。",
            ],
            "commands": [
                "python scripts/eval/export_profile_label_sheet.py --random_jobs 50 --out job_profile_labels.csv",
                "python scripts/eval/export_profile_label_sheet.py --random_students 50 --out student_profile_labels.csv",
                "python scripts/eval/compute_profile_accuracy.py --csv job_profile_labels.csv",
                "python scripts/eval/compute_profile_accuracy.py --csv student_profile_labels.csv",
            ],
        },
    }


@router.post("/dictionary/bulk_upsert")
def bulk_upsert(req: BulkUpsertRequest) -> dict[str, Any]:
    for it in req.items:
        db.upsert_dictionary_item(
            {
                "item_id": it.item_id,
                "item_type": it.item_type,
                "name_zh": it.name_zh,
                "name_en": it.name_en,
                "category_lv1": it.category_lv1,
                "aliases_json": json.dumps(it.aliases, ensure_ascii=False),
                "description": it.description,
                "status": it.status,
                "merge_to": it.merge_to,
            }
        )
    return {"ok": True, "count": len(req.items)}


@router.get("/dictionary/search")
def search_dictionary(
    item_type: str | None = Query(default=None, description="hard_skill|soft_skill|certificate"),
    q: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
) -> dict[str, Any]:
    items = db.fetch_dictionary_items(item_type=item_type, q=q, limit=limit)
    return {"items": items}


@router.post("/weights/set_default")
def set_default_weights(weights: dict[str, float]) -> dict[str, Any]:
    db.upsert_weights("default", weights_json=json.dumps(weights, ensure_ascii=False), version="v1", updated_at=now_iso())
    return {"ok": True, "weights": weights}


@router.post("/weights/set_job_family/{job_family}")
def set_job_family_weights(job_family: str, weights: dict[str, float]) -> dict[str, Any]:
    key = f"job_family:{job_family}"
    db.upsert_weights(key, weights_json=json.dumps(weights, ensure_ascii=False), version="v1", updated_at=now_iso())
    return {"ok": True, "weights_key": key, "weights": weights}


@router.get("/weights/get")
def get_weights(key: str = Query(default="default")) -> dict[str, Any]:
    w = db.get_weights(key)
    if not w:
        return {"weights_key": key, "weights": None}
    return w


@router.get("/weights/list")
def list_weights(limit: int = Query(default=100, ge=1, le=500), offset: int = 0) -> dict[str, Any]:
    items = db.list_weights(limit=limit, offset=offset)
    return {"items": items, "limit": limit, "offset": offset}


@router.post("/tasks")
def create_task(req: TaskCreate) -> dict[str, Any]:
    task_id = gen_id("TASK", 12)
    task = {
        "task_id": task_id,
        "task_type": req.task_type,
        "payload_json": json.dumps(req.payload or {}, ensure_ascii=False),
        "status": "PENDING",
        "progress": 0.0,
        "result_json": None,
        "error": None,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    db.create_task(task)
    return {"ok": True, "task_id": task_id}


@router.get("/tasks")
def list_tasks(status: str | None = None, limit: int = 50, offset: int = 0) -> dict[str, Any]:
    return {"items": db.list_tasks(status=status, limit=limit, offset=offset), "limit": limit, "offset": offset}


@router.get("/tasks/{task_id}")
def get_task(task_id: str) -> dict[str, Any]:
    t = db.get_task(task_id)
    if not t:
        return {"error": "not_found"}
    try:
        payload = json.loads(t.get("payload_json") or "{}")
    except Exception:
        payload = {}
    try:
        result = json.loads(t.get("result_json") or "{}") if t.get("result_json") else None
    except Exception:
        result = None
    return {"task": {**t, "payload": payload, "result": result}}


@router.get("/events/summary")
def events_summary(days: int = Query(default=14, ge=1, le=180), limit: int = Query(default=8, ge=1, le=50)) -> dict[str, Any]:
    conn = db.get_conn()
    window_offset = max(0, days - 1)

    type_rows = conn.execute(
        """
        SELECT event_type, COUNT(1) AS c
        FROM student_job_events
        GROUP BY event_type
        ORDER BY c DESC
        """
    ).fetchall()

    type_rows_recent = conn.execute(
        """
        SELECT event_type, COUNT(1) AS c
        FROM student_job_events
        WHERE substr(created_at, 1, 10) >= date('now', '-' || ? || ' day')
        GROUP BY event_type
        ORDER BY c DESC
        """,
        (window_offset,),
    ).fetchall()

    detailed_rows = conn.execute(
        """
        SELECT event_type, source, meta_json, substr(created_at, 1, 10) AS day
        FROM student_job_events
        WHERE substr(created_at, 1, 10) >= date('now', '-' || ? || ' day')
        """,
        (window_offset,),
    ).fetchall()

    top_jobs_rows = conn.execute(
        """
        SELECT e.job_id, COUNT(1) AS c, j.title, j.company_name
        FROM student_job_events e
        LEFT JOIN jobs j ON j.job_id = e.job_id
        WHERE e.job_id IS NOT NULL
          AND substr(e.created_at, 1, 10) >= date('now', '-' || ? || ' day')
        GROUP BY e.job_id
        ORDER BY c DESC
        LIMIT ?
        """,
        (window_offset, limit),
    ).fetchall()

    top_roles_rows = conn.execute(
        """
        SELECT e.role_id, COUNT(1) AS c, r.title_rep, r.job_family
        FROM student_job_events e
        LEFT JOIN job_roles r ON r.role_id = e.role_id
        WHERE e.role_id IS NOT NULL
          AND substr(e.created_at, 1, 10) >= date('now', '-' || ? || ' day')
        GROUP BY e.role_id
        ORDER BY c DESC
        LIMIT ?
        """,
        (window_offset, limit),
    ).fetchall()

    source_counts: dict[str, int] = defaultdict(int)
    strategy_totals: dict[str, int] = defaultdict(int)
    strategy_positive: dict[str, int] = defaultdict(int)
    strategy_view_like: dict[str, int] = defaultdict(int)
    strategy_event_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    today = datetime.utcnow().date()
    start = today - timedelta(days=max(0, days - 1))
    daily_map = {(start + timedelta(days=i)).isoformat(): 0 for i in range(days)}

    for row in detailed_rows:
        day = str(row["day"] or "")
        if day in daily_map:
            daily_map[day] += 1

        source = str(row["source"] or "unknown").strip() or "unknown"
        source_counts[source] += 1

        event_type = str(row["event_type"] or "UNKNOWN").strip().upper() or "UNKNOWN"
        meta = _safe_load_json(row["meta_json"])
        strategy = _extract_strategy(meta)

        strategy_totals[strategy] += 1
        strategy_event_counts[strategy][event_type] += 1
        if event_type in {"FAVORITE", "APPLY"}:
            strategy_positive[strategy] += 1
        if event_type in {"VIEW", "SEARCH"}:
            strategy_view_like[strategy] += 1

    counts_by_source_recent = [
        {"source": source, "count": int(count)}
        for source, count in sorted(source_counts.items(), key=lambda x: x[1], reverse=True)[:limit]
    ]

    strategy_usage_recent = []
    for strategy, total in sorted(strategy_totals.items(), key=lambda x: x[1], reverse=True):
        pos = int(strategy_positive.get(strategy, 0))
        view_like = int(strategy_view_like.get(strategy, 0))
        denom = view_like if view_like > 0 else int(total)
        engagement_rate = float(pos / denom) if denom > 0 else 0.0
        event_breakdown = [
            {"event_type": et, "count": int(c)}
            for et, c in sorted(strategy_event_counts[strategy].items(), key=lambda x: x[1], reverse=True)
        ]
        strategy_usage_recent.append(
            {
                "strategy": strategy,
                "count": int(total),
                "positive_events": pos,
                "view_like_events": view_like,
                "engagement_rate": round(engagement_rate, 4),
                "event_breakdown": event_breakdown,
            }
        )

    return {
        "total_events": db.count_student_events(),
        "recent_events": int(sum(strategy_totals.values())),
        "counts_by_type": [{**dict(r), "count": int(r["c"])} for r in type_rows],
        "counts_by_type_recent": [{**dict(r), "count": int(r["c"])} for r in type_rows_recent],
        "counts_by_source_recent": counts_by_source_recent,
        "strategy_usage_recent": strategy_usage_recent[:limit],
        "daily_trend": [{"day": day, "count": int(count)} for day, count in daily_map.items()],
        "top_jobs": [
            {
                "job_id": r["job_id"],
                "count": int(r["c"]),
                "title": r["title"],
                "company_name": r["company_name"],
            }
            for r in top_jobs_rows
        ],
        "top_roles": [
            {
                "role_id": r["role_id"],
                "count": int(r["c"]),
                "title_rep": r["title_rep"],
                "job_family": r["job_family"],
            }
            for r in top_roles_rows
        ],
        "window_days": days,
    }


@router.get("/jobs")
def admin_list_jobs(q: str | None = None, location: str | None = None, limit: int = Query(default=100, ge=1, le=500), offset: int = 0) -> dict[str, Any]:
    return {
        "items": db.list_jobs(q=q, location=location, limit=limit, offset=offset),
        "total": db.count_jobs(),
        "limit": limit,
        "offset": offset,
    }


@router.post("/jobs/upsert")
def admin_upsert_job(body: dict[str, Any]) -> dict[str, Any]:
    job_id = str(body.get("job_id") or "").strip() or gen_id("J", 10)
    existing = db.get_job(job_id) or {}

    raw_body_title = body.get("title")
    title = str(raw_body_title or "").strip() if raw_body_title is not None else str(existing.get("title") or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="title_required")

    existing_raw: dict[str, Any] = {}
    try:
        existing_raw_val = existing.get("raw_json")
        if isinstance(existing_raw_val, str) and existing_raw_val.strip():
            parsed = json.loads(existing_raw_val)
            if isinstance(parsed, dict):
                existing_raw = parsed
    except Exception:
        existing_raw = {}

    raw = body.get("raw_json") if isinstance(body.get("raw_json"), dict) else existing_raw
    auto_generate_profile = bool(body.get("auto_generate_profile", True))

    if body.get("profile") is not None and "auto_generate_profile" not in body:
        # Prefer preserving manual profile edits unless caller explicitly asks to regenerate.
        auto_generate_profile = False

    def _pick(key: str, default: Any = None) -> Any:
        if key in body:
            return body.get(key)
        if key in existing:
            return existing.get(key)
        return default

    description_val = _pick("description", "")
    description = str(description_val or "").strip()

    db.insert_job(
        {
            "job_id": job_id,
            "title": title,
            "location": _pick("location"),
            "salary_min": _pick("salary_min"),
            "salary_max": _pick("salary_max"),
            "salary_period": _pick("salary_period", "month") or "month",
            "company_name": _pick("company_name"),
            "industry": _pick("industry"),
            "company_size": _pick("company_size"),
            "company_type": _pick("company_type"),
            "job_code": _pick("job_code"),
            "description": description,
            "company_intro": _pick("company_intro"),
            "updated_date": _pick("updated_date"),
            "source_url": _pick("source_url"),
            "raw_json": json.dumps(raw, ensure_ascii=False),
        }
    )

    profile_updated = False
    profile_payload = body.get("profile")
    if isinstance(profile_payload, dict):
        current_profile = (db.get_job_profile(job_id) or {}).get("profile")
        profile_obj: dict[str, Any] = dict(current_profile) if isinstance(current_profile, dict) else {}

        if "job_family" in profile_payload:
            family = str(profile_payload.get("job_family") or "").strip()
            profile_obj["job_family"] = family or None

        if "hard_skills" in profile_payload:
            hard_items: list[dict[str, Any]] = []
            for raw_name in (profile_payload.get("hard_skills") or []):
                name = str(raw_name or "").strip()
                if not name:
                    continue
                hard_items.append({
                    "mention": name,
                    "importance": "must_low",
                    "evidence": "后台手工编辑",
                    "source_section": "manual",
                    "mapping_method": "manual",
                })
            profile_obj["hard_skills"] = hard_items

        if "soft_skills" in profile_payload:
            soft_items: list[dict[str, Any]] = []
            for raw_name in (profile_payload.get("soft_skills") or []):
                name = str(raw_name or "").strip()
                if not name:
                    continue
                soft_items.append({
                    "name": name,
                    "importance": "must_low",
                    "evidence": "后台手工编辑",
                    "source_section": "manual",
                    "mapping_method": "manual",
                })
            profile_obj["soft_skills"] = soft_items

        if "certificates" in profile_payload:
            cert_items: list[dict[str, Any]] = []
            for raw_name in (profile_payload.get("certificates") or []):
                name = str(raw_name or "").strip()
                if not name:
                    continue
                cert_items.append({
                    "name": name,
                    "importance": "plus",
                    "evidence": "后台手工编辑",
                    "source_section": "manual",
                    "mapping_method": "manual",
                })
            profile_obj["certificates"] = cert_items

        if "tags" in profile_payload:
            tags = [str(x).strip() for x in (profile_payload.get("tags") or []) if str(x).strip()]
            dedup_tags: list[str] = []
            seen_tags: set[str] = set()
            for t in tags:
                key = t.lower()
                if key in seen_tags:
                    continue
                seen_tags.add(key)
                dedup_tags.append(t)
            profile_obj["tags"] = dedup_tags

        basic_patch = profile_payload.get("basic_requirements")
        if isinstance(basic_patch, dict):
            basic_obj = profile_obj.get("basic_requirements") if isinstance(profile_obj.get("basic_requirements"), dict) else {}
            if "education" in basic_patch:
                edu = str(basic_patch.get("education") or "").strip()
                basic_obj["education"] = edu or None
            if "experience_years_min" in basic_patch:
                exp_val = basic_patch.get("experience_years_min")
                try:
                    basic_obj["experience_years_min"] = int(exp_val) if exp_val is not None else None
                except Exception:
                    basic_obj["experience_years_min"] = None
            profile_obj["basic_requirements"] = basic_obj

        db.upsert_job_profile(job_id, profile_json=json.dumps(profile_obj, ensure_ascii=False), updated_at=now_iso())
        profile_updated = True

    if not auto_generate_profile:
        return {"ok": True, "job_id": job_id, "profile_generated": False, "profile_updated": profile_updated}

    try:
        profile = generate_job_profile(job_id).model_dump()
        return {
            "ok": True,
            "job_id": job_id,
            "profile_generated": True,
            "profile_updated": profile_updated,
            "profile_counts": {
                "hard_skills": len(profile.get("hard_skills") or []),
                "soft_skills": len(profile.get("soft_skills") or []),
                "certificates": len(profile.get("certificates") or []),
            },
        }
    except Exception as exc:
        return {
            "ok": True,
            "job_id": job_id,
            "profile_generated": False,
            "profile_updated": profile_updated,
            "profile_error": str(exc),
        }


@router.delete("/jobs/{job_id}")
def admin_delete_job(job_id: str) -> dict[str, Any]:
    if not db.get_job(job_id):
        raise HTTPException(status_code=404, detail="not_found")
    db.delete_job(job_id)
    return {"ok": True, "job_id": job_id}


@router.get("/users")
def admin_list_users(limit: int = Query(default=100, ge=1, le=500), offset: int = 0) -> dict[str, Any]:
    items = db.list_users(limit=limit, offset=offset)
    return {"items": items, "limit": limit, "offset": offset, "total": len(items)}


@router.post("/users/upsert")
def admin_upsert_user(body: dict[str, Any]) -> dict[str, Any]:
    username = str(body.get("username") or "").strip()
    if not username:
        raise HTTPException(status_code=400, detail="username_required")
    existing = db.get_user_by_username(username)
    ts = now_iso()
    if existing:
        password_hash = str(existing.get("password_hash") or "")
        new_password = str(body.get("password") or "").strip()
        if new_password:
            password_hash = hash_password(new_password)
        db.upsert_user(
            {
                "user_id": existing["user_id"],
                "username": username,
                "password_hash": password_hash,
                "display_name": str(body.get("display_name") or existing.get("display_name") or username),
                "role": str(body.get("role") or existing.get("role") or "viewer"),
                "is_active": 1 if body.get("is_active", True) else 0,
                "created_at": existing.get("created_at") or ts,
                "updated_at": ts,
            }
        )
        return {"ok": True, "user_id": existing["user_id"], "mode": "updated"}
    password = str(body.get("password") or "123456").strip() or "123456"
    user_id = gen_id("U", 12)
    db.upsert_user(
        {
            "user_id": user_id,
            "username": username,
            "password_hash": hash_password(password),
            "display_name": str(body.get("display_name") or username),
            "role": str(body.get("role") or "viewer"),
            "is_active": 1 if body.get("is_active", True) else 0,
            "created_at": ts,
            "updated_at": ts,
        }
    )
    return {"ok": True, "user_id": user_id, "mode": "created"}


@router.post("/import/excel_preview")
async def admin_preview_excel(file: UploadFile = File(...), sheet_name: str | int | None = 0) -> dict[str, Any]:
    suffix = Path(file.filename or "dataset.xlsx").suffix or ".xlsx"
    tmp = Path(settings.upload_dir)
    tmp.mkdir(parents=True, exist_ok=True)
    path = tmp / f"preview_{gen_id('UP', 8)}{suffix}"
    content = await file.read()
    path.write_bytes(content)
    try:
        data = preview_excel(path, sheet_name=sheet_name)
        data["filename"] = file.filename
        return data
    finally:
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass


@router.post("/pipeline/import_competition_xls")
def import_competition_xls_pipeline(body: dict[str, Any] | None = None) -> dict[str, Any]:
    body = body or {}
    default_path = Path.cwd() / "20260226105856_457.xls"
    source_path = Path(str(body.get("path") or default_path)).expanduser().resolve()
    if not source_path.exists():
        raise HTTPException(status_code=400, detail={"code": "source_file_not_found", "path": str(source_path)})

    sheet_name = coerce_sheet_name(body.get("sheet_name", 0))
    clear_existing = bool(body.get("clear_existing", False))
    profile_limit = body.get("profile_limit")
    computer_only = bool(body.get("computer_only", True))
    build_kb = bool(body.get("build_kb", True))
    build_graph = bool(body.get("build_graph", True))
    build_vectors = bool(body.get("build_vectors", True))

    if clear_existing:
        db.clear_jobs_related()

    preview = preview_excel(str(source_path), sheet_name=sheet_name, sample_rows=3)
    task_ids: list[str] = []
    task_ids.append(
        _enqueue_task(
            "INGEST_JOBS_FILE",
            {
                "path": str(source_path),
                "encoding": "utf-8",
                "filename": source_path.name,
                "sheet_name": sheet_name,
                "computer_only": computer_only,
            },
        )
    )
    task_ids.append(
        _enqueue_task(
            "BULK_GENERATE_JOB_PROFILES",
            {
                "only_missing": False,
                "limit": profile_limit,
            },
        )
    )
    task_ids.append(
        _enqueue_task(
            "REBUILD_ROLES_AND_ROLE_GRAPH",
            {
                "clear_existing": True,
                "limit": profile_limit,
                "build_index": True,
            },
        )
    )
    if build_vectors:
        task_ids.append(_enqueue_task("BUILD_JOB_INDEX", {"limit": 10000}))
    if build_graph:
        task_ids.append(_enqueue_task("REBUILD_JOB_GRAPH", {"limit": profile_limit}))
    if build_kb:
        task_ids.append(
            _enqueue_task(
                "MATERIALIZE_KB_FROM_DB",
                {
                    "max_roles": 300,
                    "max_jobs_per_role": 3,
                    "clear_generated": True,
                    "rebuild_index": True,
                },
            )
        )
        task_ids.append(_enqueue_task("REBUILD_KB_INDEX", {}))

    return {
        "ok": True,
        "source_path": str(source_path),
        "sheet_name": sheet_name,
        "clear_existing": clear_existing,
        "computer_only": computer_only,
        "task_ids": task_ids,
        "preview": {
            "sheet_names": preview.get("sheet_names") or [],
            "columns": preview.get("columns") or [],
            "row_count": preview.get("row_count") or 0,
            "mapped_fields": preview.get("mapped_fields") or [],
        },
    }
