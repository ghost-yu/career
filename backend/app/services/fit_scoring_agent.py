from __future__ import annotations

import json
import re
from typing import Any

from app.db import sqlite as db
from app.services.kb_bridge import collect_kb_references
from app.services.llm import llm_client
from app.services.resume_file_extract import extract_resume_text_smart
from app.services.scoring import score
from app.utils.text import normalize_text

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.#/-]{1,}|[\u4e00-\u9fff]{2,}")


def _safe_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    return []


def _extract_keywords(text: str, *, limit: int = 40) -> list[str]:
    counts: dict[str, int] = {}
    for token in _TOKEN_RE.findall(text or ""):
        k = normalize_text(token).strip().lower()
        if len(k) < 2:
            continue
        counts[k] = int(counts.get(k, 0)) + 1
    ranked = sorted(counts.items(), key=lambda x: (x[1], x[0]), reverse=True)
    return [k for k, _ in ranked[:limit]]


def _keyword_overlap_score(resume_text: str, job_text: str) -> tuple[int, list[str], list[str]]:
    resume_kw = set(_extract_keywords(resume_text, limit=80))
    job_kw = _extract_keywords(job_text, limit=60)
    if not job_kw:
        return 5, [], []
    matched = [kw for kw in job_kw if kw in resume_kw]
    missing = [kw for kw in job_kw if kw not in resume_kw]
    ratio = len(matched) / max(1, len(job_kw))
    score_10 = max(1, min(10, int(round(ratio * 10))))
    return score_10, matched[:20], missing[:20]


