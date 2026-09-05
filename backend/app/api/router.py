from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.routes import admin, admin_eval, auth, chat, graph, insights, interview, jobs, kb, match, reports, roles, students
from app.core.auth import require_route_access

api_router = APIRouter()
api_router.include_router(admin.router, prefix="/admin", tags=["admin"], dependencies=[Depends(require_route_access)])
api_router.include_router(admin_eval.router, prefix="/admin", tags=["admin"], dependencies=[Depends(require_route_access)])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(insights.router, prefix="/insights", tags=["insights"], dependencies=[Depends(require_route_access)])
api_router.include_router(jobs.router, prefix="/jobs", tags=["jobs"], dependencies=[Depends(require_route_access)])
api_router.include_router(roles.router, prefix="/roles", tags=["roles"], dependencies=[Depends(require_route_access)])
api_router.include_router(students.router, prefix="/students", tags=["students"], dependencies=[Depends(require_route_access)])
api_router.include_router(match.router, prefix="/match", tags=["match"], dependencies=[Depends(require_route_access)])
api_router.include_router(graph.router, prefix="/graph", tags=["graph"], dependencies=[Depends(require_route_access)])
api_router.include_router(reports.router, prefix="/reports", tags=["reports"], dependencies=[Depends(require_route_access)])
api_router.include_router(chat.router, prefix="/chat", tags=["chat"], dependencies=[Depends(require_route_access)])
api_router.include_router(kb.router, prefix="/kb", tags=["kb"], dependencies=[Depends(require_route_access)])
api_router.include_router(interview.router, prefix="/interview", tags=["interview"], dependencies=[Depends(require_route_access)])
