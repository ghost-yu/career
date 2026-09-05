from __future__ import annotations

import logging
import os
import sys
import threading
import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router
from app.core.auth import ensure_preset_users
from app.core.config import settings
from app.core.logging import setup_logging
from app.db import sqlite as db
from app.db.sqlite import init_db
from app.services.g_rank_migration import prewarm_g_rank_models
from app.utils.ids import now_iso
from app.worker import process_one

logger = logging.getLogger(__name__)


def _inline_worker_loop(stop_event: threading.Event) -> None:
    logger.info("inline worker started (poll=%ss)", settings.worker_poll_seconds)
    while not stop_event.is_set():
        task = db.claim_next_task()
        if not task:
            stop_event.wait(float(settings.worker_poll_seconds))
            continue
        task_id = str(task.get("task_id") or "")
        task_type = str(task.get("task_type") or "")
        try:
            process_one(task)
            logger.info("inline worker success task_id=%s type=%s", task_id, task_type)
        except Exception as exc:
            db.update_task(
                task_id,
                status="FAILED",
                progress=float(task.get("progress") or 0.0),
                error=str(exc),
                updated_at=now_iso(),
            )
            logger.exception("inline worker failed task_id=%s type=%s", task_id, task_type)
    logger.info("inline worker stopped")


def _prewarm_match_models() -> None:
    if not settings.match_model_prewarm_enabled:
        logger.info("match model prewarm disabled by config")
        return
    started = time.perf_counter()
    try:
        stats = prewarm_g_rank_models(
            build_index=bool(settings.match_model_prewarm_build_index),
            max_jobs=int(settings.match_model_prewarm_max_jobs),
        )
        logger.info(
            "match model prewarm finished in %sms: %s",
            round((time.perf_counter() - started) * 1000),
            stats,
        )
    except Exception:
        logger.exception("match model prewarm failed")


def _resolve_frontend_dist() -> Path | None:
    env_dir = str(os.getenv("FRONTEND_DIST_DIR", "")).strip()
    candidates: list[Path] = []
    if env_dir:
        candidates.append(Path(env_dir))

    if getattr(sys, "frozen", False):
        meipass = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        candidates.append(meipass / "frontend_dist")

    repo_root = Path(__file__).resolve().parents[2]
    candidates.extend([
        repo_root / "frontend" / "dist",
        Path.cwd() / "frontend" / "dist",
    ])

    for candidate in candidates:
        index_file = candidate / "index.html"
        if index_file.exists():
            return candidate
    return None


def create_app() -> FastAPI:
    setup_logging("INFO")
    init_db()
    preset_result = ensure_preset_users()
    logger.info("预置账号已初始化：%s", preset_result)

    app = FastAPI(
        title=settings.app_name,
        description="基于人工智能的大学生职业规划后端服务，提供岗位画像、学生画像、人岗匹配、职业路径、报告生成与批处理任务接口。",
        version="0.6.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.on_event("startup")
    async def _start_inline_worker() -> None:
        prewarm_running = getattr(app.state, "match_prewarm_thread", None)
        if not prewarm_running or not getattr(prewarm_running, "is_alive", lambda: False)():
            prewarm_thread = threading.Thread(
                target=_prewarm_match_models,
                daemon=True,
                name="match-model-prewarm",
            )
            app.state.match_prewarm_thread = prewarm_thread
            prewarm_thread.start()
        if not settings.inline_worker_enabled:
            logger.info("inline worker disabled by config")
            return
        requeued = db.requeue_running_tasks(updated_at=now_iso())
        if requeued:
            logger.warning("requeued orphan RUNNING tasks after reload: %s", requeued)
        running = getattr(app.state, "inline_worker_thread", None)
        if running and getattr(running, "is_alive", lambda: False)():
            return
        stop_event = threading.Event()
        t = threading.Thread(
            target=_inline_worker_loop,
            args=(stop_event,),
            daemon=True,
            name="inline-task-worker",
        )
        app.state.inline_worker_stop_event = stop_event
        app.state.inline_worker_thread = t
        t.start()

    @app.on_event("shutdown")
    async def _stop_inline_worker() -> None:
        stop_event = getattr(app.state, "inline_worker_stop_event", None)
        t = getattr(app.state, "inline_worker_thread", None)
        if stop_event is not None:
            stop_event.set()
        if t and getattr(t, "is_alive", lambda: False)():
            t.join(timeout=float(settings.inline_worker_join_timeout_seconds))

    frontend_url = str(settings.frontend_app_url or "").strip().rstrip("/")
    if not frontend_url:
        frontend_url = "http://localhost:5173"

    allow = [o.strip() for o in (settings.cors_allow_origins or "").split(",") if o.strip()]
    allow_set = set(allow)
    allow_set.update({"http://localhost:5173", "http://127.0.0.1:5173", frontend_url})
    if "*" in allow_set:
        allow_set.remove("*")
    allow_list = sorted({x for x in allow_set if x})
    # Allow localhost and common LAN origins for local/dev deployment scenarios.
    local_network_origin_regex = (
        r"^https?://("
        r"localhost"
        r"|127\.0\.0\.1"
        r"|10(?:\.\d{1,3}){3}"
        r"|192\.168(?:\.\d{1,3}){2}"
        r"|172\.(?:1[6-9]|2\d|3[0-1])(?:\.\d{1,3}){2}"
        r")(?:\:\d+)?$"
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_list,
        allow_origin_regex=local_network_origin_regex,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    logger.info("CORS origins=%s + regex(localhost/127/private-lan any port)", allow_list)

    app.include_router(api_router)

    def _health_payload() -> dict[str, object]:
        return {"ok": True, "app": settings.app_name, "env": settings.env}

    @app.get("/health")
    def health():
        return _health_payload()

    @app.get("/healthz")
    def healthz():
        return _health_payload()

    frontend_dist = _resolve_frontend_dist()
    if frontend_dist:
        logger.info("frontend static enabled: %s", frontend_dist)
        app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")

        @app.exception_handler(404)
        async def spa_fallback(request: Request, _):
            # Keep API-like routes as JSON 404; fallback other routes to SPA index.
            path = str(request.url.path or "")
            if path.startswith(("/admin", "/auth", "/insights", "/jobs", "/roles", "/students", "/match", "/graph", "/reports", "/chat", "/kb", "/interview", "/news", "/health", "/healthz")):
                return JSONResponse(status_code=404, content={"detail": "Not Found"})
            index_file = frontend_dist / "index.html"
            if index_file.exists():
                return FileResponse(index_file)
            return JSONResponse(status_code=404, content={"detail": "Not Found"})
    else:
        logger.info("frontend static not found, redirecting SPA routes to %s", frontend_url)

        def _register_spa_redirect(path: str) -> None:
            @app.get(path, include_in_schema=False)
            def _redirect_to_frontend() -> RedirectResponse:
                suffix = "" if path == "/" else path
                return RedirectResponse(url=f"{frontend_url}{suffix}", status_code=307)

        for _path in ["/", "/login", "/assistant", "/jobs", "/student", "/match", "/resume", "/resume/editor", "/roles", "/report", "/interview", "/news", "/operations", "/defense-screen"]:
            _register_spa_redirect(_path)

    return app


app = create_app()
