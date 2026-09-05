from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from fastapi import APIRouter

from app.db import sqlite as db
from app.services.behavior_recommend import (
    build_student_behavior_profile,
    normalize_strategy,
    record_student_event,
    rerank_job_items,
    rerank_role_items,
)
from app.services.g_rank_migration import recommend_jobs_g_rank
from app.services.fit_scoring_agent import score_fit_with_ai
from app.services.llm import llm_client
from app.services.match_analysis import build_match_ai_analysis
from app.services.profile_snapshot import build_student_profile_snapshot
from app.services.retrieval import search_jobs
from app.services.role_retrieval import search_roles
from app.services.scoring import score
from app.services.student_profile import build_student_profile_from_manual, generate_student_profile_from_latest_resume
from app.utils.labels import enrich_job_labels, enrich_role_labels
from app.utils.ids import now_iso
from app.utils.text import normalize_token

router = APIRouter()
logger = logging.getLogger(__name__)


_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.#/_-]{1,}|[\u4e00-\u9fff]{2,}")


def _norm_text(value: Any) -> str:
    return str(value or "").strip().lower()


def _tokenize(value: Any) -> list[str]:
    text = _norm_text(value)
    if not text:
        return []
    return [token for token in _TOKEN_RE.findall(text) if token]


def _pick_terms(values: list[Any], *, limit: int = 24) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        for token in _tokenize(value):
            if token in seen:
                continue
            seen.add(token)
            out.append(token)
            if len(out) >= limit:
                return out
    return out


def _strict_query_tokens(value: Any, *, limit: int = 8) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for token in _tokenize(text):
        nt = normalize_token(token)
        if not nt or nt in seen:
            continue
        seen.add(nt)
        out.append(nt)
        if len(out) >= limit:
            break
    return out


def _strict_query_match(text: str, tokens: list[str]) -> bool:
    if not tokens:
        return True
    hay = normalize_token(text)
    if not hay:
        return False
    hits = sum(1 for tk in tokens if tk and tk in hay)
    need = 1 if len(tokens) <= 1 else min(2, len(tokens))
    return hits >= need


def _weighted_overlap(text: str, terms: list[str], *, cap: int = 12) -> float:
    if not text or not terms:
        return 0.0
    score = 0.0
    for term in terms:
        if term and term in text:
            score += 1.0
            if score >= cap:
                return float(cap)
    return score


def _student_signal_terms(student_profile: dict[str, Any], q: str | None) -> dict[str, Any]:
    hard_terms = _pick_terms(
        [
            item.get("mention") or item.get("name")
            for item in (student_profile.get("hard_skills") or [])[:18]
        ],
        limit=26,
    )
    soft_terms = _pick_terms(
        [item.get("name") for item in (student_profile.get("soft_skills") or [])[:10]],
        limit=10,
    )
    query_terms = _pick_terms([q or ""], limit=8)
    pref = student_profile.get("preferences") or {}
    preferred_families = [str(x).strip().lower() for x in (pref.get("preferred_job_families") or []) if str(x).strip()]
    preferred_locations = [str(x).strip().lower() for x in (pref.get("preferred_locations") or []) if str(x).strip()]
    return {
        "hard_terms": hard_terms,
        "soft_terms": soft_terms,
        "query_terms": query_terms,
        "preferred_families": preferred_families,
        "preferred_locations": preferred_locations,
    }


def _student_hard_skill_count(student_profile: dict[str, Any]) -> int:
    count = 0
    for item in student_profile.get("hard_skills") or []:
        term = str(item.get("mention") or item.get("name") or item.get("skill_id") or "").strip()
        if term:
            count += 1
    return count


def _hard_skill_presence_adjust(student_hard_count: int, target_hard_count: int) -> float:
    stu = max(0, int(student_hard_count))
    tgt = max(0, int(target_hard_count))
    if stu <= 0:
        if tgt <= 0:
            return 10.0
        if tgt <= 2:
            return 4.0
        if tgt <= 5:
            return -2.0
        return -8.0
    if tgt <= 0:
        return -6.0
    if tgt <= 2:
        return -1.5
    return min(7.5, float(tgt) * 1.1)


def _clamp_location_weight(value: Any, *, default: float = 1.0) -> float:
    try:
        w = float(value)
    except Exception:
        w = default
    if w < 0.0:
        return 0.0
    if w > 2.0:
        return 2.0
    return w


def _clamp_ratio(value: Any, *, default: float = 0.35) -> float:
    try:
        w = float(value)
    except Exception:
        w = default
    if w < 0.0:
        return 0.0
    if w > 1.0:
        return 1.0
    return w


def _clamp_ai_rerank_top_n(value: Any, *, default: int = 20) -> int:
    try:
        n = int(value)
    except Exception:
        n = default
    if n < 1:
        return 1
    if n > 50:
        return 50
    return n


def _normalize_score_map(score_map: dict[str, float]) -> dict[str, float]:
    if not score_map:
        return {}
    max_score = max(float(v or 0.0) for v in score_map.values())
    if max_score <= 0:
        return {}
    return {k: max(0.0, float(v or 0.0) / max_score) for k, v in score_map.items() if float(v or 0.0) > 0}


def _build_recall_queries(signals: dict[str, Any], q: str | None, *, max_terms: int = 5) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()

    def _push(raw: Any) -> None:
        text = str(raw or "").strip()
        if not text:
            return
        key = text.lower()
        if key in seen:
            return
        seen.add(key)
        out.append(text)

    _push(q)
    hard_terms = [str(x).strip() for x in (signals.get("hard_terms") or []) if str(x).strip()]
    for term in hard_terms[: max(1, int(max_terms))]:
        _push(term)
    if q and hard_terms:
        _push(f"{q} {' '.join(hard_terms[:2])}")
    if not out and hard_terms:
        _push(" ".join(hard_terms[:3]))
    return out[: max(2, max_terms + 1)]


def _role_vector_recall_scores(signals: dict[str, Any], q: str | None, *, top_k_each: int = 120) -> dict[str, float]:
    queries = _build_recall_queries(signals, q, max_terms=4)
    if not queries:
        return {}
    score_map: dict[str, float] = {}
    k = max(20, min(320, int(top_k_each)))
    for query in queries:
        try:
            rows = search_roles(query, top_k=k, use_embedding=False)
        except Exception:
            rows = []
        for rank, row in enumerate(rows):
            role_id = str(row.get("role_id") or "").strip()
            if not role_id:
                continue
            base = float(row.get("score") or row.get("base_score") or 0.0)
            rank_gain = max(0.0, 1.0 - (rank / max(1.0, float(k))))
            merged = base * 0.75 + rank_gain * 0.25
            if merged > float(score_map.get(role_id) or 0.0):
                score_map[role_id] = merged
    return _normalize_score_map(score_map)


