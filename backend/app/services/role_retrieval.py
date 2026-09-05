from __future__ import annotations

import os
import pickle
from dataclasses import dataclass
from typing import Any

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from app.core.config import settings
from app.db import sqlite as db
from app.services.embedding_rerank import rerank_records
from app.utils.text import normalize_text


@dataclass
class TfidfRoleIndex:
    vectorizer: TfidfVectorizer
    matrix: Any
    role_ids: list[str]
    texts: list[str]


_role_index: TfidfRoleIndex | None = None


def build_role_index(limit: int = 5000) -> dict[str, Any]:
    """Build a role-level retrieval index.

    This complements job-level search:
      - roles: stable, ~100 nodes, good for "career exploration"
      - jobs: 10k postings, good for concrete opportunities
    """

    global _role_index
    db.init_db()

    roles = db.list_roles(limit=limit, offset=0)
    role_ids: list[str] = []
    texts: list[str] = []
    for r in roles:
        rid = r["role_id"]
        rp = db.get_role_profile(rid)
        skills = []
        if rp:
            for it in (rp["profile"].get("top_hard_skills") or [])[:30]:
                skills.append(it.get("name") or it.get("skill_id"))
        full = " ".join(
            [
                r.get("title_rep") or "",
                r.get("job_family") or "",
                r.get("base_role") or "",
                r.get("level_label") or "",
                " ".join([s for s in skills if s]),
            ]
        )
        role_ids.append(rid)
        texts.append(normalize_text(full))

    vectorizer = TfidfVectorizer(analyzer="char", ngram_range=(2, 5), min_df=1)
    matrix = vectorizer.fit_transform(texts) if texts else None
    _role_index = TfidfRoleIndex(vectorizer=vectorizer, matrix=matrix, role_ids=role_ids, texts=texts)

    os.makedirs(os.path.dirname(settings.role_vector_index_path), exist_ok=True)
    with open(settings.role_vector_index_path, "wb") as f:
        pickle.dump(_role_index, f)

    return {"count": len(role_ids), "path": settings.role_vector_index_path}


def load_role_index() -> bool:
    global _role_index
    if _role_index is not None:
        return True
    if not os.path.exists(settings.role_vector_index_path):
        return False
    with open(settings.role_vector_index_path, "rb") as f:
        _role_index = pickle.load(f)
    return True


def search_roles(query: str, top_k: int = 10, use_embedding: bool = True) -> list[dict[str, Any]]:
    db.init_db()
    if not load_role_index():
        build_role_index()
        load_role_index()
    if _role_index is None or _role_index.matrix is None:
        return []

    q = normalize_text(query)
    qv = _role_index.vectorizer.transform([q])
    sims = cosine_similarity(qv, _role_index.matrix).flatten()
    q_text = q.lower()
    keyword_bonus: list[tuple[str, float]] = [
        ("前端", 0.24),
        ("测试", 0.24),
        ("后端", 0.22),
        ("算法", 0.22),
        ("产品", 0.18),
        ("运维", 0.18),
    ]

    candidates: list[dict[str, Any]] = []
    idxs = sims.argsort()[::-1][: max(top_k * 4, top_k)]
    for i in idxs:
        idx = int(i)
        rid = _role_index.role_ids[int(i)]
        r = db.get_role(rid) or {}
        title = str(r.get("title_rep") or "")
        base = str(r.get("base_role") or "")
        family = str(r.get("job_family") or "")
        role_text = f"{title} {base} {family}".lower()
        bonus = 0.0
        for kw, w in keyword_bonus:
            if kw in q_text and kw in role_text:
                bonus += w
        base_score = float(sims[idx])
        score_before_rerank = base_score + bonus
        candidates.append(
            {
                "_idx": idx,
                "role_id": rid,
                "title": title,
                "job_family": r.get("job_family"),
                "level_label": r.get("level_label"),
                "base_score": base_score,
                "keyword_bonus": bonus,
                "score_before_rerank": score_before_rerank,
                "score": score_before_rerank,
            }
        )

    ranked, _ = rerank_records(
        query,
        candidates,
        text_getter=lambda item: _role_index.texts[int(item["_idx"])],
        score_key="score_before_rerank",
        top_k=top_k,
        enabled=use_embedding,
    )

    out: list[dict[str, Any]] = []
    for item in ranked:
        out.append(
            {
                "role_id": item.get("role_id"),
                "title": item.get("title"),
                "job_family": item.get("job_family"),
                "level_label": item.get("level_label"),
                "score": float(item.get("score") or 0.0),
                "base_score": float(item.get("base_score") or 0.0),
                "keyword_bonus": float(item.get("keyword_bonus") or 0.0),
                "embedding_score": item.get("embedding_score"),
            }
        )
    return out
