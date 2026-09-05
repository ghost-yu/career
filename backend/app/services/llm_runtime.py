from __future__ import annotations

import json
from typing import Any

from app.core.config import settings
from app.db import sqlite as db
from app.utils.ids import now_iso

SETTING_KEY = "llm_runtime"

_PROVIDER_DEFAULTS: dict[str, dict[str, Any]] = {
    "mock": {
        "provider": "mock",
        "label": "本地模拟",
        "base_url": "",
        "model": "mock",
        "api_key": "",
        "enabled": False,
    },
    "deepseek": {
        "provider": "deepseek",
        "label": "深度求索（推荐）",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
        "api_key": "",
        "enabled": True,
    },
    "qwen": {
        "provider": "qwen",
        "label": "阿里云百炼（通义千问）",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-plus",
        "api_key": "",
        "enabled": True,
    },
    "zhipu": {
        "provider": "zhipu",
        "label": "智谱 AI",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4.5-air",
        "api_key": "",
        "enabled": True,
    },
    "ark": {
        "provider": "ark",
        "label": "火山引擎（豆包）",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "model": "doubao-seed-1-6-250615",
        "api_key": "",
        "enabled": True,
    },
    "openai": {
        "provider": "openai",
        "label": "国际通用接口",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4.1-mini",
        "api_key": "",
        "enabled": True,
    },
    "custom": {
        "provider": "custom",
        "label": "自定义兼容接口",
        "base_url": "",
        "model": "",
        "api_key": "",
        "enabled": True,
    },
}

_ZHIPU_MODEL_ALIASES = {
    "glm-4.5-air": "glm-4.5-air",
    "glm4.5air": "glm-4.5-air",
    "glm-4.5air": "glm-4.5-air",
    "glm_4_5_air": "glm-4.5-air",
    "glm-4.5-airx": "glm-4.5-airx",
    "glm-4.5-flash": "glm-4.5-flash",
    "glm-5": "glm-5",
    "glm-4.7": "glm-4.7",
}


def provider_defaults(provider: str | None) -> dict[str, Any]:
    key = str(provider or "mock").strip().lower() or "mock"
    return dict(_PROVIDER_DEFAULTS.get(key, _PROVIDER_DEFAULTS["custom"]))


def list_provider_presets() -> list[dict[str, Any]]:
    return [provider_defaults(key) for key in ["deepseek", "qwen", "zhipu", "ark", "openai", "custom", "mock"]]


def _mask_key(value: str | None) -> str:
    raw = str(value or "")
    if len(raw) <= 8:
        return "*" * len(raw)
    return f"{raw[:4]}{'*' * max(4, len(raw) - 8)}{raw[-4:]}"


def _normalize_provider_config(config: dict[str, Any]) -> dict[str, Any]:
    out = dict(config)
    provider = str(out.get("provider") or "mock").strip().lower() or "mock"
    out["provider"] = provider
    out["enabled"] = bool(out.get("enabled", provider != "mock"))
    out["timeout_seconds"] = int(out.get("timeout_seconds") or 60)
    out["temperature"] = float(out.get("temperature") if out.get("temperature") is not None else 0.2)
    out["max_tokens"] = int(out.get("max_tokens") or 600)
    out["base_url"] = str(out.get("base_url") or "").strip().rstrip("/")
    out["model"] = str(out.get("model") or "").strip()
    out["api_key"] = str(out.get("api_key") or "").strip()
    if provider == "zhipu":
        model_key = out["model"].lower().replace(" ", "").replace("_", "-")
        model_key = model_key.replace("--", "-")
        out["model"] = _ZHIPU_MODEL_ALIASES.get(model_key, model_key or provider_defaults("zhipu")["model"])
        if not out["base_url"]:
            out["base_url"] = provider_defaults("zhipu")["base_url"]
    return out