def _job_vector_recall_scores(signals: dict[str, Any], q: str | None, *, top_k_each: int = 220) -> dict[str, float]:
    queries = _build_recall_queries(signals, q, max_terms=5)
    if not queries:
        return {}
    score_map: dict[str, float] = {}
    k = max(30, min(520, int(top_k_each)))
    for query in queries:
        try:
            rows = search_jobs(query, top_k=k, use_embedding=False)
        except Exception:
            rows = []
        for rank, row in enumerate(rows):
            job_id = str(row.get("job_id") or "").strip()
            if not job_id:
                continue
            base = float(row.get("score") or row.get("tfidf_score") or 0.0)
            rank_gain = max(0.0, 1.0 - (rank / max(1.0, float(k))))
            merged = base * 0.72 + rank_gain * 0.28
            if merged > float(score_map.get(job_id) or 0.0):
                score_map[job_id] = merged
    return _normalize_score_map(score_map)


def _coarse_role_score(role: dict[str, Any], signals: dict[str, Any]) -> float:
    title_text = _norm_text(
        " ".join(
            [
                str(role.get("title_rep") or ""),
                str(role.get("base_role") or ""),
                str(role.get("role_key") or ""),
                str(role.get("job_family") or ""),
            ]
        )
    )
    score = 0.0
    score += _weighted_overlap(title_text, signals.get("query_terms") or [], cap=8) * 3.2
    score += _weighted_overlap(title_text, signals.get("hard_terms") or [], cap=10) * 2.0
    if signals.get("preferred_families") and _norm_text(role.get("job_family")) in set(signals["preferred_families"]):
        score += 20.0
    return score


def _refined_role_score(
    role: dict[str, Any],
    role_profile: dict[str, Any] | None,
    signals: dict[str, Any],
    *,
    student_hard_count: int,
) -> float:
    score = _coarse_role_score(role, signals)
    profile = (role_profile or {}).get("profile") or {}
    top_hard_skills = profile.get("top_hard_skills") or []
    role_hard_count = len([x for x in top_hard_skills if str(x.get("name") or x.get("mention") or x.get("skill_id") or "").strip()])
    hard_skill_text = _norm_text(
        " ".join(
            [
                str(item.get("name") or item.get("mention") or item.get("skill_id") or "")
                for item in top_hard_skills[:18]
            ]
        )
    )
    score += _weighted_overlap(hard_skill_text, signals.get("hard_terms") or [], cap=12) * 2.6
    score += _weighted_overlap(hard_skill_text, signals.get("query_terms") or [], cap=6) * 2.2
    score += _hard_skill_presence_adjust(student_hard_count, role_hard_count)
    return score


def _pick_representative_job_id(
    members: list[str],
    signals: dict[str, Any],
    *,
    max_scan: int = 8,
    location_weight: float = 1.0,
) -> tuple[str, dict[str, Any]]:
    best_job_id = ""
    best_job: dict[str, Any] = {}
    best_score = -1.0
    for job_id in members[: max(1, int(max_scan))]:
        job = db.get_job(job_id) or {}
        text = _norm_text(
            " ".join(
                [
                    str(job.get("title") or ""),
                    str(job.get("company_name") or ""),
                    str(job.get("location") or ""),
                    str(job.get("description") or "")[:1400],
                ]
            )
        )
        s = 0.0
        s += _weighted_overlap(text, signals.get("query_terms") or [], cap=6) * 3.0
        s += _weighted_overlap(text, signals.get("hard_terms") or [], cap=12) * 1.9
        if signals.get("preferred_locations"):
            loc = _norm_text(job.get("location"))
            for pref_loc in signals["preferred_locations"]:
                if pref_loc and pref_loc in loc:
                    s += 4.0 * max(0.0, float(location_weight))
                    break
        if s > best_score:
            best_score = s
            best_job_id = str(job_id)
            best_job = job
    if not best_job_id and members:
        best_job_id = str(members[0])
        best_job = db.get_job(best_job_id) or {}
    return best_job_id, best_job


def _coarse_job_score(job: dict[str, Any], signals: dict[str, Any], *, location_weight: float = 1.0) -> float:
    text = _norm_text(
        " ".join(
            [
                str(job.get("title") or ""),
                str(job.get("company_name") or ""),
                str(job.get("location") or ""),
                str(job.get("description") or "")[:1200],
            ]
        )
    )
    score = 0.0
    score += _weighted_overlap(text, signals.get("query_terms") or [], cap=8) * 3.2
    score += _weighted_overlap(text, signals.get("hard_terms") or [], cap=14) * 1.8
    score += _weighted_overlap(text, signals.get("soft_terms") or [], cap=8) * 0.8
    if signals.get("preferred_locations"):
        loc = _norm_text(job.get("location"))
        for pref_loc in signals["preferred_locations"]:
            if pref_loc and pref_loc in loc:
                score += 5.0 * max(0.0, float(location_weight))
                break
    return score


def _job_query_intent_hit(job: dict[str, Any], query_tokens: set[str]) -> bool:
    if not query_tokens:
        return False
    focus = normalize_token(
        " ".join(
            [
                str(job.get("title") or ""),
                str(job.get("company_name") or ""),
            ]
        )
    )
    if not focus:
        return False
    for tk in query_tokens:
        token = str(tk or "").strip()
        if token and token in focus:
            return True
    return False


def _job_family(job_id: str, cache: dict[str, str]) -> str:
    jid = str(job_id or "").strip()
    if not jid:
        return ""
    if jid in cache:
        return cache[jid]
    role_ids = db.list_roles_for_job(jid)
    family = ""
    if role_ids:
        role = db.get_role(role_ids[0]) or {}
        family = str(role.get("job_family") or "").strip().lower()
    cache[jid] = family
    return family


def _refine_job_score_with_family(
    job: dict[str, Any],
    *,
    base_score: float,
    signals: dict[str, Any],
    family_cache: dict[str, str],
    hard_count_cache: dict[str, int],
    student_hard_count: int,
) -> tuple[float, str, int]:
    job_id = str(job.get("job_id") or "").strip()
    family = _job_family(str(job.get("job_id") or ""), family_cache)
    hard_count = hard_count_cache.get(job_id)
    if hard_count is None:
        profile = db.get_job_profile(job_id) or {}
        hard_count = len(((profile.get("profile") or {}).get("hard_skills") or []))
        hard_count_cache[job_id] = int(hard_count)
    score = base_score
    preferred = set(signals.get("preferred_families") or [])
    if preferred:
        if family and family in preferred:
            score += 16.0
        elif family:
            score -= 2.0
    score += _hard_skill_presence_adjust(student_hard_count, hard_count)
    return score, family, int(hard_count)


