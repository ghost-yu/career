from __future__ import annotations

import json
import re
import time
from typing import Any
from uuid import uuid4

import httpx

from app.core.config import settings
from app.core.logging import emit_audit_event
from app.services.llm_runtime import load_effective_llm_config

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_RESUME_MODEL = "deepseek-v4-pro"
_JSON_BLOCK_RE = re.compile(r"\{[\s\S]*\}$")
_JSON_FENCE_RE = re.compile(r"^```(?:json|JSON)?\s*([\s\S]*?)\s*```$")


def deepseek_config() -> dict[str, Any]:
    runtime = load_effective_llm_config()
    runtime_is_deepseek = str(runtime.get("provider") or "").strip().lower() == "deepseek"
    api_key = str(settings.deepseek_api_key or "").strip()
    if not api_key and runtime_is_deepseek:
        api_key = str(runtime.get("api_key") or "").strip()
    return {
        "provider": "deepseek",
        "base_url": DEEPSEEK_BASE_URL,
        "model": DEEPSEEK_RESUME_MODEL,
        "api_key": api_key,
        "temperature": 0.2,
        "timeout_seconds": int(runtime.get("timeout_seconds") or 60),
    }


def deepseek_json_enabled() -> bool:
    return bool(str(deepseek_config().get("api_key") or "").strip())


def _chat_url(base_url: str) -> str:
    base = str(base_url or "").strip().rstrip("/")
    if not base:
        raise ValueError("deepseek_base_url_empty")
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def _collect_chat_text(payload: dict[str, Any]) -> str:
    try:
        choice = (payload.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        content = message.get("content")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    text = item.get("text") or item.get("content")
                    if isinstance(text, str):
                        parts.append(text)
            return "\n".join([part for part in parts if part.strip()]).strip()
        reasoning = message.get("reasoning_content")
        if isinstance(reasoning, str):
            return reasoning.strip()
    except Exception:
        return ""
    return ""


def _strip_json_fence(text: str) -> str:
    raw = str(text or "").strip()
    match = _JSON_FENCE_RE.match(raw)
    return match.group(1).strip() if match else raw


def _json_candidates(text: str) -> list[str]:
    raw = _strip_json_fence(text)
    candidates: list[str] = [raw]
    fenced = re.findall(r"```(?:json|JSON)?\s*([\s\S]*?)\s*```", raw)
    candidates.extend([item.strip() for item in fenced if item.strip()])

    starts = [idx for idx, ch in enumerate(raw) if ch == "{"]
    for start in starts:
        depth = 0
        in_string = False
        escape = False
        for idx in range(start, len(raw)):
            ch = raw[idx]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidates.append(raw[start : idx + 1].strip())
                    break
    return candidates


def _matches_expected_keys(value: dict[str, Any], expected_keys: set[str] | None) -> bool:
    if not expected_keys:
        return True
    return bool(set(value.keys()) & set(expected_keys))


def _as_json_dict(value: Any, expected_keys: set[str] | None = None) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value if _matches_expected_keys(value, expected_keys) else None
    if isinstance(value, str):
        try:
            nested = json.loads(_strip_json_fence(value))
        except Exception:
            return None
        return nested if isinstance(nested, dict) and _matches_expected_keys(nested, expected_keys) else None
    return None


def _parse_json_text(text: str, expected_keys: set[str] | None = None) -> dict[str, Any]:
    raw = str(text or "").strip()
    if not raw:
        raise ValueError("deepseek_empty_response")
    for candidate in _json_candidates(raw):
        try:
            parsed = json.loads(candidate)
        except Exception:
            continue
        as_dict = _as_json_dict(parsed, expected_keys)
        if as_dict is not None:
            return as_dict
    match = _JSON_BLOCK_RE.search(_strip_json_fence(raw))
    if match:
        try:
            parsed = json.loads(match.group(0))
        except Exception:
            parsed = None
        as_dict = _as_json_dict(parsed, expected_keys)
        if as_dict is not None:
            return as_dict
    raise ValueError("deepseek_json_parse_failed")


def deepseek_chat_json_sync(
    system: str,
    user: str,
    *,
    trace_context: str,
    max_tokens: int,
    expected_root_keys: set[str] | None = None,
) -> dict[str, Any]:
    cfg = deepseek_config()
    api_key = str(cfg.get("api_key") or "").strip()
    if not api_key:
        raise ValueError("deepseek_api_key_missing")
    call_id = f"deepseek-{uuid4().hex[:12]}"
    started = time.perf_counter()
    payload = {
        "model": DEEPSEEK_RESUME_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": float(cfg.get("temperature") or 0.2),
        "stream": False,
        "response_format": {"type": "json_object"},
        "thinking": {"type": "disabled"},
        "max_tokens": int(max_tokens),
    }
    event: dict[str, Any] = {
        "event": "model_call",
        "trace_id": call_id,
        "load_id": call_id,
        "provider": "deepseek",
        "model": DEEPSEEK_RESUME_MODEL,
        "base_url": DEEPSEEK_BASE_URL,
        "mode": "compatible_json",
        "trace_context": trace_context,
        "input": {
            "system": system[:12000],
            "user": user[:12000],
        },
    }
    try:
        with httpx.Client(timeout=max(60.0, float(cfg.get("timeout_seconds") or 60))) as client:
            resp = client.post(
                _chat_url(DEEPSEEK_BASE_URL),
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
            )
            if resp.status_code >= 400:
                raise RuntimeError(f"deepseek_request_failed:{resp.status_code}:{(resp.text or '')[:240]}")
            data = resp.json() if resp.text else {}
        text = _collect_chat_text(data)
        parsed = _parse_json_text(text, expected_root_keys)
        event["ok"] = True
        event["duration_ms"] = int((time.perf_counter() - started) * 1000)
        event["output"] = {"text": text[:12000], "json": parsed}
        emit_audit_event(event)
        return parsed
    except Exception as exc:
        event["ok"] = False
        event["duration_ms"] = int((time.perf_counter() - started) * 1000)
        event["error"] = str(exc)
        if "data" in locals():
            event["response"] = {
                "raw": data if isinstance(data, dict) else str(data)[:12000],
                "text": _collect_chat_text(data)[:12000] if isinstance(data, dict) else "",
            }
        emit_audit_event(event)
        raise
