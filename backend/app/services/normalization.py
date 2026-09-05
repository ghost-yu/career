from __future__ import annotations

import math
import threading
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from app.services.dictionary_cache import dictionary_cache
from app.utils.text import normalize_text, normalize_token


@dataclass
class VectorIndex:
    item_type: str
    vectorizer: TfidfVectorizer
    matrix: Any  # sparse
    items: list[dict[str, Any]]


_index_lock = threading.Lock()
_indexes: dict[str, VectorIndex] = {}


def _build_index(item_type: str) -> VectorIndex:
    items = dictionary_cache.list_by_type(item_type)
    texts: list[str] = []
    for it in items:
        parts = [it.get("name_zh") or ""]
        if it.get("name_en"):
            parts.append(it["name_en"])
        parts.extend(it.get("aliases") or [])
        parts.append(it.get("description") or "")
        texts.append(" ".join(parts))
    vectorizer = TfidfVectorizer(analyzer="char", ngram_range=(2, 4), min_df=1)
    matrix = vectorizer.fit_transform(texts) if texts else None
    return VectorIndex(item_type=item_type, vectorizer=vectorizer, matrix=matrix, items=items)


def get_index(item_type: str, force_rebuild: bool = False) -> VectorIndex:
    with _index_lock:
        if force_rebuild or item_type not in _indexes:
            _indexes[item_type] = _build_index(item_type)
        return _indexes[item_type]


def normalize_to_item(
    mention: str,
    item_type: str,
    top_k: int = 5,
    threshold: float = 0.78,
) -> dict[str, Any] | None:
    """
    Map a free-text mention to dictionary item via:
    1) alias exact
    2) tf-idf char ngram semantic match
    """
    if not mention:
        return None
    # 1) alias exact
    it = dictionary_cache.lookup_by_alias(mention)
    if it and it["item_type"] == item_type:
        return {
            "item_id": it["item_id"],
            "name_zh": it["name_zh"],
            "confidence": 0.96,
            "mapping_method": "alias_exact",
        }

    # 2) semantic
    idx = get_index(item_type)
    if idx.matrix is None or not idx.items:
        return None
    q = normalize_text(mention)
    q_vec = idx.vectorizer.transform([q])
    sims = cosine_similarity(q_vec, idx.matrix).flatten()
    # get topk
    top = sims.argsort()[::-1][:top_k]
    best_i = int(top[0]) if len(top) else -1
    if best_i < 0:
        return None
    best_sim = float(sims[best_i])
    if best_sim < threshold:
        return None
    best = idx.items[best_i]
    return {
        "item_id": best["item_id"],
        "name_zh": best["name_zh"],
        "confidence": best_sim,
        "mapping_method": "semantic",
    }
