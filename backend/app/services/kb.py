from __future__ import annotations

import os
import pickle
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from app.core.config import settings
from app.services.document_store import get_doc_store
from app.services.embedding_rerank import embed_texts, rerank_records
from app.utils.text import normalize_text


@dataclass
class TfidfKBIndex:
    vectorizer: TfidfVectorizer
    matrix: Any
    doc_ids: list[str]
    titles: list[str]
    paths: list[str]
    texts: list[str]


_kb_index: TfidfKBIndex | None = None


_ALLOWED_EXT = {".md", ".txt"}


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        try:
            return path.read_text(encoding="gbk", errors="ignore")
        except Exception:
            return ""


def _title_from_md(text: str, fallback: str) -> str:
    # Find first markdown heading
    for line in (text or "").splitlines():
        line = line.strip()
        if line.startswith("#"):
            return line.lstrip("#").strip() or fallback
    return fallback


def _scan_docs(kb_dir: str) -> list[tuple[str, str, str, str]]:
    """Return list of (doc_id, title, path, text)."""
    base = Path(kb_dir)
    if not base.exists():
        return []

    docs: list[tuple[str, str, str, str]] = []
    for p in base.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() not in _ALLOWED_EXT:
            continue
        rel = str(p.relative_to(base))
        text = _read_text(p)
        if not text.strip():
            continue
        title = _title_from_md(text, fallback=p.stem)
        doc_id = re.sub(r"[^a-zA-Z0-9_\-]", "_", rel)
        docs.append((doc_id, title, str(p), text))
    return docs


def build_kb_index(kb_dir: str | None = None) -> dict[str, Any]:
    """Build local TF-IDF index for knowledge base docs."""

    global _kb_index
    kb_dir = kb_dir or settings.kb_dir
    docs = _scan_docs(kb_dir)

    doc_ids: list[str] = []
    titles: list[str] = []
    paths: list[str] = []
    texts: list[str] = []

    for doc_id, title, path, text in docs:
        doc_ids.append(doc_id)
        titles.append(title)
        paths.append(path)
        texts.append(normalize_text(title + "\n" + text))

    vectorizer = TfidfVectorizer(analyzer="char", ngram_range=(2, 5), min_df=1)
    matrix = vectorizer.fit_transform(texts) if texts else None
    _kb_index = TfidfKBIndex(vectorizer=vectorizer, matrix=matrix, doc_ids=doc_ids, titles=titles, paths=paths, texts=texts)

    os.makedirs(os.path.dirname(settings.kb_vector_index_path), exist_ok=True)
    with open(settings.kb_vector_index_path, "wb") as f:
        pickle.dump(_kb_index, f)

    return {"count": len(doc_ids), "path": settings.kb_vector_index_path, "kb_dir": kb_dir}


def load_kb_index() -> bool:
    global _kb_index
    if _kb_index is not None:
        return True
    if not os.path.exists(settings.kb_vector_index_path):
        return False
    with open(settings.kb_vector_index_path, "rb") as f:
        _kb_index = pickle.load(f)
    return True


def _search_chunk_store(query: str, top_k: int = 5, enabled: bool = True) -> list[dict[str, Any]]:
    if not enabled:
        return []

    q_vec = embed_texts([query])[0]
    if not isinstance(q_vec, list) or not q_vec:
        return []

    try:
        rows = get_doc_store().search(q_vec, top_k=top_k)
    except Exception:
        return []

    out: list[dict[str, Any]] = []
    for idx, row in enumerate(rows):
        score = float(row.get("score") or 0.0)
        if score <= 1e-8:
            continue
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        text = str(row.get("text") or "")
        source = str(metadata.get("source") or metadata.get("path") or metadata.get("title") or "chunk_store")
        title = str(metadata.get("title") or metadata.get("source") or f"chunk_store:{idx + 1}")
        out.append(
            {
                "doc_id": f"chunk_store_{idx + 1}",
                "title": title,
                "path": source,
                "score": score,
                "tfidf_score": 0.0,
                "embedding_score": score,
                "snippet": text.strip().replace("\n", " ")[:220],
                "source_type": "chunk_store",
            }
        )
    return out


def search_kb(query: str, top_k: int = 5, use_embedding: bool = True) -> list[dict[str, Any]]:
    chunk_results = _search_chunk_store(query, top_k=top_k, enabled=use_embedding)

    if not load_kb_index():
        build_kb_index()
        load_kb_index()
    if _kb_index is None or _kb_index.matrix is None:
        return chunk_results[:top_k]

    q = normalize_text(query)
    qv = _kb_index.vectorizer.transform([q])
    sims = cosine_similarity(qv, _kb_index.matrix).flatten()
    top_n = max(top_k * 4, top_k)
    idxs = sims.argsort()[::-1][:top_n]

    candidates: list[dict[str, Any]] = []
    for i in idxs:
        idx = int(i)
        score = float(sims[idx])
        # Skip obvious near-zero noise in recall stage.
        if score <= 1e-8:
            continue
        candidates.append(
            {
                "_idx": idx,
                "doc_id": _kb_index.doc_ids[idx],
                "title": _kb_index.titles[idx],
                "path": _kb_index.paths[idx],
                "tfidf_score": score,
                "score": score,
            }
        )

    ranked, _ = rerank_records(
        query,
        candidates,
        text_getter=lambda item: _kb_index.texts[int(item["_idx"])],
        score_key="tfidf_score",
        top_k=top_k,
        enabled=use_embedding,
    )

    out: list[dict[str, Any]] = []
    for item in ranked:
        idx = int(item["_idx"])
        score = float(item.get("score") or 0.0)
        if score <= 1e-8:
            continue
        path = str(item.get("path") or _kb_index.paths[idx])
        snippet = ""
        try:
            raw = _read_text(Path(path))
            snippet = raw.strip().replace("\n", " ")[:220]
        except Exception:
            snippet = ""
        out.append(
            {
                "doc_id": item.get("doc_id") or _kb_index.doc_ids[idx],
                "title": item.get("title") or _kb_index.titles[idx],
                "path": path,
                "score": score,
                "tfidf_score": float(item.get("tfidf_score") or 0.0),
                "embedding_score": item.get("embedding_score"),
                "snippet": snippet,
                "source_type": "kb_dir",
            }
        )

    merged = [*out, *chunk_results]
    merged.sort(key=lambda item: float(item.get("score") or 0.0), reverse=True)
    return merged[:top_k]
