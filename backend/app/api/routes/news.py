from __future__ import annotations

import os
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Query

router = APIRouter()

DEFAULT_UPSTREAM_BASE = "https://news.yltfspace.com/api"


async def _proxy_get(path: str, params: dict[str, Any]) -> Any:
    base = str(os.getenv("NEWS_UPSTREAM_BASE_URL") or DEFAULT_UPSTREAM_BASE).rstrip("/")
    url = f"{base}/{path.lstrip('/')}"
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            response = await client.get(url, params={k: v for k, v in params.items() if v not in (None, "")})
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail={"code": "news_upstream_failed", "message": str(exc)}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=502, detail={"code": "news_upstream_invalid_json", "message": str(exc)}) from exc

    if isinstance(payload, dict) and int(payload.get("code") or 0) == 200:
        return payload.get("data") or []
    if isinstance(payload, list):
        return payload
    return []


@router.get("")
async def list_news(
    platform: str = Query(..., description="新闻平台标识"),
    order: str | None = Query(None, pattern="^(asc|desc)$"),
    timestamp: int | None = Query(None, alias="_t"),
) -> Any:
    return await _proxy_get("news", {"platform": platform, "order": order, "_t": timestamp})


@router.get("/platforms")
async def list_platforms() -> Any:
    return await _proxy_get("platforms", {})