def _top_strengths_and_gaps(result: dict[str, Any]) -> tuple[list[str], list[str]]:
    skills = (result.get("dimension_scores") or {}).get("skills") or {}
    strengths = [m.get("name") for m in (skills.get("matched") or []) if float(m.get("match") or 0) >= 1][:5]
    gaps = [m.get("name") for m in (skills.get("missing") or [])][:6]
    return strengths, gaps


def _clip_log_payload(data: Any, *, limit: int = 32000) -> str:
    try:
        text = json.dumps(data, ensure_ascii=False)
    except Exception:
        text = str(data)
    if len(text) <= limit:
        return text
    omitted = len(text) - limit
    return f"{text[:limit]}...<truncated {omitted} chars>"


def _student_profile_for_ai_rerank(student_profile: dict[str, Any]) -> dict[str, Any]:
    return build_student_profile_snapshot(
        student_profile,
        hard_limit=32,
        soft_limit=20,
        cert_limit=12,
        detail_limit_per_field=6,
        include_detail_items=True,
        include_education=True,
        notes_limit=280,
        profile_notes_limit=420,
    )


def _job_profile_for_ai_rerank(profile: dict[str, Any]) -> dict[str, Any]:
    basic = profile.get("basic_requirements") or {}
    return {
        "job_family": str(profile.get("job_family") or "").strip(),
        "hard_skills": [
            str(item.get("mention") or item.get("name") or item.get("skill_id") or "").strip()
            for item in (profile.get("hard_skills") or [])[:24]
            if str(item.get("mention") or item.get("name") or item.get("skill_id") or "").strip()
        ],
        "soft_skills": [
            str(item.get("mention") or item.get("name") or "").strip()
            for item in (profile.get("soft_skills") or [])[:12]
            if str(item.get("mention") or item.get("name") or "").strip()
        ],
        "certificates": [
            str(item.get("mention") or item.get("name") or "").strip()
            for item in (profile.get("certificates") or [])[:10]
            if str(item.get("mention") or item.get("name") or "").strip()
        ],
        "basic_requirements": {
            "education": basic.get("education"),
            "experience_years_min": basic.get("experience_years_min"),
            "tags": basic.get("tags") or [],
        },
    }


def _extract_ai_rerank_scores(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        rows = None
        for key in ("scores", "items", "ranked_jobs", "jobs", "results"):
            value = data.get(key)
            if isinstance(value, list):
                rows = value
                break
        if rows is None and data.get("job_id"):
            rows = [data]
        if rows is None:
            rows = []
    else:
        rows = []

    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        job_id = str(row.get("job_id") or row.get("id") or "").strip()
        if not job_id:
            continue
        raw_score = row.get("ai_score")
        if raw_score is None:
            raw_score = row.get("score")
        if raw_score is None:
            raw_score = row.get("fit_score")
        try:
            ai_score = float(raw_score)
        except Exception:
            continue
        if ai_score <= 1.0:
            ai_score = ai_score * 100.0
        ai_score = max(0.0, min(100.0, ai_score))
        reason = str(row.get("reason") or row.get("summary") or row.get("analysis") or "").strip()
        out.append({"job_id": job_id, "ai_score": ai_score, "reason": reason[:180]})
    return out


def _ai_rerank_top_jobs(
    *,
    items: list[dict[str, Any]],
    student_profile: dict[str, Any],
    top_n: int,
    debug: bool = False,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any] | None]:
    if not items or top_n <= 0 or not llm_client.is_enabled():
        return {}, None
    candidates = items[:top_n]
    candidate_job_ids = {str(item.get("job_id") or "").strip() for item in candidates if str(item.get("job_id") or "").strip()}
    if not candidate_job_ids:
        return {}, None

    jobs_payload = []
    candidate_rank_score_map: dict[str, float] = {}
    for rank, item in enumerate(candidates, start=1):
        job_id = str(item.get("job_id") or "").strip()
        if not job_id:
            continue
        candidate_rank_score_map[job_id] = float(item.get("rank_score") or 0.0)
        job = db.get_job(job_id) or {}
        job_profile = (db.get_job_profile(job_id) or {}).get("profile") or {}
        jobs_payload.append(
            {
                "rank": rank,
                "job_id": job_id,
                "title": item.get("title") or job.get("title"),
                "company_name": item.get("company_name") or job.get("company_name"),
                "location": item.get("location") or job.get("location"),
                "salary_min": item.get("salary_min") or job.get("salary_min"),
                "salary_max": item.get("salary_max") or job.get("salary_max"),
                "job_family": item.get("job_family") or job_profile.get("job_family"),
                "rank_score": item.get("rank_score"),
                "overall_score": item.get("overall_score"),
                "top_strengths": item.get("top_strengths") or [],
                "top_gaps": item.get("top_gaps") or [],
                "description": str(job.get("description") or item.get("description") or "")[:1200],
                "job_profile": _job_profile_for_ai_rerank(job_profile),
            }
        )
    if not jobs_payload:
        return {}, None

    student_payload = _student_profile_for_ai_rerank(student_profile)
    request_payload = {
        "student_profile": student_payload,
        "candidate_jobs": jobs_payload,
    }
    if debug:
        logger.info("[AI_RERANK][INPUT][student_profile] %s", _clip_log_payload(student_payload))
        logger.info("[AI_RERANK][INPUT][candidate_jobs] %s", _clip_log_payload(jobs_payload))

    system = """你是岗位匹配重排评审器。请基于学生画像与岗位完整信息，对候选岗位做0-100分的可比较评分。
只输出严格 JSON：
{
  "scores": [
    {"job_id": "string", "ai_score": 0-100, "reason": "一句话原因"}
  ]
}
规则：
1) 必须优先评估技能匹配（硬技能/软技能）、基础要求匹配（学历/经验）、地点偏好匹配。
2) 必须参考学生 experience（实习/项目/获奖/开源/负责人计数）和 experience_evidence_counts（证据充足度）判断履历深度；如提供 experience_detail_items，可用于核验真实性与相关性。
3) 如果岗位几乎不要求硬技能，不要因为学生硬技能少而扣分。
4) 分数用于同一批候选的相对排序，越适配分越高。
5) reason 要简短具体，不要空泛。
6) 必须覆盖所有 candidate_jobs 的 job_id，不允许遗漏。
7) 只给输入中出现过的 job_id 打分。
8) 对于应届/初级岗位，不要因经验计数偏低而过度扣分。"""
    user = json.dumps(request_payload, ensure_ascii=False)
    try:
        data = llm_client.chat_json_sync(
            system,
            user,
            trace_context="match.recommend_jobs.ai_rerank",
        )
    except Exception:
        return {}, (request_payload if debug else None)

    score_rows = _extract_ai_rerank_scores(data)
    if debug:
        logger.info("[AI_RERANK][OUTPUT][scores] %s", _clip_log_payload(score_rows))
        logger.info("[AI_RERANK][OUTPUT][raw] %s", _clip_log_payload(data))
    score_map: dict[str, dict[str, Any]] = {}
    for row in score_rows:
        job_id = str(row.get("job_id") or "").strip()
        if job_id not in candidate_job_ids:
            continue
        score_map[job_id] = {
            "ai_score": float(row.get("ai_score") or 0.0),
            "reason": str(row.get("reason") or "").strip(),
        }
    # If model omits some jobs (often due truncation), fallback to rule rank-derived score.
    if len(score_map) < len(candidate_job_ids):
        vals = [candidate_rank_score_map.get(jid, 0.0) for jid in candidate_job_ids]
        lo = min(vals) if vals else 0.0
        hi = max(vals) if vals else 0.0
        for jid in candidate_job_ids:
            if jid in score_map:
                continue
            base = float(candidate_rank_score_map.get(jid) or 0.0)
            if hi <= lo:
                fallback_ai = 70.0
            else:
                fallback_ai = ((base - lo) / (hi - lo)) * 100.0
            score_map[jid] = {
                "ai_score": max(0.0, min(100.0, float(fallback_ai))),
                "reason": "AI响应缺失，使用规则排序分兜底",
            }
    debug_payload = None
    if debug:
        debug_payload = {
            "student_profile_sent": student_payload,
            "jobs_sent": jobs_payload,
            "jobs_sent_count": len(jobs_payload),
            "llm_scores_received": score_rows,
            "llm_scores_missing_filled": max(0, len(candidate_job_ids) - len(score_rows)),
        }
    return score_map, debug_payload