def load_runtime_llm_config() -> dict[str, Any]:
    row = db.get_system_setting(SETTING_KEY)
    if not row or not isinstance(row.get("value"), dict):
        return _normalize_provider_config(provider_defaults(str(settings.llm_provider or "mock")))
    saved = dict(row["value"])
    merged = provider_defaults(saved.get("provider"))
    merged.update(saved)
    return _normalize_provider_config(merged)


def _provider_env_key(provider: str) -> str:
    p = str(provider or "").strip().lower()
    if p == "zhipu":
        return str(settings.zhipu_api_key or settings.zai_api_key or settings.openai_api_key or "")
    if p == "deepseek":
        return str(settings.deepseek_api_key or settings.openai_api_key or "")
    if p == "qwen":
        return str(settings.qwen_api_key or settings.openai_api_key or "")
    if p == "ark":
        return str(settings.ark_api_key or settings.openai_api_key or "")
    if p in {"openai", "custom"}:
        return str(settings.openai_api_key or "")
    return ""


def _apply_env_fallback(cfg: dict[str, Any]) -> dict[str, Any]:
    out = dict(cfg)
    provider = str(out.get("provider") or "mock").strip().lower() or "mock"
    env_provider = str(settings.llm_provider or "mock").strip().lower() or "mock"
    env_provider_key = _provider_env_key(env_provider)

    if provider == "mock" and env_provider != "mock":
        base = provider_defaults(env_provider)
        return _normalize_provider_config(
            {
                **base,
                "provider": env_provider,
                "base_url": settings.openai_base_url or base.get("base_url") or "",
                "model": settings.openai_model or base.get("model") or "",
                "api_key": env_provider_key,
                "enabled": True,
                "timeout_seconds": int(out.get("timeout_seconds") or 60),
                "temperature": float(out.get("temperature") if out.get("temperature") is not None else 0.2),
                "max_tokens": int(out.get("max_tokens") or 600),
            }
        )

    if provider != env_provider and env_provider != "mock" and str(env_provider_key).strip():
        base = provider_defaults(env_provider)
        return _normalize_provider_config(
            {
                **base,
                "provider": env_provider,
                "base_url": settings.openai_base_url or base.get("base_url") or "",
                "model": settings.openai_model or base.get("model") or "",
                "api_key": env_provider_key,
                "enabled": True,
                "timeout_seconds": int(out.get("timeout_seconds") or 60),
                "temperature": float(out.get("temperature") if out.get("temperature") is not None else 0.2),
                "max_tokens": int(out.get("max_tokens") or 600),
            }
        )

    if not str(out.get("api_key") or "").strip():
        out["api_key"] = _provider_env_key(provider)

    if provider == env_provider:
        if not str(out.get("base_url") or "").strip() and str(settings.openai_base_url or "").strip():
            out["base_url"] = settings.openai_base_url or ""
        if not str(out.get("model") or "").strip() and str(settings.openai_model or "").strip():
            out["model"] = settings.openai_model or ""
    return _normalize_provider_config(out)


def load_effective_llm_config() -> dict[str, Any]:
    return _apply_env_fallback(load_runtime_llm_config())


def save_runtime_llm_config(config: dict[str, Any]) -> dict[str, Any]:
    previous = load_runtime_llm_config()
    provider = str(config.get("provider") or "custom").strip().lower()
    merged = provider_defaults(provider)
    incoming = {k: v for k, v in config.items() if v is not None}
    if "api_key" in incoming and not str(incoming.get("api_key") or "").strip() and str(previous.get("api_key") or "").strip():
        incoming.pop("api_key", None)
    merged.update(incoming)
    merged["provider"] = provider
    merged = _normalize_provider_config(merged)
    db.upsert_system_setting(SETTING_KEY, setting_json=json.dumps(merged, ensure_ascii=False), updated_at=now_iso())
    return merged


def runtime_llm_status(mask_secret: bool = True) -> dict[str, Any]:
    cfg = load_effective_llm_config()
    out = dict(cfg)
    if mask_secret:
        out["api_key"] = _mask_key(out.get("api_key"))
        out["has_api_key"] = bool(str(cfg.get("api_key") or "").strip())
    return out
