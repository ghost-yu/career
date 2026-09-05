from __future__ import annotations

import os
from typing import Any

import httpx
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from app.services.interview_coach import (
    judge_coding_submission,
    make_coding_challenge,
    review_answer,
    review_coding_answer,
    start_interview,
    summarize_interview,
)
from app.services.face_auth_local import register_face_local, verify_face_local
from app.services.llm import llm_client

router = APIRouter()


def _zhipu_url(path: str) -> str:
    cfg = llm_client.runtime_config()
    base = str(cfg.get("base_url") or "https://open.bigmodel.cn/api/paas/v4").rstrip("/")
    return f"{base}/{path.lstrip('/')}"


def _zhipu_headers() -> dict[str, str]:
    cfg = llm_client.runtime_config()
    api_key = str(cfg.get("api_key") or "").strip()
    if not api_key:
        raise HTTPException(status_code=400, detail={"code": "zhipu_key_missing", "message": "请先在系统管理中配置智谱 API Key"})
    return {"Authorization": f"Bearer {api_key}"}


def _face_base_url() -> str:
    return str(os.getenv("FACE_VERIFY_BASE_URL") or os.getenv("FLASK_BASE_URL") or "").strip().rstrip("/")


async def _proxy_face(path: str, body: dict[str, Any]) -> dict[str, Any]:
    base_url = _face_base_url()
    if not base_url:
        return _local_face(path, body)
    payload = {
        "image": str(body.get("image") or ""),
        "userId": str(body.get("userId") or body.get("user_id") or ""),
    }
    if not payload["image"] or not payload["userId"]:
        raise HTTPException(status_code=400, detail={"code": "face_payload_required", "message": "image/userId required"})
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(f"{base_url}/{path.lstrip('/')}", json=payload)
        if resp.status_code >= 400:
            raise HTTPException(status_code=resp.status_code, detail={"code": "face_service_failed", "message": resp.text})
        data = resp.json()
        return data if isinstance(data, dict) else {"status": "1", "message": str(data)}
    except HTTPException:
        raise
    except Exception:
        return _local_face(path, body)


def _local_face(path: str, body: dict[str, Any]) -> dict[str, Any]:
    image = str(body.get("image") or "")
    user_id = str(body.get("userId") or body.get("user_id") or "")
    if not image or not user_id:
        raise HTTPException(status_code=400, detail={"code": "face_payload_required", "message": "image/userId required"})
    route = path.strip().lower().strip("/")
    if route == "register-face":
        return register_face_local(image, user_id)
    if route == "verify-face":
        return verify_face_local(image, user_id)
    raise HTTPException(status_code=404, detail={"code": "face_route_not_found", "message": route})


@router.post("/start")
def start(body: dict[str, Any]) -> dict[str, Any]:
    student_id = str(body.get("student_id") or "").strip()
    if not student_id:
        raise HTTPException(status_code=400, detail={"code": "student_id_required", "message": "student_id required"})
    return start_interview(
        student_id,
        str(body.get("job_id") or "").strip() or None,
        question_count=int(body.get("question_count") or 4),
    )


@router.post("/answer")
def answer(body: dict[str, Any]) -> dict[str, Any]:
    student_id = str(body.get("student_id") or "").strip()
    question = str(body.get("question") or "").strip()
    answer_text = str(body.get("answer") or "").strip()
    if not student_id or not question or not answer_text:
        raise HTTPException(status_code=400, detail={"code": "answer_payload_required", "message": "student_id/question/answer required"})
    return review_answer(
        student_id,
        question,
        answer_text,
        job_id=str(body.get("job_id") or "").strip() or None,
        history=body.get("history") if isinstance(body.get("history"), list) else [],
    )


@router.post("/summary")
def summary(body: dict[str, Any]) -> dict[str, Any]:
    student_id = str(body.get("student_id") or "").strip()
    items = body.get("items")
    if not student_id or not isinstance(items, list):
        raise HTTPException(status_code=400, detail={"code": "summary_payload_required", "message": "student_id/items required"})
    return summarize_interview(
        student_id,
        items,
        job_id=str(body.get("job_id") or "").strip() or None,
        coding_review=body.get("coding_review") if isinstance(body.get("coding_review"), dict) else None,
        coding_challenge=body.get("coding_challenge") if isinstance(body.get("coding_challenge"), dict) else None,
    )