def _blend_job_rank_with_ai(
    items: list[dict[str, Any]],
    *,
    ai_score_map: dict[str, dict[str, Any]],
    ai_weight: float,
) -> list[dict[str, Any]]:
    if not items:
        return []
    rank_values = [float(item.get("rank_score") or 0.0) for item in items]
    lo = min(rank_values) if rank_values else 0.0
    hi = max(rank_values) if rank_values else 0.0
    w = _clamp_ratio(ai_weight, default=0.35)
    out = []
    for item in items:
        ranked = dict(item)
        rank_score = float(item.get("rank_score") or 0.0)
        if hi <= lo:
            rank_score_norm = 100.0
        else:
            rank_score_norm = max(0.0, min(100.0, ((rank_score - lo) / (hi - lo)) * 100.0))
        job_id = str(item.get("job_id") or "").strip()
        ai_row = ai_score_map.get(job_id)
        if ai_row:
            ai_score = max(0.0, min(100.0, float(ai_row.get("ai_score") or 0.0)))
            final_rank = (1.0 - w) * rank_score_norm + w * ai_score
            ranked["ai_rerank_used"] = True
            ranked["ai_rerank_score"] = round(ai_score, 2)
            ranked["ai_rerank_reason"] = str(ai_row.get("reason") or "")
        else:
            final_rank = rank_score_norm
            ranked["ai_rerank_used"] = False
            ranked["ai_rerank_score"] = None
            ranked["ai_rerank_reason"] = ""
        ranked["rank_score_normalized"] = round(rank_score_norm, 2)
        ranked["ai_rerank_weight"] = round(w, 3)
        ranked["final_rank_score"] = round(final_rank, 2)
        out.append(ranked)
    out.sort(
        key=lambda x: (
            float(x.get("final_rank_score") or 0.0),
            float(x.get("rank_score") or 0.0),
            float(x.get("overall_score") or 0.0),
        ),
        reverse=True,
    )
    return out


def _ensure_student_profile(student_id: str) -> tuple[dict[str, Any], str]:
    current = db.get_student_profile(student_id)
    if current and isinstance(current.get("profile"), dict):
        return current["profile"], "existing"

    try:
        generate_student_profile_from_latest_resume(student_id)
    except Exception:
        pass

    current = db.get_student_profile(student_id)
    if current and isinstance(current.get("profile"), dict):
        return current["profile"], "generated_from_latest_resume"

    try:
        profile = build_student_profile_from_manual(
            student_id,
            {
                "hard_skills": [],
                "soft_skills": [],
                "certificates": [],
                "experience": {"internships": 0, "projects": 0, "awards": 0, "publications": 0, "open_source": 0, "leadership": 0},
                "preferences": {},
                "raw_text": "",
            },
        )
        return profile.model_dump(), "generated_empty_fallback"
    except Exception:
        return {}, "missing"


@router.post("/events")
def track_event(body: dict[str, Any]) -> dict[str, Any]:
    student_id = body.get("student_id")
    event_type = body.get("event_type")
    if not student_id or not event_type:
        return {"error": "student_id and event_type required"}
    item = record_student_event(
        student_id=student_id,
        event_type=event_type,
        job_id=body.get("job_id"),
        role_id=body.get("role_id"),
        source=body.get("source"),
        metadata=body.get("meta"),
        event_value=body.get("event_value"),
    )
    return {"ok": True, "event": item}


@router.get("/events/{student_id}")
def list_events(student_id: str, event_type: str | None = None, limit: int = 100, offset: int = 0) -> dict[str, Any]:
    return {
        "items": db.list_student_events(student_id=student_id, event_type=event_type, limit=limit, offset=offset),
        "count": db.count_student_events(student_id=student_id),
        "limit": limit,
        "offset": offset,
    }


@router.get("/preferences/{student_id}")
def list_preferences(student_id: str, limit: int = 500, offset: int = 0) -> dict[str, Any]:
    items = db.list_student_job_preferences(student_id=student_id, limit=limit, offset=offset)
    return {
        "items": items,
        "count": len(items),
        "limit": limit,
        "offset": offset,
    }


