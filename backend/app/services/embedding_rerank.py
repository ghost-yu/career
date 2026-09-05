from __future__ import annotations

import hashlib
import os
from collections import deque
from typing import Any, Callable

import httpx
import openai

from app.core.config import settings
from app.services.llm_runtime import load_effective_llm_config

_EMBED_MODEL = "embedding-3"
_CACHE_MAX = 4000

_emb_cache: dict[str, list[float]] = {}
_emb_cache_order: deque[str] = deque()

_client: openai.OpenAI | None = None
_client_key: str = ""
_client_base_url: str = ""


def _sanitize_text(text: Any, max_len: int = 1800) -> str:
    raw = " ".join(str(text or "").replace("\x00", " ").split())
    if len(raw) > max_len:
        return raw[:max_len]
    return raw


def _cache_key(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()


def _cache_get(text: str) -> list[float] | None:
    return _emb_cache.get(_cache_key(text))


def _cache_put(text: str, vec: list[float]) -> None:
    key = _cache_key(text)
    if key in _emb_cache:
        return
    _emb_cache[key] = vec
    _emb_cache_order.append(key)
    while len(_emb_cache_order) > _CACHE_MAX:
        old = _emb_cache_order.popleft()
        _emb_cache.pop(old, None)


def _resolve_key() -> str:
    return str(
        os.getenv("ZHIPU_API_KEY")
        or os.getenv("ZAI_API_KEY")
        or settings.zhipu_api_key
        or settings.zai_api_key
        or ""
    ).strip()


def _resolve_base_url() -> str:
    cfg = load_effective_llm_config()
    if str(cfg.get("provider") or "").strip().lower() == "zhipu":
        base_url = str(cfg.get("base_url") or "").strip().rstrip("/")
        if base_url:
            return f"{base_url}/"
    return "https://open.bigmodel.cn/api/paas/v4/"


def _get_client() -> openai.OpenAI | None:
    global _client
    global _client_key
    global _client_base_url

    key = _resolve_key()
    if not key:
        return None
    base_url = _resolve_base_url()
    if _client is not None and key == _client_key and base_url == _client_base_url:
        return _client

    _client = openai.OpenAI(
        api_key=key,
        base_url=base_url,
        http_client=httpx.Client(timeout=25.0, trust_env=False, verify=False),
    )
    _client_key = key
    _client_base_url = base_url
    return _client


def _embed_batch(client: openai.OpenAI, texts: list[str]) -> list[list[float] | None]:
    if not texts:
        return []
    try:
        res = client.embeddings.create(model=_EMBED_MODEL, input=texts)
        out: list[list[float] | None] = []
        for item in (res.data or []):
            emb = getattr(item, "embedding", None)
            if isinstance(emb, list) and emb:
                out.append([float(x) for x in emb])
            else:
                out.append(None)
        if len(out) == len(texts):
            return out
        if len(out) < len(texts):
            out.extend([None] * (len(texts) - len(out)))
        return out[: len(texts)]
    except Exception:
        if len(texts) <= 1:
            return [None]
        out: list[list[float] | None] = []
        for t in texts:
            out.extend(_embed_batch(client, [t]))
        return out


def embed_texts(texts: list[str]) -> list[list[float] | None]:
    if not texts:
        return []

    sanitized = [_sanitize_text(t) for t in texts]
    out: list[list[float] | None] = [None] * len(sanitized)

    missing_texts: list[str] = []
    missing_indices: list[int] = []
    for i, text in enumerate(sanitized):
        if not text:
            continue
        cached = _cache_get(text)
        if cached is not None:
            out[i] = cached
            continue
        missing_indices.append(i)
        missing_texts.append(text)

    if not missing_texts:
        return out

    client = _get_client()
    if client is None:
        return out

    batch_size = 16
    for start in range(0, len(missing_texts), batch_size):
        batch_texts = missing_texts[start : start + batch_size]
        batch_indices = missing_indices[start : start + batch_size]
        batch_out = _embed_batch(client, batch_texts)
        for idx, vec, text in zip(batch_indices, batch_out, batch_texts):
            if isinstance(vec, list) and vec:
                out[idx] = vec
                _cache_put(text, vec)

    return out


def cosine(v1: list[float], v2: list[float]) -> float:
    if not v1 or not v2:
        return 0.0
    n = min(len(v1), len(v2))
    if n <= 0:
        return 0.0
    dot = 0.0
    n1 = 0.0
    n2 = 0.0
    for i in range(n):
        a = float(v1[i])
        b = float(v2[i])
        dot += a * b
        n1 += a * a
        n2 += b * b
    if n1 <= 0.0 or n2 <= 0.0:
        return 0.0
    return dot / ((n1 ** 0.5) * (n2 ** 0.5))


def rerank_records(
    query: str,
    records: list[dict[str, Any]],
    *,
    text_getter: Callable[[dict[str, Any]], str],
    score_key: str = "score",
    top_k: int = 10,
    alpha: float = 0.45,
    enabled: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not records:
        return [], {"enabled": False, "reason": "empty_records"}
    if not enabled:
        return records[:top_k], {"enabled": False, "reason": "disabled"}

    q_vec = embed_texts([query])[0]
    if not isinstance(q_vec, list) or not q_vec:
        return records[:top_k], {"enabled": False, "reason": "query_embedding_unavailable"}

    texts = [text_getter(r) for r in records]
    emb_list = embed_texts(texts)

    base_scores = [float(r.get(score_key) or 0.0) for r in records]
    min_base = min(base_scores)
    max_base = max(base_scores)

    ranked: list[dict[str, Any]] = []
    embedded_candidates = 0
    for rec, base, vec in zip(records, base_scores, emb_list):
        if max_base > min_base:
            base_norm = (base - min_base) / (max_base - min_base)
        else:
            base_norm = 0.5

        emb_raw: float | None = None
        emb_norm: float | None = None
        if isinstance(vec, list) and vec:
            embedded_candidates += 1
            emb_raw = cosine(q_vec, vec)
            emb_norm = max(0.0, min(1.0, (emb_raw + 1.0) / 2.0))

        if emb_norm is None:
            final_score = base
        else:
            final_score = alpha * base_norm + (1.0 - alpha) * emb_norm

        item = dict(rec)
        item["score"] = float(final_score)
        item["embedding_score"] = emb_raw
        ranked.append(item)

    ranked.sort(key=lambda x: float(x.get("score") or 0.0), reverse=True)
    return ranked[:top_k], {
        "enabled": True,
        "query_embedded": True,
        "candidate_embedded": embedded_candidates,
        "alpha": alpha,
    }
