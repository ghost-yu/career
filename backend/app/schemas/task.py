from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class TaskCreate(BaseModel):
    task_type: str = Field(..., description="INGEST_JOBS_FILE|BULK_GENERATE_JOB_PROFILES|BUILD_JOB_INDEX|REBUILD_JOB_GRAPH|REBUILD_ROLES_AND_ROLE_GRAPH|BUILD_ROLE_INDEX")
    payload: Dict[str, Any] = Field(default_factory=dict)


class TaskInfo(BaseModel):
    task_id: str
    task_type: str
    status: str
    progress: float
    created_at: str
    updated_at: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