@router.post("/coding/start")
def coding_start(body: dict[str, Any]) -> dict[str, Any]:
    student_id = str(body.get("student_id") or "").strip()
    if not student_id:
        raise HTTPException(status_code=400, detail={"code": "student_id_required", "message": "student_id required"})
    return make_coding_challenge(
        student_id,
        job_id=str(body.get("job_id") or "").strip() or None,
        language=str(body.get("language") or "python"),
        difficulty=str(body.get("difficulty") or "medium"),
        first=bool(body.get("first", True)),
    )


@router.post("/coding/review")
def coding_review(body: dict[str, Any]) -> dict[str, Any]:
    student_id = str(body.get("student_id") or "").strip()
    challenge = body.get("challenge")
    code = str(body.get("code") or "").strip()
    if not student_id or not isinstance(challenge, dict) or not code:
        raise HTTPException(status_code=400, detail={"code": "coding_review_payload_required", "message": "student_id/challenge/code required"})
    return review_coding_answer(
        student_id,
        challenge,
        code,
        job_id=str(body.get("job_id") or "").strip() or None,
    )


@router.post("/coding/judge")
def coding_judge(body: dict[str, Any]) -> dict[str, Any]:
    student_id = str(body.get("student_id") or "").strip()
    challenge = body.get("challenge")
    code = str(body.get("code") or "").strip()
    if not student_id or not isinstance(challenge, dict) or not code:
        raise HTTPException(status_code=400, detail={"code": "coding_judge_payload_required", "message": "student_id/challenge/code required"})
    return judge_coding_submission(
        student_id,
        challenge,
        code,
        job_id=str(body.get("job_id") or "").strip() or None,
        sample_only=bool(body.get("sample_only", False)),
    )


@router.post("/face/verify")
async def verify_face(body: dict[str, Any]) -> dict[str, Any]:
    return await _proxy_face("/verify-face", body)


@router.post("/face/register")
async def register_face(body: dict[str, Any]) -> dict[str, Any]:
    return await _proxy_face("/register-face", body)


@router.post("/speech/transcribe")
async def transcribe_audio(file: UploadFile = File(...), model: str = Form(default="")) -> dict[str, Any]:
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail={"code": "empty_audio", "message": "音频为空"})
    files = {
        "file": (file.filename or "answer.webm", content, file.content_type or "application/octet-stream"),
    }
    default_model = str(os.getenv("ZHIPU_ASR_MODEL") or "glm-asr-2512").strip()
    data = {"model": model or default_model, "stream": "false"}
    try:
        async with httpx.AsyncClient(timeout=90) as client:
            resp = await client.post(_zhipu_url("/audio/transcriptions"), headers=_zhipu_headers(), data=data, files=files)
        if resp.status_code >= 400:
            raise HTTPException(status_code=resp.status_code, detail={"code": "asr_failed", "message": resp.text})
        payload = resp.json()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail={"code": "asr_failed", "message": str(exc)}) from exc
    text = str(payload.get("text") or payload.get("result") or "").strip()
    return {"ok": True, "text": text, "raw": payload}


@router.post("/speech/synthesize")
async def synthesize_speech(body: dict[str, Any]) -> Response:
    text = str(body.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail={"code": "text_required", "message": "text required"})
    payload = {
        "model": str(body.get("model") or os.getenv("ZHIPU_TTS_MODEL") or "glm-tts"),
        "input": text[:2000],
        "voice": str(body.get("voice") or "tongtong"),
        "response_format": str(body.get("response_format") or "wav"),
        "speed": float(body.get("speed") or 1.0),
        "volume": float(body.get("volume") or 1.0),
    }
    try:
        async with httpx.AsyncClient(timeout=90) as client:
            resp = await client.post(
                _zhipu_url("/audio/speech"),
                headers={**_zhipu_headers(), "Content-Type": "application/json"},
                json=payload,
            )
        if resp.status_code >= 400:
            raise HTTPException(status_code=resp.status_code, detail={"code": "tts_failed", "message": resp.text})
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail={"code": "tts_failed", "message": str(exc)}) from exc
    return Response(content=resp.content, media_type=resp.headers.get("content-type") or "audio/mpeg")
