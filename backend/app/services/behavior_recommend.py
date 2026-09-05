from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from app.db import sqlite as db
from app.utils.ids import gen_id, now_iso

VALID_STRATEGIES = {"balanced", "skill_first", "location_first", "salary_first"}

EVENT_ALIASES = {
    "VIEW_ROLE": "VIEW",
    "VIEW_JOB": "VIEW",
    "OPEN_DETAIL": "VIEW",
    "CLICK": "VIEW",
    "DETAIL": "VIEW",
    "FAV": "FAVORITE",
    "SAVE": "FAVORITE",
    "BOOKMARK": "FAVORITE",
    "SUBMIT": "APPLY",
}

EVENT_WEIGHTS = {
    "VIEW": 1.0,
    "FAVORITE": 2.2,
    "APPLY": 3.2,
    "DISMISS": -0.8,
    "UNFAVORITE": -2.2,
    "UNDISMISS": 0.8,
}


def normalize_strategy(strategy: str | None) -> str:
    s = str(strategy or "balanced").strip().lower()
    return s if s in VALID_STRATEGIES else "balanced"


def canonical_event_type(event_type: str | None) -> str:
    e = str(event_type or "VIEW").strip().upper()
    return EVENT_ALIASES.get(e, e)


def default_event_value(event_type: str) -> float:
    return float(EVENT_WEIGHTS.get(event_type, 1.0))


def record_student_event(
    student_id: str,
    event_type: str,
    job_id: str | None = None,
    role_id: str | None = None,
    source: str | None = None,
    metadata: dict[str, Any] | None = None,
    event_value: float | None = None,
) -> dict[str, Any]:
    et = canonical_event_type(event_type)
    ev = float(event_value) if event_value is not None else default_event_value(et)

    if not db.get_student(student_id):
        db.upsert_student(student_id, name=None, created_at=now_iso())

    item = {
        "event_id": gen_id("EVT", 12),
        "student_id": student_id,
        "event_type": et,
        "job_id": job_id,
        "role_id": role_id,
        "event_value": ev,
        "source": source or "unknown",
        "meta_json": json.dumps(metadata or {}, ensure_ascii=False),
        "created_at": now_iso(),
    }
    db.insert_student_event(item)
    return {**item, "meta": metadata or {}}


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def _event_decay(created_at: str | None, lookback_days: int) -> float:
    dt = _parse_dt(created_at)
    if not dt:
        return 1.0
    now = datetime.now(timezone.utc)
    age_days = max(0.0, (now - dt.astimezone(timezone.utc)).total_seconds() / 86400.0)
    if age_days > lookback_days:
        return 0.0
    # linear decay with a floor, keeps recent behavior stronger
    return max(0.2, 1.0 - age_days / max(1.0, float(lookback_days)))


def _normalize_scores(items: dict[str, float]) -> dict[str, float]:
    if not items:
        return {}
    m = max(items.values())
    if m <= 0:
        return {}
    return {k: float(v / m) for k, v in items.items() if v > 0}


def _resolve_job_family(job_id: str | None = None, role_id: str | None = None) -> str | None:
    if role_id:
        role = db.get_role(role_id)
        if role and role.get("job_family"):
            return str(role.get("job_family"))
    if job_id:
        role_ids = db.list_roles_for_job(job_id)
        if role_ids:
            role = db.get_role(role_ids[0])
            if role and role.get("job_family"):
                return str(role.get("job_family"))
    return None


def _resolve_location(job_id: str | None = None, role_id: str | None = None) -> str | None:
    if job_id:
        job = db.get_job(job_id)
        if job and job.get("location"):
            return str(job.get("location"))
    if role_id:
        members = db.list_role_members(role_id)
        if members:
            job = db.get_job(members[0])
            if job and job.get("location"):
                return str(job.get("location"))
    return None