@router.post("/preferences")
def set_preference(body: dict[str, Any]) -> dict[str, Any]:
    student_id = str(body.get("student_id") or "").strip()
    job_id = str(body.get("job_id") or "").strip()
    raw_preference = str(body.get("preference") or "").strip().upper()
    source = str(body.get("source") or "match_workbench").strip() or "match_workbench"
    if not student_id or not job_id:
        return {"error": "student_id and job_id required"}

    if raw_preference in {"", "NONE", "CLEAR", "CANCEL", "UNSET"}:
        previous = db.get_student_job_preference(student_id, job_id)
        db.delete_student_job_preference(student_id, job_id)
        if previous:
            event_type = "UNFAVORITE" if previous.get("preference") == "FAVORITE" else "UNDISMISS"
            record_student_event(
                student_id=student_id,
                event_type=event_type,
                job_id=job_id,
                source=source,
                metadata={"previous_preference": previous.get("preference"), **(body.get("meta") or {})},
            )
        return {"ok": True, "preference": None}

    if raw_preference not in {"FAVORITE", "DISMISS"}:
        return {"error": "preference must be FAVORITE, DISMISS, or CLEAR"}

    now = now_iso()
    db.upsert_student_job_preference(
        student_id=student_id,
        job_id=job_id,
        preference=raw_preference,
        source=source,
        meta_json=json.dumps(body.get("meta") or {}, ensure_ascii=False),
        created_at=now,
        updated_at=now,
    )
    record_student_event(
        student_id=student_id,
        event_type=raw_preference,
        job_id=job_id,
        source=source,
        metadata=body.get("meta") or {},
    )
    return {"ok": True, "preference": db.get_student_job_preference(student_id, job_id)}


@router.post("/score")
def score_one(body: dict[str, Any]) -> dict[str, Any]:
    student_id = body.get("student_id")
    job_id = body.get("job_id")
    if not student_id or not job_id:
        return {"error": "student_id and job_id required"}
    _, profile_source = _ensure_student_profile(student_id)
    try:
        res = score(
            student_id,
            job_id,
            use_cache=bool(body.get("use_cache", True)),
            use_semantic_review=bool(body.get("use_semantic_review", True)),
        )
    except ValueError as e:
        return {"error": str(e)}
    data = res.model_dump()
    data["profile_source"] = profile_source
    if bool(body.get("include_ai_analysis", True)):
        data["ai_analysis"] = build_match_ai_analysis(student_id, job_id, data)
    else:
        data["ai_analysis"] = None
    return data


@router.post("/analysis")
def analyze_match(body: dict[str, Any]) -> dict[str, Any]:
    student_id = body.get("student_id")
    job_id = body.get("job_id")
    if not student_id or not job_id:
        return {"error": "student_id and job_id required"}
    score_result = body.get("score_result")
    if not isinstance(score_result, dict):
        try:
            score_result = score(
                student_id,
                job_id,
                use_cache=bool(body.get("use_cache", True)),
                use_semantic_review=bool(body.get("use_semantic_review", False)),
            ).model_dump()
        except ValueError as e:
            return {"error": str(e)}
    return {
        "student_id": student_id,
        "job_id": job_id,
        "ai_analysis": build_match_ai_analysis(student_id, job_id, score_result),
    }


@router.post("/score_fit_ai")
def score_fit_ai(body: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        return score_fit_with_ai(body)
    except ValueError as e:
        return {"error": str(e)}


@router.post("/score_role")
def score_role(body: dict[str, Any]) -> dict[str, Any]:
    student_id = body.get("student_id")
    role_id = body.get("role_id")
    if not student_id or not role_id:
        return {"error": "student_id and role_id required"}
    _, profile_source = _ensure_student_profile(student_id)
    members = db.list_role_members(role_id)
    if not members:
        return {"error": "role_has_no_jobs"}
    job_id = members[0]
    try:
        res = score(
            student_id,
            job_id,
            use_cache=bool(body.get("use_cache", True)),
            use_semantic_review=bool(body.get("use_semantic_review", True)),
        )
    except ValueError as e:
        return {"error": str(e)}
    d = res.model_dump()
    d["role_id"] = role_id
    d["representative_job_id"] = job_id
    d["profile_source"] = profile_source
    d["ai_analysis"] = build_match_ai_analysis(student_id, job_id, d)
    return d


@router.post("/batch_score")
def batch_score(body: dict[str, Any]) -> dict[str, Any]:
    student_id = body.get("student_id")
    job_ids = body.get("job_ids") or []
    if not student_id or not job_ids:
        return {"error": "student_id and job_ids required"}
    _, profile_source = _ensure_student_profile(student_id)
    use_semantic_review = bool(body.get("use_semantic_review", False))
    workers = max(1, min(16, int(body.get("workers") or min(8, len(job_ids)))))
    results: list[dict[str, Any]] = []

    def _score_job(job_id: Any) -> dict[str, Any] | None:
        try:
            return score(
                student_id,
                str(job_id),
                use_cache=True,
                use_semantic_review=use_semantic_review,
            ).model_dump()
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="match-batch-score") as executor:
        futures = [executor.submit(_score_job, jid) for jid in job_ids]
        for future in as_completed(futures):
            row = future.result()
            if row:
                results.append(row)
    results.sort(key=lambda x: x["overall_score"], reverse=True)
    return {
        "items": results,
        "profile_source": profile_source,
        "use_semantic_review": use_semantic_review,
        "workers": workers,
    }