def _candidate_skill_names(candidate_top20: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for item in candidate_top20[:20]:
        name = str(item.get("name") or item.get("skill_id") or "").strip()
        if name:
            out.append(name)
    return out


def _kb_context_for_fit(
    *,
    job_title: str,
    overlap_missing: list[str],
    candidate_top20: list[dict[str, Any]],
    missing_keywords: list[str] | None = None,
) -> list[dict[str, Any]]:
    queries: list[str] = []
    if job_title:
        queries.append(job_title)
    queries.extend(overlap_missing[:4])
    queries.extend(_candidate_skill_names(candidate_top20)[:3])
    if missing_keywords:
        queries.extend([str(x) for x in missing_keywords[:4] if str(x).strip()])
    return collect_kb_references(queries, per_query=2, max_items=10)


def _latest_resume_text(student_id: str) -> str:
    files = db.list_student_files(student_id) or []
    if not files:
        return ""
    latest = sorted(files, key=lambda x: str(x.get("created_at") or ""), reverse=True)[0]
    path = str(latest.get("path") or "")
    if not path:
        return ""
    text, _source = extract_resume_text_smart(path, filename=str(latest.get("filename") or ""))
    return normalize_text(text)


def _normalize_ai_score(raw: dict[str, Any] | None, fallback_10: int) -> dict[str, Any]:
    data = raw or {}
    try:
        fit_score_10 = int(data.get("fit_score_10"))
    except Exception:
        fit_score_10 = int(fallback_10)
    fit_score_10 = max(1, min(10, fit_score_10))

    fit_label = str(data.get("fit_label") or "").strip().lower()
    if fit_label not in {"strong", "good", "moderate", "weak", "poor"}:
        if fit_score_10 >= 9:
            fit_label = "strong"
        elif fit_score_10 >= 7:
            fit_label = "good"
        elif fit_score_10 >= 5:
            fit_label = "moderate"
        elif fit_score_10 >= 3:
            fit_label = "weak"
        else:
            fit_label = "poor"

    try:
        confidence = float(data.get("confidence"))
    except Exception:
        confidence = 0.6
    confidence = max(0.0, min(1.0, confidence))

    matched_keywords = [str(x).strip() for x in _safe_list(data.get("matched_keywords")) if str(x).strip()]
    missing_keywords = [str(x).strip() for x in _safe_list(data.get("missing_keywords")) if str(x).strip()]
    next_actions = [str(x).strip() for x in _safe_list(data.get("next_actions")) if str(x).strip()]

    return {
        "fit_score_10": fit_score_10,
        "fit_label": fit_label,
        "confidence": round(confidence, 3),
        "matched_keywords": matched_keywords[:20],
        "missing_keywords": missing_keywords[:20],
        "reasoning": normalize_text(str(data.get("reasoning") or "")),
        "next_actions": next_actions[:8],
    }


def score_fit_with_ai(body: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = body or {}
    student_id = str(payload.get("student_id") or "").strip()
    job_id = str(payload.get("job_id") or "").strip()
    resume_text = normalize_text(str(payload.get("resume_text") or ""))
    job_title = normalize_text(str(payload.get("job_title") or ""))
    job_description = normalize_text(str(payload.get("job_description") or ""))

    base_score_100: float | None = None
    candidate_top20: list[dict[str, Any]] = []
    student_profile: dict[str, Any] = {}
    job_profile: dict[str, Any] = {}
    job_meta: dict[str, Any] = {}

    if student_id and not resume_text:
        resume_text = _latest_resume_text(student_id)

    if student_id and job_id:
        score_result = score(student_id, job_id, use_cache=bool(payload.get("use_cache", True))).model_dump()
        try:
            base_score_100 = float(score_result.get("overall_score"))
        except Exception:
            base_score_100 = None
        candidate_top20 = _safe_list((((score_result.get("dimension_scores") or {}).get("skills") or {}).get("llm_candidate_top20")))
        student_profile = (db.get_student_profile(student_id) or {}).get("profile") or {}
        job_profile = (db.get_job_profile(job_id) or {}).get("profile") or {}
        job_meta = db.get_job(job_id) or {}
        if not job_title:
            job_title = normalize_text(str(job_meta.get("title") or ""))
        if not job_description:
            job_description = normalize_text(str(job_meta.get("description") or ""))

    if not resume_text:
        raise ValueError("resume_text_required")
    if not job_description and not job_title and not job_profile:
        raise ValueError("job_context_required")

    fallback_10_from_100 = int(round((base_score_100 or 50.0) / 10.0))
    overlap_score_10, overlap_matched, overlap_missing = _keyword_overlap_score(
        resume_text,
        "\n".join(
            [
                job_title,
                job_description,
                "\n".join(str(x.get("name") or x.get("mention") or "") for x in _safe_list(job_profile.get("hard_skills"))),
            ]
        ).strip(),
    )
    fallback_10 = max(1, min(10, int(round((fallback_10_from_100 * 0.6) + (overlap_score_10 * 0.4)))))
    kb_context = _kb_context_for_fit(
        job_title=job_title,
        overlap_missing=overlap_missing,
        candidate_top20=candidate_top20,
    )

    llm_result: dict[str, Any] | None = None
    if llm_client.is_enabled():
        score_payload = {
            "student": {
                "student_id": student_id or None,
                "profile": {
                    "hard_skills": [
                        str(x.get("mention") or x.get("name") or "").strip()
                        for x in _safe_list(student_profile.get("hard_skills"))
                        if str(x.get("mention") or x.get("name") or "").strip()
                    ][:30],
                    "soft_skills": [
                        str(x.get("name") or x.get("mention") or "").strip()
                        for x in _safe_list(student_profile.get("soft_skills"))
                        if str(x.get("name") or x.get("mention") or "").strip()
                    ][:20],
                    "certificates": [
                        str(x.get("name") or x.get("mention") or "").strip()
                        for x in _safe_list(student_profile.get("certificates"))
                        if str(x.get("name") or x.get("mention") or "").strip()
                    ][:12],
                    "experience": student_profile.get("experience") or {},
                },
                "resume_text": resume_text[:18000],
            },
            "target_job": {
                "job_id": job_id or None,
                "title": job_title,
                "description": job_description[:12000],
                "job_profile": job_profile,
            },
            "candidate_hard_skills_top20": candidate_top20[:20],
            "baseline": {
                "score_100": base_score_100,
                "fallback_score_10": fallback_10,
                "overlap_matched": overlap_matched[:20],
                "overlap_missing": overlap_missing[:20],
            },
            "kb_context": kb_context[:6],
        }
        system = """You are an ATS fit scoring agent.
Return STRICT JSON only:
{
  "fit_score_10": 1-10,
  "fit_label": "strong|good|moderate|weak|poor",
  "confidence": 0.0-1.0,
  "matched_keywords": ["string"],
  "missing_keywords": ["string"],
  "reasoning": "2-4 concise sentences",
  "next_actions": ["string"]
}
Rules:
1) Be conservative and realistic.
2) Never fabricate skills or experiences.
3) Prioritize candidate_hard_skills_top20 and target job requirements.
4) If information is incomplete, lower confidence and state that in reasoning.
5) When useful, leverage kb_context for learning actions; do not invent non-existing docs.
"""
        try:
            llm_result = llm_client.chat_json_sync(
                system,
                json.dumps(score_payload, ensure_ascii=False),
                trace_context="fit_scoring_agent.score",
            )
        except Exception:
            llm_result = None

    normalized = _normalize_ai_score(llm_result, fallback_10=fallback_10)
    if not normalized["matched_keywords"]:
        normalized["matched_keywords"] = overlap_matched[:20]
    if not normalized["missing_keywords"]:
        normalized["missing_keywords"] = overlap_missing[:20]
    final_kb_refs = _kb_context_for_fit(
        job_title=job_title,
        overlap_missing=overlap_missing,
        candidate_top20=candidate_top20,
        missing_keywords=normalized["missing_keywords"],
    )

    return {
        "ok": True,
        "student_id": student_id or None,
        "job_id": job_id or None,
        "job_title": job_title,
        "base_score_100": base_score_100,
        "llm_used": bool(llm_result),
        "candidate_hard_skills_top20": candidate_top20[:20],
        "kb_references": final_kb_refs,
        **normalized,
    }
