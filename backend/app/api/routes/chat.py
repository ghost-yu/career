from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.auth import get_current_user
from app.db import sqlite as db
from app.services.agent import run_agent
from app.services.graph_store import graph_store
from app.services.llm import llm_client
from app.services.reporting import generate_report
from app.services.retrieval import search_jobs
from app.services.scoring import score
from app.utils.ids import gen_id, now_iso

router = APIRouter()

# Small in-memory cache, still used as a fast transient state mirror.
_session_mem: dict[str, dict[str, Any]] = {}


def _default_state() -> dict[str, Any]:
    return {"last_recommended": [], "last_recommended_roles": [], "last_compared_roles": []}


def _load_state_from_row(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return _default_state()
    try:
        val = json.loads(row.get("state_json") or "{}")
        if isinstance(val, dict):
            out = _default_state()
            out.update(val)
            return out
    except Exception:
        pass
    return _default_state()


def _state_key(student_id: str, session_id: str) -> str:
    return f"{student_id}:{session_id}"


def _touch_session(
    *,
    session_id: str,
    owner_id: str,
    student_id: str,
    message: str,
    state: dict[str, Any],
    last_job_id: str | None = None,
) -> dict[str, Any]:
    row = db.get_chat_session(session_id)
    ts = now_iso()
    title = (row or {}).get("title") or message[:20]

    if row:
        if str(row.get("user_id") or "") != owner_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="session_forbidden")
        db.update_chat_session(
            session_id=session_id,
            updated_at=ts,
            title=title,
            last_job_id=last_job_id,
            state_json=json.dumps(state, ensure_ascii=False),
        )
        return row

    db.create_chat_session(
        {
            "session_id": session_id,
            "user_id": owner_id,
            "student_id": student_id,
            "title": title,
            "last_job_id": last_job_id,
            "state_json": json.dumps(state, ensure_ascii=False),
            "created_at": ts,
            "updated_at": ts,
        }
    )
    return db.get_chat_session(session_id) or {}


def _persist_turn(
    *,
    session_id: str,
    owner_id: str,
    user_text: str,
    assistant_payload: dict[str, Any],
) -> None:
    ts = now_iso()
    db.insert_chat_message(
        {
            "message_id": gen_id("CM", 12),
            "session_id": session_id,
            "user_id": owner_id,
            "role": "user",
            "content": user_text,
            "meta_json": "{}",
            "created_at": ts,
        }
    )
    db.insert_chat_message(
        {
            "message_id": gen_id("CM", 12),
            "session_id": session_id,
            "user_id": owner_id,
            "role": "assistant",
            "content": json.dumps(assistant_payload, ensure_ascii=False),
            "meta_json": json.dumps({"type": assistant_payload.get("type")}, ensure_ascii=False),
            "created_at": now_iso(),
        }
    )


def _get_state(student_id: str, session_id: str, session_row: dict[str, Any] | None) -> dict[str, Any]:
    key = _state_key(student_id, session_id)
    if key not in _session_mem:
        _session_mem[key] = _load_state_from_row(session_row)
    return _session_mem[key]


@router.get("/sessions")
def list_sessions(
    user: dict[str, Any] = Depends(get_current_user),
    limit: int = 30,
    offset: int = 0,
    student_id: str | None = None,
) -> dict[str, Any]:
    items = db.list_chat_sessions(
        str(user["user_id"]),
        limit=max(1, min(limit, 100)),
        offset=max(0, offset),
        student_id=(str(student_id or "").strip() or None),
    )
    return {"items": items, "limit": limit, "offset": offset}


@router.get("/sessions/{session_id}/messages")
def list_session_messages(
    session_id: str,
    user: dict[str, Any] = Depends(get_current_user),
    limit: int = 200,
    offset: int = 0,
) -> dict[str, Any]:
    session = db.get_chat_session(session_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session_not_found")
    if str(session.get("user_id") or "") != str(user["user_id"]):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="session_forbidden")
    items = db.list_chat_messages(session_id, limit=max(1, min(limit, 500)), offset=max(0, offset))
    return {"session": session, "items": items, "limit": limit, "offset": offset}


@router.post("/sessions")
def create_session(body: dict[str, Any], user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    student_id = str(body.get("student_id") or "").strip()
    if not student_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="student_id_required")
    session_id = gen_id("CS", 12)
    ts = now_iso()
    title = str(body.get("title") or "").strip() or "新会话"
    db.create_chat_session(
        {
            "session_id": session_id,
            "user_id": str(user["user_id"]),
            "student_id": student_id,
            "title": title[:30],
            "last_job_id": None,
            "state_json": json.dumps(_default_state(), ensure_ascii=False),
            "created_at": ts,
            "updated_at": ts,
        }
    )
    return {"ok": True, "session_id": session_id}