@router.post("/recommend_roles")
def recommend_roles(body: dict[str, Any]) -> dict[str, Any]:
    student_id = body.get("student_id")
    if not student_id:
        return {"error": "student_id required"}

    top_k = int(body.get("top_k") or 8)
    max_candidates = int(body.get("max_candidates") or 1500)
    q = body.get("q")
    job_family = body.get("job_family")
    use_cache = bool(body.get("use_cache", True))
    strategy = normalize_strategy(body.get("strategy"))
    strict_family = bool(body.get("strict_family", True))
    allow_low_relevance_fallback = bool(body.get("allow_low_relevance_fallback", False))
    strict_keyword_filter = bool(body.get("strict_keyword_filter", bool(str(q or "").strip())))
    score_candidates = int(body.get("score_candidates") or min(max_candidates, 260))
    coarse_pool = int(body.get("coarse_pool") or min(max_candidates, 900))
    representative_scan_members = int(body.get("representative_scan_members") or 8)
    vector_top_k_each = int(body.get("vector_top_k_each") or 120)
    location_weight = _clamp_location_weight(body.get("location_weight"), default=1.0)

    student_profile, profile_source = _ensure_student_profile(student_id)
    student_hard_count = _student_hard_skill_count(student_profile)
    preferred_families = (student_profile.get("preferences") or {}).get("preferred_job_families") or []
    student_has_preferred_families = bool(preferred_families)
    behavior_profile = build_student_behavior_profile(
        student_id=student_id,
        lookback_days=int(body.get("lookback_days") or 180),
        limit=int(body.get("event_limit") or 1000),
    )
    strict_q_tokens = _strict_query_tokens(q) if strict_keyword_filter else []
    roles = db.list_roles(
        job_family=job_family,
        q=(q if strict_keyword_filter and len(strict_q_tokens) <= 1 else None),
        limit=max_candidates,
        offset=0,
    )
    if strict_keyword_filter and len(strict_q_tokens) > 1:
        roles = [
            role
            for role in roles
            if _strict_query_match(
                " ".join(
                    [
                        str(role.get("title_rep") or ""),
                        str(role.get("base_role") or ""),
                        str(role.get("role_key") or ""),
                        str(role.get("job_family") or ""),
                    ]
                ),
                strict_q_tokens,
            )
        ]
    roles_total = len(roles)
    signals = _student_signal_terms(student_profile, q)
    role_vector_scores = _role_vector_recall_scores(signals, q, top_k_each=vector_top_k_each)
    query_tokens = {normalize_token(x) for x in (signals.get("query_terms") or []) if normalize_token(x)}

    def _role_hybrid_coarse_score(role: dict[str, Any]) -> float:
        base = _coarse_role_score(role, signals)
        role_id = str(role.get("role_id") or "").strip()
        vector_bonus = 24.0 * float(role_vector_scores.get(role_id) or 0.0)
        keyword_bonus = 0.0
        if query_tokens and not strict_keyword_filter:
            role_text = normalize_token(
                " ".join(
                    [
                        str(role.get("title_rep") or ""),
                        str(role.get("base_role") or ""),
                        str(role.get("job_family") or ""),
                    ]
                )
            )
            if role_text:
                hits = sum(1 for tk in query_tokens if tk and tk in role_text)
                keyword_bonus = min(6.0, float(hits) * 2.0)
        return base + vector_bonus + keyword_bonus

    role_scoring_pool_raw = sorted(
        [{"role": role, "coarse_score": _role_hybrid_coarse_score(role)} for role in roles],
        key=lambda x: x["coarse_score"],
        reverse=True,
    )
    role_refine_candidates = role_scoring_pool_raw[: max(1, min(len(role_scoring_pool_raw), coarse_pool))]
    role_profile_cache: dict[str, dict[str, Any] | None] = {}
    role_scoring_pool = []
    for item in role_refine_candidates:
        role = item["role"]
        role_id = str(role.get("role_id") or "").strip()
        if not role_id:
            continue
        rp = db.get_role_profile(role_id)
        role_profile_cache[role_id] = rp
        role_scoring_pool.append(
            {
                "role": role,
                "refined_score": _refined_role_score(
                    role,
                    rp,
                    signals,
                    student_hard_count=student_hard_count,
                ),
            }
        )
    role_scoring_pool.sort(key=lambda x: x["refined_score"], reverse=True)
    role_candidates = [item["role"] for item in role_scoring_pool[: max(1, min(len(role_scoring_pool), score_candidates))]]
    roles_without_members = 0
    scored_roles = 0
    score_failed_roles = 0
    score_failed_reason_counter: dict[str, int] = {}
    relation_low_filtered = 0
    relation_unknown_filtered = 0
    relation_unknown_kept = 0
    strict_family_fallback_used = False
    items = []
    relation_low_items = []
    for role in role_candidates:
        members = db.list_role_members(role["role_id"])
        if not members:
            roles_without_members += 1
            continue
        representative_job_id, representative_job = _pick_representative_job_id(
            members,
            signals,
            max_scan=representative_scan_members,
            location_weight=location_weight,
        )
        try:
            result = score(
                student_id,
                representative_job_id,
                use_cache=use_cache,
                use_semantic_review=False,
            ).model_dump()
        except ValueError:
            score_failed_roles += 1
            err = "score_value_error"
            score_failed_reason_counter[err] = int(score_failed_reason_counter.get(err) or 0) + 1
            continue
        except Exception as e:
            score_failed_roles += 1
            err = str(e)[:120] if str(e) else "score_unknown_error"
            score_failed_reason_counter[err] = int(score_failed_reason_counter.get(err) or 0) + 1
            continue
        scored_roles += 1
        role_id = str(role.get("role_id") or "").strip()
        rp = role_profile_cache.get(role_id)
        if rp is None:
            rp = db.get_role_profile(role_id)
            role_profile_cache[role_id] = rp
        strengths, gaps = _top_strengths_and_gaps(result)
        relation = str((((result.get("dimension_scores") or {}).get("skills") or {}).get("relation") or "")).strip().lower()
        items.append(
            {
                "role_id": role["role_id"],
                "representative_job_id": representative_job_id,
                "representative_job_title": representative_job.get("title"),
                "representative_company": representative_job.get("company_name"),
                "title": role.get("title_rep") or role.get("base_role"),
                "job_family": role.get("job_family"),
                "level_label": role.get("level_label"),
                "member_count": len(members),
                "overall_score": result.get("overall_score"),
                "dimension_scores": result.get("dimension_scores"),
                "representative_location": representative_job.get("location"),
                "top_strengths": strengths,
                "top_gaps": gaps,
                "match_relation": relation,
                "top_hard_skills": ((rp or {}).get("profile") or {}).get("top_hard_skills", [])[:8],
                "top_soft_skills": ((rp or {}).get("profile") or {}).get("top_soft_skills", [])[:5],
                "salary_stats": ((rp or {}).get("profile") or {}).get("salary_stats") or {},
            }
        )
        if strict_family and relation == "low":
            relation_low_filtered += 1
            relation_low_items.append(items.pop())
        elif strict_family and relation == "unknown" and student_has_preferred_families:
            relation_unknown_filtered += 1
            items.pop()
        elif relation == "unknown":
            relation_unknown_kept += 1

    if strict_family and allow_low_relevance_fallback and not items and relation_low_items:
        # Keep service usable when every candidate is cross-family; still expose diagnostics.
        strict_family_fallback_used = True
        items = relation_low_items
    items = rerank_role_items(
        items=items,
        strategy=strategy,
        student_profile=student_profile,
        behavior_profile=behavior_profile,
    )
    total_candidates = len(items)
    items = [enrich_role_labels(item) for item in items[:top_k]]
    return {
        "items": items,
        "total_candidates": total_candidates,
        "strategy": strategy,
        "profile_source": profile_source,
        "behavior_used_events": int(behavior_profile.get("used_events") or 0),
        "diagnostics": {
            "student_hard_skill_count": student_hard_count,
            "location_weight": location_weight,
            "skill_presence_policy": "student_without_hard_skills_prefers_low_hard_requirement_roles"
            if student_hard_count <= 0
            else "student_with_hard_skills_prefers_roles_with_hard_requirements",
            "roles_total": roles_total,
            "strict_keyword_filter": strict_keyword_filter,
            "vector_recall_hits": len(role_vector_scores),
            "roles_recall_pool": len(role_scoring_pool_raw),
            "roles_refine_pool": len(role_refine_candidates),
            "roles_scoring_pool": len(role_candidates),
            "roles_without_members": roles_without_members,
            "roles_scored": scored_roles,
            "roles_score_failed": score_failed_roles,
            "student_has_preferred_families": student_has_preferred_families,
            "preferred_family_count": len(preferred_families),
            "strict_family": strict_family,
            "allow_low_relevance_fallback": allow_low_relevance_fallback,
            "strict_family_fallback_used": strict_family_fallback_used,
            "relation_low_filtered": relation_low_filtered,
            "relation_unknown_filtered": relation_unknown_filtered,
            "relation_unknown_kept": relation_unknown_kept,
            "profile_needs_family_preferences": not student_has_preferred_families,
            "top_score_fail_reasons": sorted(
                score_failed_reason_counter.items(),
                key=lambda kv: kv[1],
                reverse=True,
            )[:3],
        },
        "kb_references": [],
    }