def build_student_behavior_profile(student_id: str, lookback_days: int = 180, limit: int = 1000) -> dict[str, Any]:
    events = db.list_student_events(student_id, limit=limit, offset=0)
    role_aff: dict[str, float] = defaultdict(float)
    job_aff: dict[str, float] = defaultdict(float)
    family_aff: dict[str, float] = defaultdict(float)
    location_aff: dict[str, float] = defaultdict(float)
    used = 0

    for e in events:
        decay = _event_decay(e.get("created_at"), lookback_days=lookback_days)
        if decay <= 0:
            continue
        used += 1
        w = float(e.get("event_value") or default_event_value(str(e.get("event_type") or "VIEW")))
        score = w * decay
        rid = e.get("role_id")
        jid = e.get("job_id")

        if rid:
            role_aff[str(rid)] += score
        if jid:
            job_aff[str(jid)] += score

        family = _resolve_job_family(job_id=jid, role_id=rid)
        if family:
            family_aff[family] += score

        location = _resolve_location(job_id=jid, role_id=rid)
        if location:
            location_aff[location] += score

    return {
        "used_events": used,
        "role_affinity": _normalize_scores(dict(role_aff)),
        "job_affinity": _normalize_scores(dict(job_aff)),
        "family_affinity": _normalize_scores(dict(family_aff)),
        "location_affinity": _normalize_scores(dict(location_aff)),
    }


def _safe_dimension_score(item: dict[str, Any], key: str) -> float:
    try:
        return float((((item.get("dimension_scores") or {}).get(key) or {}).get("score")) or 0.0)
    except Exception:
        return 0.0


def _location_match_score(student_profile: dict[str, Any] | None, candidate_location: str | None) -> float:
    if not student_profile or not candidate_location:
        return 0.0
    prefs = ((student_profile.get("preferences") or {}).get("preferred_locations") or [])
    target = str(candidate_location).strip().lower()
    if not prefs or not target:
        return 0.0
    for p in prefs:
        s = str(p or "").strip().lower()
        if s and (s in target or target in s):
            return 1.0
    return 0.0


def _location_affinity_score(candidate_location: str | None, loc_affinity: dict[str, float]) -> float:
    if not candidate_location or not loc_affinity:
        return 0.0
    target = str(candidate_location).strip().lower()
    best = 0.0
    for k, v in loc_affinity.items():
        kk = str(k).strip().lower()
        if kk and (kk in target or target in kk):
            best = max(best, float(v or 0.0))
    return best


def _norm(value: float, lo: float, hi: float) -> float:
    if hi <= lo:
        return 0.0
    return max(0.0, min(1.0, (value - lo) / (hi - lo)))