@router.delete("/sessions/{session_id}")
def delete_session(session_id: str, user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    session = db.get_chat_session(session_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session_not_found")
    if str(session.get("user_id") or "") != str(user["user_id"]):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="session_forbidden")
    db.delete_chat_session(session_id)
    key = _state_key(str(session.get("student_id") or ""), session_id)
    _session_mem.pop(key, None)
    return {"ok": True, "session_id": session_id}


@router.delete("/sessions/{session_id}/messages")
def clear_session_messages(session_id: str, user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    session = db.get_chat_session(session_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session_not_found")
    if str(session.get("user_id") or "") != str(user["user_id"]):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="session_forbidden")

    deleted = db.delete_chat_messages(session_id)
    state = _default_state()
    student_id = str(session.get("student_id") or "")
    db.update_chat_session(
        session_id=session_id,
        updated_at=now_iso(),
        state_json=json.dumps(state, ensure_ascii=False),
    )
    _session_mem[_state_key(student_id, session_id)] = state
    return {"ok": True, "session_id": session_id, "deleted": deleted}


@router.post("")
def chat(body: dict[str, Any], user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    """Legacy endpoint kept for compatibility."""

    student_id = str(body.get("student_id") or "").strip()
    msg = str(body.get("message") or "").strip()
    if not student_id or not msg:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="student_id_and_message_required")

    owner_id = str(user["user_id"])
    session_id = str(body.get("session_id") or "").strip() or gen_id("CS", 12)
    session_row = db.get_chat_session(session_id)
    state = _get_state(student_id, session_id, session_row)
    msg_lower = msg.lower()

    if ("model" in msg_lower) or ("llm" in msg_lower) or ("什么模型" in msg) or ("你是什么模型" in msg) or ("当前模型" in msg):
        runtime = llm_client.runtime_config()
        payload = {
            "type": "text",
            "content": (
                "当前生涯顾问模型配置：\n"
                f"- provider: {str(runtime.get('provider') or 'unknown')}\n"
                f"- model: {str(runtime.get('model') or 'unknown')}\n"
                f"- base_url: {str(runtime.get('base_url') or 'unknown')}"
            ),
        }
    elif any(k in msg for k in ["推荐", "找岗位", "岗位推荐", "job", "position"]):
        sp = db.get_student_profile(student_id)
        skill_terms: list[str] = []
        if sp:
            for item in sp["profile"].get("hard_skills", [])[:12]:
                mention = item.get("mention")
                if mention:
                    skill_terms.append(str(mention))
        query = (msg + " " + " ".join(skill_terms)).strip()
        recs = search_jobs(query, top_k=10)
        state["last_recommended"] = [str(r.get("job_id")) for r in recs if r.get("job_id")]
        payload = {"type": "recommendations", "query": query, "items": recs}
    elif any(k in msg for k in ["匹配", "match", "适配度", "评分"]):
        job_id = body.get("job_id") or (state.get("last_recommended") or [None])[0]
        if not job_id:
            payload = {"type": "text", "content": "请先选定一个岗位，或先让系统为你推荐岗位。"}
        else:
            payload = {"type": "match_result", "job_id": job_id, "result": score(student_id, job_id, use_cache=True).model_dump()}
    elif any(k in msg for k in ["路径", "晋升", "换岗", "发展"]):
        job_id = body.get("job_id") or (state.get("last_recommended") or [None])[0]
        if not job_id:
            payload = {"type": "text", "content": "请先选定一个岗位，或先完成岗位推荐，再查看职业路径。"}
        else:
            vertical = graph_store.get_vertical_path(job_id)
            switches = graph_store.get_switch_paths(job_id, top_k=5)
            payload = {"type": "paths", "job_id": job_id, "vertical_path": vertical, "switch_paths": switches}
    elif any(k in msg for k in ["报告", "生成报告", "导出"]):
        job_ids = body.get("target_job_ids") or state.get("last_recommended") or []
        if not job_ids:
            payload = {"type": "text", "content": "请先把目标岗位加入报告清单，或先完成岗位推荐，再生成报告。"}
        else:
            rpt = generate_report(student_id, list(job_ids)[:5])
            payload = {"type": "report", "report_id": rpt.report_id, "markdown": rpt.markdown}
    else:
        payload = {
            "type": "help",
            "content": (
                "我可以帮助你：\n"
                "1) 推荐岗位：发送“推荐岗位/找岗位” + 你的方向\n"
                "2) 查看匹配：发送“匹配/评分”，也可以直接点岗位卡片\n"
                "3) 查看路径：发送“路径/晋升/换岗”，也可以直接点路径按钮\n"
                "4) 生成报告：发送“生成报告/报告”，也可以先把岗位加入报告清单\n"
                "5) 也可直接在生涯顾问页继续追问"
            ),
        }

    _touch_session(
        session_id=session_id,
        owner_id=owner_id,
        student_id=student_id,
        message=msg,
        state=state,
        last_job_id=str(body.get("job_id") or "") or None,
    )
    _persist_turn(session_id=session_id, owner_id=owner_id, user_text=msg, assistant_payload=payload)
    payload["session_id"] = session_id
    return payload


@router.post("/agent")
async def chat_agent(body: dict[str, Any], user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    """LLM-planned tool execution with persistent session storage."""

    student_id = str(body.get("student_id") or "").strip()
    if not student_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="student_id_required")

    owner_id = str(user["user_id"])
    msg = str(body.get("message") or "").strip()
    session_id = str(body.get("session_id") or "").strip() or gen_id("CS", 12)
    session_row = db.get_chat_session(session_id)
    state = _get_state(student_id, session_id, session_row)

    result = await run_agent(student_id, body, state)

    _touch_session(
        session_id=session_id,
        owner_id=owner_id,
        student_id=student_id,
        message=msg,
        state=state,
        last_job_id=str(body.get("job_id") or "") or None,
    )
    _persist_turn(session_id=session_id, owner_id=owner_id, user_text=msg, assistant_payload=result)

    out = dict(result)
    out["session_id"] = session_id
    return out