@router.post("/recommend_jobs")
def recommend_jobs(body: dict[str, Any]) -> dict[str, Any]:
    student_id = body.get("student_id")
    if not student_id:
        return {"error": "student_id required"}
    engine = str(body.get("engine") or "legacy").strip().lower()
    if engine == "g_rank":
        top_k = int(body.get("top_k") or 10)
        return recommend_jobs_g_rank(
            student_id,
            top_k=top_k,
            q=body.get("q"),
            location=body.get("location"),
            job_family=body.get("job_family"),
            strategy=body.get("strategy"),
            max_candidates=int(body.get("max_candidates") or 12000),
            strict_family=bool(body.get("strict_family", True)),
            semantic_enabled=bool(body.get("semantic_enabled", True)),
            bge_rerank_enabled=bool(body.get("bge_rerank_enabled", True)),
            bge_rerank_top_n=int(body.get("bge_rerank_top_n") or 20),
            bge_rerank_weight=_clamp_ratio(body.get("bge_rerank_weight"), default=0.28),
        )
    top_k = int(body.get("top_k") or 10)
    max_candidates = int(body.get("max_candidates") or 12000)
    q = body.get("q")
    location = body.get("location")
    use_cache = bool(body.get("use_cache", True))
    strategy = normalize_strategy(body.get("strategy"))
    strict_family = bool(body.get("strict_family", True))
    allow_low_relevance_fallback = bool(body.get("allow_low_relevance_fallback", False))
    strict_keyword_filter = bool(body.get("strict_keyword_filter", bool(str(q or "").strip())))
    score_candidates = int(body.get("score_candidates") or min(max_candidates, 320))
    coarse_pool = int(body.get("coarse_pool") or min(max_candidates, 1200))
    vector_top_k_each = int(body.get("vector_top_k_each") or 220)
    location_weight = _clamp_location_weight(body.get("location_weight"), default=1.0)
    ai_rerank_enabled = bool(body.get("ai_rerank_enabled", True))
    ai_rerank_top_n = _clamp_ai_rerank_top_n(body.get("ai_rerank_top_n"), default=20)
    ai_rerank_weight = _clamp_ratio(body.get("ai_rerank_weight"), default=0.35)
    ai_rerank_debug = bool(body.get("ai_rerank_debug", False))

    student_profile, profile_source = _ensure_student_profile(student_id)
    student_hard_count = _student_hard_skill_count(student_profile)
    preferred_families = (student_profile.get("preferences") or {}).get("preferred_job_families") or []
    student_has_preferred_families = bool(preferred_families)
    behavior_profile = build_student_behavior_profile(
        student_id=student_id,
        lookback_days=int(body.get("lookback_days") or 180),
        limit=int(body.get("event_limit") or 1000),
    )
    signals = _student_signal_terms(student_profile, q)
    strict_q_tokens = _strict_query_tokens(q) if strict_keyword_filter else []
    jobs = db.list_jobs(
        q=(q if strict_keyword_filter and len(strict_q_tokens) <= 1 else None),
        location=location,
        limit=max_candidates,
        offset=0,
    )
    if strict_keyword_filter and len(strict_q_tokens) > 1:
        jobs = [
            job
            for job in jobs
            if _strict_query_match(
                " ".join(
                    [
                        str(job.get("title") or ""),
                        str(job.get("company_name") or ""),
                        str(job.get("description") or ""),
                    ]
                ),
                strict_q_tokens,
            )
        ]
    job_vector_scores = _job_vector_recall_scores(signals, q, top_k_each=vector_top_k_each)
    jobs_by_id = {str(job.get("job_id") or "").strip(): job for job in jobs if str(job.get("job_id") or "").strip()}
    vector_ranked_ids = sorted(job_vector_scores.keys(), key=lambda jid: float(job_vector_scores.get(jid) or 0.0), reverse=True)
    vector_jobs = [jobs_by_id[jid] for jid in vector_ranked_ids if jid in jobs_by_id]
    query_tokens = {normalize_token(x) for x in (signals.get("query_terms") or []) if normalize_token(x)}

    def _query_keyword_bonus(job: dict[str, Any]) -> float:
        if not query_tokens or strict_keyword_filter:
            return 0.0
        focus_text = normalize_token(
            " ".join(
                [
                    str(job.get("title") or ""),
                    str(job.get("company_name") or ""),
                ]
            )
        )
        focus_hits = 0
        if focus_text:
            focus_hits = sum(1 for tk in query_tokens if tk and tk in focus_text)
        text = normalize_token(
            " ".join(
                [
                    str(job.get("title") or ""),
                    str(job.get("company_name") or ""),
                    str(job.get("description") or "")[:1200],
                ]
            )
        )
        if not text:
            return min(18.0, float(focus_hits) * 6.0)
        hits = sum(1 for tk in query_tokens if tk and tk in text)
        broad_bonus = min(8.0, float(hits) * 2.2)
        focus_bonus = min(18.0, float(focus_hits) * 6.0)
        return broad_bonus + focus_bonus

    use_vector_pool = len(vector_jobs) >= max(220, min(800, coarse_pool // 2))
    jobs_fallback_seed = 0
    if use_vector_pool:
        vector_cap = max(1, min(len(vector_jobs), max(coarse_pool, score_candidates * 2)))
        coarse_source_jobs = list(vector_jobs[:vector_cap])
        vector_ids = {str(job.get("job_id") or "").strip() for job in coarse_source_jobs}
        fallback_cap = max(60, min(320, coarse_pool // 3))
        fallback_pool = [job for job in jobs if str(job.get("job_id") or "").strip() not in vector_ids]
        if fallback_pool and fallback_cap > 0:
            fallback_ranked = sorted(
                fallback_pool,
                key=lambda row: _coarse_job_score(row, signals, location_weight=location_weight) + _query_keyword_bonus(row),
                reverse=True,
            )
            fallback_jobs = fallback_ranked[:fallback_cap]
            coarse_source_jobs.extend(fallback_jobs)
            jobs_fallback_seed = len(fallback_jobs)
    else:
        coarse_source_jobs = jobs

    def _job_hybrid_coarse_score(job: dict[str, Any]) -> float:
        base = _coarse_job_score(job, signals, location_weight=location_weight)
        job_id = str(job.get("job_id") or "").strip()
        vector_bonus = 28.0 * float(job_vector_scores.get(job_id) or 0.0)
        keyword_bonus = _query_keyword_bonus(job)
        return base + vector_bonus + keyword_bonus

    job_scoring_pool_raw = sorted(
        [{"job": job, "coarse_score": _job_hybrid_coarse_score(job)} for job in coarse_source_jobs],
        key=lambda x: x["coarse_score"],
        reverse=True,
    )
    job_refine_candidates = job_scoring_pool_raw[: max(1, min(len(job_scoring_pool_raw), coarse_pool))]
    family_cache: dict[str, str] = {}
    hard_count_cache: dict[str, int] = {}
    job_scoring_pool = []
    for item in job_refine_candidates:
        row = item["job"]
        refined, family, job_hard_skill_count = _refine_job_score_with_family(
            row,
            base_score=float(item["coarse_score"]),
            signals=signals,
            family_cache=family_cache,
            hard_count_cache=hard_count_cache,
            student_hard_count=student_hard_count,
        )
        job_scoring_pool.append(
            {
                "job": row,
                "refined_score": refined,
                "family": family,
                "job_hard_skill_count": int(job_hard_skill_count),
            }
        )
    job_scoring_pool.sort(key=lambda x: x["refined_score"], reverse=True)
    job_candidates = job_scoring_pool[: max(1, min(len(job_scoring_pool), score_candidates))]
    items = []
    relation_low_filtered = 0
    relation_unknown_filtered = 0
    relation_unknown_kept = 0
    strict_family_fallback_used = False
    relation_low_items = []
    for candidate in job_candidates:
        job = candidate["job"]
        role_family = str(candidate.get("family") or "").strip()
        job_hard_skill_count = int(candidate.get("job_hard_skill_count") or 0)
        try:
            result = score(
                student_id,
                job["job_id"],
                use_cache=use_cache,
                use_semantic_review=False,
            ).model_dump()
        except ValueError:
            continue
        strengths, gaps = _top_strengths_and_gaps(result)
        row = {
            **job,
            "job_family": role_family,
            "overall_score": result.get("overall_score"),
            "dimension_scores": result.get("dimension_scores"),
            "top_strengths": strengths,
            "top_gaps": gaps,
            "match_relation": str((((result.get("dimension_scores") or {}).get("skills") or {}).get("relation") or "")).strip().lower(),
            "job_hard_skill_count": job_hard_skill_count,
        }
        relation = str(row.get("match_relation") or "").strip().lower()
        query_intent_hit = _job_query_intent_hit(job, query_tokens)
        row["query_intent_hit"] = query_intent_hit
        row["query_intent_boost"] = 12.0 if query_intent_hit else 0.0
        if strict_family and relation == "low" and not query_intent_hit:
            relation_low_filtered += 1
            relation_low_items.append(row)
            continue
        if strict_family and relation == "unknown" and student_has_preferred_families and not query_intent_hit:
            relation_unknown_filtered += 1
            continue
        if relation == "unknown":
            relation_unknown_kept += 1
        items.append(
            {
                **row,
            }
        )

    if strict_family and allow_low_relevance_fallback and not items and relation_low_items:
        strict_family_fallback_used = True
        items = relation_low_items
    items = rerank_job_items(
        items=items,
        strategy=strategy,
        student_profile=student_profile,
        behavior_profile=behavior_profile,
    )
    ai_score_map: dict[str, dict[str, Any]] = {}
    ai_rerank_debug_payload: dict[str, Any] | None = None
    if ai_rerank_enabled:
        ai_score_map, ai_rerank_debug_payload = _ai_rerank_top_jobs(
            items=items,
            student_profile=student_profile,
            top_n=ai_rerank_top_n,
            debug=ai_rerank_debug,
        )
    items = _blend_job_rank_with_ai(
        items,
        ai_score_map=ai_score_map,
        ai_weight=ai_rerank_weight,
    )
    rows = [enrich_job_labels(item) for item in items[:top_k]]
    return {
        "items": rows,
        "total_candidates": len(items),
        "jobs_total": len(jobs),
        "student_hard_skill_count": student_hard_count,
        "location_weight": location_weight,
        "skill_presence_policy": "student_without_hard_skills_prefers_low_hard_requirement_jobs"
        if student_hard_count <= 0
        else "student_with_hard_skills_prefers_jobs_with_hard_requirements",
        "strict_keyword_filter": strict_keyword_filter,
        "vector_recall_hits": len(job_vector_scores),
        "jobs_recall_source": "vector_plus_full_fallback" if use_vector_pool else "full_pool",
        "jobs_fallback_seed": jobs_fallback_seed,
        "jobs_recall_pool": len(job_scoring_pool_raw),
        "jobs_refine_pool": len(job_refine_candidates),
        "jobs_scoring_pool": len(job_candidates),
        "strategy": strategy,
        "strict_family": strict_family,
        "allow_low_relevance_fallback": allow_low_relevance_fallback,
        "strict_family_fallback_used": strict_family_fallback_used,
        "relation_low_filtered": relation_low_filtered,
        "relation_unknown_filtered": relation_unknown_filtered,
        "relation_unknown_kept": relation_unknown_kept,
        "student_has_preferred_families": student_has_preferred_families,
        "preferred_family_count": len(preferred_families),
        "profile_needs_family_preferences": not student_has_preferred_families,
        "profile_source": profile_source,
        "behavior_used_events": int(behavior_profile.get("used_events") or 0),
        "ai_rerank_enabled": ai_rerank_enabled,
        "ai_rerank_used": bool(ai_score_map),
        "ai_rerank_top_n": ai_rerank_top_n,
        "ai_rerank_weight": ai_rerank_weight,
        "ai_rerank_debug": ai_rerank_debug,
        "ai_rerank_scored_count": len(ai_score_map),
        "ai_rerank_debug_payload": ai_rerank_debug_payload if ai_rerank_debug else None,
        "kb_references": [],
    }
