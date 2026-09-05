from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from app.services.insights import build_competition_readiness, build_kb_readiness, build_market_overview, get_role_cockpit, list_featured_roles
from app.utils.labels import enrich_role_labels

router = APIRouter()


@router.get("/overview")
def overview(top_n: int = Query(default=10, ge=3, le=30)) -> dict[str, Any]:
    return build_market_overview(top_n=top_n)


@router.get("/role_samples")
def role_samples(top_k: int = Query(default=12, ge=1, le=50), job_family: str | None = None) -> dict[str, Any]:
    return {"items": [enrich_role_labels(x) for x in list_featured_roles(top_k=top_k, job_family=job_family)], "top_k": top_k}


@router.get("/role/{role_id}")
def role_cockpit(role_id: str, switch_top_k: int = Query(default=5, ge=1, le=10)) -> dict[str, Any]:
    data = get_role_cockpit(role_id, switch_top_k=switch_top_k)
    if not data:
        return {"error": "not_found"}
    if isinstance(data.get("role"), dict):
        data["role"] = enrich_role_labels(data.get("role"))
    profile_row = data.get("profile")
    if isinstance(profile_row, dict) and isinstance(profile_row.get("profile"), dict):
        profile_row = dict(profile_row)
        profile_row["profile"] = enrich_role_labels(profile_row.get("profile"))
        data["profile"] = profile_row
    return data


@router.get("/competition/readiness")
def readiness() -> dict[str, Any]:
    return build_competition_readiness()


@router.get("/kb/readiness")
def kb_readiness() -> dict[str, Any]:
    return build_kb_readiness()


@router.get("/career-map/pdf")
def career_map_pdf() -> FileResponse:
    root = Path(__file__).resolve().parents[4]
    target = root / "CSDN_IT人才成长路线图.pdf"
    if not target.exists():
        raise HTTPException(status_code=404, detail="career_map_pdf_not_found")
    return FileResponse(path=str(target), media_type="application/pdf", filename=target.name)
