from __future__ import annotations

import json
import os
import pickle
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from app.core.config import settings
from app.db import sqlite as db
from app.services.embedding_rerank import rerank_records
from app.utils.text import normalize_text


@dataclass
class TfidfJobIndex:
    vectorizer: TfidfVectorizer
    matrix: Any
    job_ids: list[str]
    texts: list[str]


_job_index: TfidfJobIndex | None = None


def _export_job_vectors_json(index: TfidfJobIndex, jobs: list[dict[str, Any]], out_path: str) -> str:
    job_meta = {
        j.get("job_id"): {
            "title": j.get("title"),
            "industry": j.get("industry"),
            "location": j.get("location"),
            "salary": j.get("salary"),
        }
        for j in jobs
    }

    records: list[dict[str, Any]] = []
    if index.matrix is not None:
        for i, job_id in enumerate(index.job_ids):
            row = index.matrix.getrow(i)
            meta = job_meta.get(job_id, {})
            records.append(
                {
                    "job_id": job_id,
                    "title": meta.get("title"),
                    "industry": meta.get("industry"),
                    "location": meta.get("location"),
                    "salary": meta.get("salary"),
                    "vector": {
                        "indices": row.indices.tolist(),
                        "values": [float(v) for v in row.data.tolist()],
                    },
                }
            )

    payload = {
        "vector_backend": "tfidf",
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "feature_dim": int(index.matrix.shape[1]) if index.matrix is not None else 0,
        "record_count": len(records),
        "records": records,
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)

    return out_path


def build_job_index(limit: int = 5000) -> dict[str, Any]:
    """Build a local TFIDF index for job postings."""

    global _job_index
    db.init_db()

    jobs = db.list_jobs(limit=limit, offset=0)
    job_ids: list[str] = []
    texts: list[str] = []
    for j in jobs:
        job_ids.append(j["job_id"])
        full = " ".join(
            [
                j.get("title") or "",
                j.get("company_name") or "",
                j.get("industry") or "",
                (db.get_job(j["job_id"]) or {}).get("description") or "",
            ]
        )
        texts.append(normalize_text(full))

    vectorizer = TfidfVectorizer(analyzer="char", ngram_range=(2, 5), min_df=1)
    matrix = vectorizer.fit_transform(texts) if texts else None
    _job_index = TfidfJobIndex(vectorizer=vectorizer, matrix=matrix, job_ids=job_ids, texts=texts)

    os.makedirs(os.path.dirname(settings.job_vector_index_path), exist_ok=True)
    with open(settings.job_vector_index_path, "wb") as f:
        pickle.dump(_job_index, f)

    export_path = os.path.join(os.path.dirname(settings.job_vector_index_path), "job_vectors_export.json")
    _export_job_vectors_json(_job_index, jobs, export_path)

    return {
        "count": len(job_ids),
        "path": settings.job_vector_index_path,
        "export_json_path": export_path,
    }


def load_job_index() -> bool:
    global _job_index
    if _job_index is not None:
        return True
    if not os.path.exists(settings.job_vector_index_path):
        return False
    with open(settings.job_vector_index_path, "rb") as f:
        _job_index = pickle.load(f)
    return True


def search_jobs(query: str, top_k: int = 10, use_embedding: bool = True) -> list[dict[str, Any]]:
    db.init_db()
    if not load_job_index():
        build_job_index()
        load_job_index()
    if _job_index is None or _job_index.matrix is None:
        return []

    q = normalize_text(query)
    qv = _job_index.vectorizer.transform([q])
    sims = cosine_similarity(qv, _job_index.matrix).flatten()
    top_n = max(top_k * 4, top_k)
    idxs = sims.argsort()[::-1][:top_n]

    candidates: list[dict[str, Any]] = []
    for i in idxs:
        job_id = _job_index.job_ids[int(i)]
        j = db.get_job(job_id) or {}
        candidates.append(
            {
                "_idx": int(i),
                "job_id": job_id,
                "title": j.get("title"),
                "company_name": j.get("company_name"),
                "location": j.get("location"),
                "industry": j.get("industry"),
                "tfidf_score": float(sims[int(i)]),
                "score": float(sims[int(i)]),
            }
        )

    ranked, _ = rerank_records(
        query,
        candidates,
        text_getter=lambda item: _job_index.texts[int(item["_idx"])],
        score_key="tfidf_score",
        top_k=top_k,
        enabled=use_embedding,
    )

    out: list[dict[str, Any]] = []
    for item in ranked:
        out.append(
            {
                "job_id": item.get("job_id"),
                "title": item.get("title"),
                "company_name": item.get("company_name"),
                "location": item.get("location"),
                "industry": item.get("industry"),
                "score": float(item.get("score") or 0.0),
                "tfidf_score": float(item.get("tfidf_score") or 0.0),
                "embedding_score": item.get("embedding_score"),
            }
        )
    return out
