from __future__ import annotations

import re
import threading
from typing import Any

from app.services.dictionary_cache import dictionary_cache
from app.utils.text import normalize_text, normalize_token

try:
    import ahocorasick  # type: ignore
except Exception:  # pragma: no cover
    ahocorasick = None


_SENT_SPLIT_RE = re.compile(r"[\n。！？!?]+")

# Very short ASCII tokens tend to be ambiguous in Chinese texts.
_AMBIGUOUS_SHORT_ALIASES = {
    "go",
    "c",
    "r",
    "ai",
    "ui",
    "qa",
}

_auto_lock = threading.Lock()
_automata: dict[str, tuple[float, Any]] = {}  # item_type -> (snapshot_ts, automaton)


def split_sentences(text: str, max_len: int = 240) -> list[str]:
    text = normalize_text(text)
    parts = [p.strip() for p in _SENT_SPLIT_RE.split(text) if p.strip()]
    # Further split long parts.
    out: list[str] = []
    for p in parts:
        if len(p) <= max_len:
            out.append(p)
        else:
            chunks = [c.strip() for c in re.split(r"[,，;；、]", p) if c.strip()]
            out.extend(chunks if chunks else [p[:max_len]])
    return out


def _is_ascii_token(alias_norm: str) -> bool:
    # Consider token ASCII if it contains any ASCII letter/digit.
    return any(("a" <= ch <= "z") or ("0" <= ch <= "9") for ch in alias_norm)


def _boundary_ok(text_norm: str, start: int, end: int, alias_norm: str) -> bool:
    """For ASCII-ish aliases ensure we are not matching inside a longer token."""

    if not _is_ascii_token(alias_norm):
        return True

    before = text_norm[start - 1] if start > 0 else " "
    after = text_norm[end + 1] if end + 1 < len(text_norm) else " "

    def _is_word_char(ch: str) -> bool:
        return ch.isalnum() or ch in {"_", ".", "+", "#", "-"}

    return (not _is_word_char(before)) and (not _is_word_char(after))


def _get_automaton(item_type: str) -> Any | None:
    """Build (or reuse) an Aho-Corasick automaton for the given item_type."""

    if ahocorasick is None:
        return None
    snap = dictionary_cache.get_snapshot()
    with _auto_lock:
        cached = _automata.get(item_type)
        if cached and cached[0] == snap.ts:
            return cached[1]

        A = ahocorasick.Automaton()
        for alias_norm, it in snap.alias_to_item.items():
            if it.get("item_type") != item_type:
                continue
            if not alias_norm or len(alias_norm) <= 1:
                continue
            if alias_norm in _AMBIGUOUS_SHORT_ALIASES:
                continue
            # Store item_id to de-dup across aliases.
            A.add_word(alias_norm, (alias_norm, it.get("item_id")))
        A.make_automaton()
        _automata[item_type] = (snap.ts, A)
        return A


def extract_dictionary_mentions(
    text: str,
    item_type: str,
    section: str | None = None,
    max_hits: int = 80,
) -> list[dict[str, Any]]:
    """
    Extract mentions by scanning aliases (works well for tech stack / certificates).
    Returns list of items with evidence sentence.
    """

    snap = dictionary_cache.get_snapshot()
    sentences = split_sentences(text)
    found: dict[str, dict[str, Any]] = {}
    id_to_item = {it.get("item_id"): it for it in snap.items if it.get("item_id")}

    # Prefer Aho-Corasick for speed; fallback to substring scanning.
    A = _get_automaton(item_type)
    aliases: list[tuple[str, dict[str, Any]]] = []
    if A is None:
        # Pre-build once for fallback path.
        for alias_norm, it in snap.alias_to_item.items():
            if it.get("item_type") != item_type:
                continue
            if not alias_norm or len(alias_norm) <= 1:
                continue
            if alias_norm in _AMBIGUOUS_SHORT_ALIASES:
                continue
            aliases.append((alias_norm, it))

    for sent in sentences:
        sent_norm = normalize_token(sent)
        if not sent_norm:
            continue

        if A is not None:
            for end_idx, (alias_norm, item_id) in A.iter(sent_norm):
                if not item_id:
                    continue
                start_idx = end_idx - len(alias_norm) + 1
                if not _boundary_ok(sent_norm, start_idx, end_idx, alias_norm):
                    continue
                if item_id in found:
                    continue
                it = id_to_item.get(item_id)
                if not it:
                    continue
                found[item_id] = {**it, "evidence": sent, "section": section}
                if len(found) >= max_hits:
                    break
        else:
            # Fallback: scan aliases (slower but dependency-free).
            for alias_norm, it in aliases:
                pos = sent_norm.find(alias_norm)
                if pos >= 0:
                    if not _boundary_ok(sent_norm, pos, pos + len(alias_norm) - 1, alias_norm):
                        continue
                    item_id = it.get("item_id")
                    if item_id and item_id not in found:
                        found[item_id] = {**it, "evidence": sent, "section": section}
                        if len(found) >= max_hits:
                            break

        if len(found) >= max_hits:
            break

    out = list(found.values())
    out.sort(key=lambda x: (x.get("category_lv1") or "", x.get("name_zh") or ""))
    return out