def rerank_role_items(
    items: list[dict[str, Any]],
    strategy: str,
    student_profile: dict[str, Any] | None,
    behavior_profile: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not items:
        return []
    strategy = normalize_strategy(strategy)
    behavior_profile = behavior_profile or {}
    role_aff = behavior_profile.get("role_affinity") or {}
    family_aff = behavior_profile.get("family_affinity") or {}
    loc_aff = behavior_profile.get("location_affinity") or {}

    salary_values = []
    for it in items:
        stats = it.get("salary_stats") or {}
        v = float((stats.get("salary_min_avg") or 0) + (stats.get("salary_max_avg") or 0)) / 2.0
        salary_values.append(v)
    s_min = min(salary_values) if salary_values else 0.0
    s_max = max(salary_values) if salary_values else 0.0

    out = []
    for it in items:
        overall = float(it.get("overall_score") or 0.0)
        basic = _safe_dimension_score(it, "basic")
        skills = _safe_dimension_score(it, "skills")
        qualities = _safe_dimension_score(it, "qualities")
        potential = _safe_dimension_score(it, "potential")
        loc_match = _location_match_score(student_profile, it.get("representative_location"))

        stats = it.get("salary_stats") or {}
        salary_value = float((stats.get("salary_min_avg") or 0) + (stats.get("salary_max_avg") or 0)) / 2.0
        salary_score = _norm(salary_value, s_min, s_max) * 100.0

        if strategy == "skill_first":
            strategy_score = 0.65 * skills + 0.20 * overall + 0.10 * qualities + 0.05 * potential
        elif strategy == "location_first":
            strategy_score = 0.55 * (loc_match * 100.0) + 0.30 * basic + 0.15 * overall
        elif strategy == "salary_first":
            strategy_score = 0.55 * salary_score + 0.25 * overall + 0.20 * skills
        else:
            strategy_score = overall

        role_id = str(it.get("role_id") or "")
        family = str(it.get("job_family") or "")
        loc_hint = _location_affinity_score(it.get("representative_location"), loc_aff)
        behavior_boost = 8.0 * float(role_aff.get(role_id, 0.0)) + 6.0 * float(family_aff.get(family, 0.0)) + 4.0 * loc_hint

        ranked = dict(it)
        ranked["strategy"] = strategy
        ranked["strategy_score"] = round(strategy_score, 2)
        ranked["behavior_boost"] = round(behavior_boost, 2)
        ranked["rank_score"] = round(strategy_score + behavior_boost, 2)
        out.append(ranked)

    out.sort(key=lambda x: (float(x.get("rank_score") or 0), float(x.get("overall_score") or 0), int(x.get("member_count") or 0)), reverse=True)
    return out


def rerank_job_items(
    items: list[dict[str, Any]],
    strategy: str,
    student_profile: dict[str, Any] | None,
    behavior_profile: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not items:
        return []
    strategy = normalize_strategy(strategy)
    behavior_profile = behavior_profile or {}
    job_aff = behavior_profile.get("job_affinity") or {}
    family_aff = behavior_profile.get("family_affinity") or {}
    loc_aff = behavior_profile.get("location_affinity") or {}

    salary_values = []
    for it in items:
        salary_values.append(float(it.get("salary_max") or 0.0))
    s_min = min(salary_values) if salary_values else 0.0
    s_max = max(salary_values) if salary_values else 0.0

    out = []
    for it in items:
        overall = float(it.get("overall_score") or 0.0)
        basic = _safe_dimension_score(it, "basic")
        skills = _safe_dimension_score(it, "skills")
        qualities = _safe_dimension_score(it, "qualities")
        loc_match = _location_match_score(student_profile, it.get("location"))
        salary_score = _norm(float(it.get("salary_max") or 0.0), s_min, s_max) * 100.0

        if strategy == "skill_first":
            strategy_score = 0.70 * skills + 0.20 * overall + 0.10 * qualities
        elif strategy == "location_first":
            strategy_score = 0.60 * (loc_match * 100.0) + 0.25 * basic + 0.15 * overall
        elif strategy == "salary_first":
            strategy_score = 0.60 * salary_score + 0.25 * overall + 0.15 * skills
        else:
            strategy_score = overall

        job_id = str(it.get("job_id") or "")
        family = str(it.get("job_family") or "")
        loc_hint = _location_affinity_score(it.get("location"), loc_aff)
        behavior_boost = 10.0 * float(job_aff.get(job_id, 0.0)) + 5.0 * float(family_aff.get(family, 0.0)) + 4.0 * loc_hint
        query_intent_boost = float(it.get("query_intent_boost") or 0.0)
        if query_intent_boost <= 0.0 and bool(it.get("query_intent_hit")):
            query_intent_boost = 12.0

        ranked = dict(it)
        ranked["strategy"] = strategy
        ranked["strategy_score"] = round(strategy_score, 2)
        ranked["behavior_boost"] = round(behavior_boost, 2)
        ranked["query_intent_boost"] = round(query_intent_boost, 2)
        ranked["rank_score"] = round(strategy_score + behavior_boost + query_intent_boost, 2)
        out.append(ranked)

    out.sort(key=lambda x: (float(x.get("rank_score") or 0), float(x.get("overall_score") or 0)), reverse=True)
    return out
