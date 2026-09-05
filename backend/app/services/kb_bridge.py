from __future__ import annotations

from typing import Any

from app.services.kb import search_kb


def _clean_query(text: str) -> str:
    return " ".join(str(text or "").strip().split())


def _unique_queries(queries: list[str], *, limit: int = 12) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in queries:
        q = _clean_query(raw)
        if len(q) < 2:
            continue
        key = q.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(q)
        if len(out) >= limit:
            break
    return out


def collect_kb_references(
    queries: list[str],
    *,
    per_query: int = 3,
    max_items: int = 8,
    min_score: float = 1e-6,
) -> list[dict[str, Any]]:
    """Search KB with multiple queries and merge deduplicated references."""

    merged: dict[str, dict[str, Any]] = {}

    for q in _unique_queries(queries):
        for item in search_kb(q, top_k=max(1, int(per_query))):
            try:
                score = float(item.get("score") or 0.0)
            except Exception:
                score = 0.0
            if score <= float(min_score):
                continue

            key = str(item.get("path") or item.get("doc_id") or "").strip() or f"doc::{len(merged)+1}"
            entry = merged.get(key)
            if not entry:
                entry = {
                    "doc_id": item.get("doc_id"),
                    "title": item.get("title"),
                    "path": item.get("path"),
                    "snippet": item.get("snippet"),
                    "score": score,
                    "matched_queries": [q],
                }
                merged[key] = entry
            else:
                if score > float(entry.get("score") or 0.0):
                    entry["score"] = score
                    if item.get("snippet"):
                        entry["snippet"] = item.get("snippet")
                    if item.get("title"):
                        entry["title"] = item.get("title")
                if q not in (entry.get("matched_queries") or []):
                    entry["matched_queries"] = list(entry.get("matched_queries") or []) + [q]

    items = list(merged.values())
    items.sort(key=lambda x: float(x.get("score") or 0.0), reverse=True)
    return items[: max(1, int(max_items))]

