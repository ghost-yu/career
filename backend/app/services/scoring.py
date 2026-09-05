from __future__ import annotations

import json
from typing import Any

from app.db import sqlite as db
from app.schemas.match import EvidenceSpan, MatchedSkill, MatchResult, TransferableSkill
from app.services.dictionary_cache import dictionary_cache
from app.services.job_profile import infer_job_family
from app.services.llm import llm_client
from app.services.skill_proficiency import (
    DEFAULT_JOB_LEVEL,
    DEFAULT_STUDENT_LEVEL,
    infer_required_proficiency_from_text,
    infer_student_proficiency_from_evidence,
    merge_proficiency_with_verification,
    proficiency_info,
)
from app.utils.ids import now_iso
from app.utils.text import normalize_token

DEFAULT_WEIGHTS = {"basic": 0.2, "skills": 0.45, "qualities": 0.15, "potential": 0.20}
SCORE_VERSION = "score_v2.5"

FAMILY_SIMILAR = {
    "backend": {"data", "ops", "ai", "security", "mobile"},
    "frontend": {"mobile", "product", "design"},
    "data": {"backend", "ai", "product"},
    "ai": {"data", "backend", "research"},
    "qa": {"backend", "ops", "implementation"},
    "ops": {"backend", "security", "implementation"},
    "product": {"frontend", "design", "implementation", "data"},
    "design": {"frontend", "product"},
    "implementation": {"support", "qa", "ops", "product"},
    "support": {"implementation", "product", "ops"},
    "security": {"ops", "backend", "qa"},
    "embedded": {"mobile", "backend", "qa"},
    "mobile": {"frontend", "backend", "product"},
    "research": {"ai", "data"},
}

_SEMANTIC_EQUIV_GROUPS_RAW = [
    {"rabbitmq", "消息队列", "mq", "message queue", "amqp"},
    {"kafka", "消息队列", "mq", "stream", "流处理"},
    {"redis", "cache", "缓存"},
    {"mysql", "postgresql", "sql", "数据库", "rdbms"},
]
_SEMANTIC_EQUIV_GROUPS = [
    {normalize_token(token) for token in group if normalize_token(token)}
    for group in _SEMANTIC_EQUIV_GROUPS_RAW
]


def _get_weights_for_job(job_profile: dict[str, Any] | None) -> dict[str, float]:
    if job_profile and job_profile.get("job_family"):
        w = db.get_weights(f"job_family:{job_profile.get('job_family')}")
        if w:
            return w["weights"]
    w0 = db.get_weights("default")
    return (w0["weights"] if w0 else DEFAULT_WEIGHTS)


def _importance_weight(importance: str) -> float:
    return {"must": 2.0, "must_low": 1.25, "plus": 0.8}.get((importance or "must").lower(), 1.0)


def _skill_category(item_id: str) -> str | None:
    snap = dictionary_cache.get_snapshot(force=False)
    for it in snap.items:
        if it.get("item_id") == item_id:
            return it.get("category_lv1")
    return None


def _dictionary_item_by_id(item_id: str) -> dict[str, Any] | None:
    sid = str(item_id or "").strip()
    if not sid:
        return None
    snap = dictionary_cache.get_snapshot(force=False)
    for it in snap.items:
        if str(it.get("item_id") or "").strip() == sid:
            return it
    return None


def _resolve_skill_id(skill_id: Any, mention: Any) -> str | None:
    raw_sid = str(skill_id or "").strip()
    raw_name = str(mention or "").strip()
    if raw_sid and _dictionary_item_by_id(raw_sid):
        return raw_sid
    if raw_sid:
        hit = dictionary_cache.lookup_by_alias(raw_sid)
        if hit and hit.get("item_type") == "hard_skill":
            val = str(hit.get("item_id") or "").strip()
            return val or None
    if raw_name:
        hit = dictionary_cache.lookup_by_alias(raw_name)
        if hit and hit.get("item_type") == "hard_skill":
            val = str(hit.get("item_id") or "").strip()
            return val or None
    return None


def _skill_token_set(skill_id: Any, name: Any) -> set[str]:
    out: set[str] = set()
    sid = str(skill_id or "").strip()
    raw_name = str(name or "").strip()
    if raw_name:
        tk = normalize_token(raw_name)
        if tk:
            out.add(tk)
    if sid:
        item = _dictionary_item_by_id(sid)
        if item:
            for value in [item.get("name_zh"), item.get("name_en"), *(item.get("aliases") or [])]:
                tk = normalize_token(value)
                if tk:
                    out.add(tk)
    expanded = set(out)
    for token in list(out):
        for group in _SEMANTIC_EQUIV_GROUPS:
            if token in group:
                expanded.update(group)
    return expanded


def _student_skill_map(student_profile: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for s in student_profile.get("hard_skills") or []:
        sid = _resolve_skill_id(s.get("skill_id"), s.get("mention"))
        if sid and sid not in out:
            out[sid] = s
    return out


def _student_skill_token_map(student_profile: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for s in student_profile.get("hard_skills") or []:
        sid = _resolve_skill_id(s.get("skill_id"), s.get("mention"))
        name = str(s.get("mention") or s.get("skill_id") or "").strip()
        for token in _skill_token_set(sid, name):
            if token and token not in out:
                out[token] = s
    return out


def _ability_verification_map(student_profile: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    meta = student_profile.get("extraction_meta") if isinstance(student_profile.get("extraction_meta"), dict) else {}
    for row in meta.get("ability_verification") or []:
        if not isinstance(row, dict):
            continue
        for skill in row.get("skills") or []:
            token = normalize_token(skill)
            if token:
                out[token] = row
    return out


def _verification_for_skill(skill_name: str, verification_map: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    key = normalize_token(skill_name)
    if not key:
        return None
    for token, row in verification_map.items():
        if token and (token in key or key in token):
            return row
    return None


def _required_skill_proficiency(job_skill: dict[str, Any], job_profile: dict[str, Any], job_title: str = "") -> dict[str, Any]:
    explicit = job_skill.get("proficiency") or job_skill.get("level")
    if explicit:
        return proficiency_info(explicit, default=DEFAULT_JOB_LEVEL)
    text = " ".join(
        str(x or "")
        for x in [
            job_title,
            job_skill.get("mention"),
            job_skill.get("evidence"),
            job_skill.get("source_section"),
            " ".join(str(x.get("mention") or "") for x in (job_profile.get("hard_skills") or []) if isinstance(x, dict)),
        ]
    )
    return infer_required_proficiency_from_text(str(job_skill.get("mention") or job_skill.get("skill_id") or ""), text, default=DEFAULT_JOB_LEVEL)


def _student_effective_proficiency(
    skill_name: str,
    skill_item: dict[str, Any] | None,
    student_profile: dict[str, Any],
    verification_map: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    prof = infer_student_proficiency_from_evidence(skill_name, skill_item or {}, str(student_profile.get("resume_text") or student_profile.get("profile_notes") or ""))
    verification = _verification_for_skill(skill_name, verification_map)
    if verification:
        merged = merge_proficiency_with_verification(
            prof.get("level"),
            verification_level=verification.get("level"),
            verification_score=verification.get("overall_score"),
        )
        return {
            **merged,
            "evidence": verification.get("evidence") or prof.get("evidence"),
            "source": "ability_verification",
            "verification": verification,
        }
    return prof


def _family_relation(student_family: str | None, job_family: str | None) -> tuple[str, float]:
    sf = str(student_family or "").strip().lower()
    jf = str(job_family or "").strip().lower()
    if not sf or not jf:
        return "unknown", 1.0
    if sf == jf:
        return "high", 1.0
    if jf in FAMILY_SIMILAR.get(sf, set()) or sf in FAMILY_SIMILAR.get(jf, set()):
        return "medium", 0.78
    return "low", 0.42


def _build_candidate_job_skills(
    student_profile: dict[str, Any],
    job_profile: dict[str, Any],
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    student_map = _student_skill_map(student_profile)
    student_token_map = _student_skill_token_map(student_profile)
    student_ids = set(student_map.keys())
    student_names = [str(item.get("mention") or "") for item in student_map.values()]
    student_text = normalize_token(
        "\n".join(
            student_names
            + [str(item.get("name") or "") for item in (student_profile.get("soft_skills") or [])]
            + [str(item.get("name") or "") for item in (student_profile.get("certificates") or [])]
            + [str((student_profile.get("preferences") or {}).get("notes") or "")]
        )
    )
    student_categories = {_skill_category(sid) for sid in student_ids}

    ranked: list[tuple[float, int, str, dict[str, Any]]] = []
    for idx, skill in enumerate(job_profile.get("hard_skills") or []):
        sid = _resolve_skill_id(skill.get("skill_id"), skill.get("mention"))
        name = str(skill.get("mention") or sid).strip()
        if not name:
            continue
        importance = str(skill.get("importance") or "must")

        score = 0.0
        reasons: list[str] = []
        if sid and sid in student_ids:
            score += 7.0
            reasons.append("exact_skill_id_match")
        else:
            job_tokens = _skill_token_set(sid, name)
            if job_tokens and any(token in student_token_map for token in job_tokens):
                score += 4.2
                reasons.append("alias_or_synonym_match")

        norm_name = normalize_token(name)
        if norm_name and norm_name in student_text:
            score += 3.0
            reasons.append("keyword_hit")

        category = _skill_category(sid) if sid else None
        if category and category in student_categories:
            score += 1.5
            reasons.append(f"same_category:{category}")

        score += _importance_weight(importance) * 0.8
        if importance == "must":
            reasons.append("importance:must")
        elif importance == "must_low":
            reasons.append("importance:must_low")
        else:
            reasons.append("importance:plus")

        ranked.append(
            (
                score,
                -idx,
                sid or name,
                {
                    "skill_id": sid or None,
                    "name": name,
                    "importance": importance,
                    "retrieval_score": round(score, 4),
                    "reasons": reasons,
                },
            )
        )

    ranked.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
    return [item[3] for item in ranked[:limit]]


def _semantic_review(
    student_profile: dict[str, Any],
    job_profile: dict[str, Any],
    current_scores: dict[str, Any],
    *,
    candidate_skills: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    if not llm_client.is_enabled():
        return None
    candidate_skills = candidate_skills or []
    candidate_names = [str(x.get("name") or "") for x in candidate_skills if str(x.get("name") or "").strip()]

    system = """你是大学生求职匹配评审助手。请根据学生画像与岗位画像，对人岗匹配做语义复核，只输出 JSON。
格式：
{
  \"relevance\": \"high|medium|low\",
  \"basic\": 0-100,
  \"skills\": 0-100,
  \"qualities\": 0-100,
  \"potential\": 0-100,
  \"matched_skills\": [\"技能1\", \"技能2\"],
  \"gap_skills\": [\"技能1\", \"技能2\"],
  \"transferable_skills\": [\"技能1->技能2\"],
  \"summary\": \"一句话总结\"
}
要求：
1. 如果学生方向与岗位方向明显不一致，relevance 必须是 low。
2. 不能编造不存在的技能或经历。
3. 分数要严格，弱相关岗位不要给高分。
4. 仅围绕输入中的 candidate_hard_skills_top20 进行技能语义复核与差距分析。
"""
    payload = {
        "student": {
            "hard_skills": [x.get("mention") for x in student_profile.get("hard_skills") or []][:20],
            "soft_skills": [x.get("name") for x in student_profile.get("soft_skills") or []][:10],
            "certificates": [x.get("name") for x in student_profile.get("certificates") or []][:8],
            "experience": student_profile.get("experience") or {},
            "preferences": student_profile.get("preferences") or {},
        },
        "job": {
            "job_family": job_profile.get("job_family") or infer_job_family(str(job_profile.get("title") or "")),
            "hard_skills": candidate_names[:20],
            "soft_skills": [x.get("name") for x in job_profile.get("soft_skills") or []][:10],
            "certificates": [x.get("name") for x in job_profile.get("certificates") or []][:8],
            "basic_requirements": job_profile.get("basic_requirements") or {},
        },
        "token_optimization": {
            "candidate_hard_skills_top20": candidate_skills[:20],
            "original_job_hard_skill_count": len(job_profile.get("hard_skills") or []),
        },
        "current": current_scores,
    }
    try:
        return llm_client.chat_json_sync(
            system,
            json.dumps(payload, ensure_ascii=False),
            trace_context="scoring.semantic_review",
        )
    except Exception:
        return None


def score(
    student_id: str,
    job_id: str,
    use_cache: bool = True,
    use_semantic_review: bool = True,
) -> MatchResult:
    if use_cache:
        cached = db.get_match_cache(student_id, job_id)
        if cached and cached.get("result"):
            try:
                cached_result = cached["result"]
                # Recompute when scoring logic version changes to avoid stale match behavior.
                if str(cached_result.get("version") or "") != SCORE_VERSION:
                    pass
                # If caller needs semantic review but cached item has no semantic payload,
                # continue and recompute once to avoid serving low-fidelity cache forever.
                elif use_semantic_review and llm_client.is_enabled() and not cached_result.get("semantic_review"):
                    pass
                else:
                    return MatchResult(**cached_result)
            except Exception:
                pass

    jobp = db.get_job_profile(job_id)
    stup = db.get_student_profile(student_id)
    if not jobp:
        raise ValueError("Job profile not found. Generate it first.")
    if not stup:
        raise ValueError("Student profile not found. Generate it first.")
    job_profile = jobp["profile"]
    student_profile = stup["profile"]
    weights = _get_weights_for_job(job_profile)

    pref_families = (student_profile.get("preferences") or {}).get("preferred_job_families") or []
    student_family = pref_families[0] if pref_families else None
    job_family = job_profile.get("job_family") or infer_job_family(str((db.get_job(job_id) or {}).get("title") or ""))
    relation, relation_factor = _family_relation(student_family, job_family)
    llm_candidate_skills = _build_candidate_job_skills(student_profile, job_profile, limit=20)

    # Basic
    basic_score = 85.0
    basic_details = []
    pref_locs = (student_profile.get("preferences") or {}).get("preferred_locations") or []
    job_locs = (job_profile.get("basic_requirements") or {}).get("location") or []
    if pref_locs and job_locs:
        ok = any(pl in jl or jl in pl for pl in pref_locs for jl in job_locs)
        basic_details.append({"item": "地点偏好", "result": "匹配" if ok else "不匹配", "evidence": f"期望:{pref_locs} / 岗位:{job_locs}"})
        if not ok:
            basic_score -= 12
    basic_details.append({"item": "方向相关性", "result": relation, "evidence": f"学生:{student_family} / 岗位:{job_family}"})
    if relation == "low":
        basic_score -= 28
    elif relation == "medium":
        basic_score -= 8
    basic_score = max(0.0, min(100.0, basic_score))

    # Skills
    student_skills = _student_skill_map(student_profile)
    student_skill_tokens = _student_skill_token_map(student_profile)
    verification_map = _ability_verification_map(student_profile)
    matched = []
    missing = []
    transferable = []
    numer = 0.0
    denom = 0.0
    missing_must = 0
    student_categories: dict[str, list[str]] = {}
    for sid in student_skills.keys():
        cat = _skill_category(sid)
        if cat:
            student_categories.setdefault(cat, []).append(sid)
    for js in job_profile.get("hard_skills") or []:
        sid = _resolve_skill_id(js.get("skill_id"), js.get("mention"))
        fallback_sid = str(js.get("skill_id") or js.get("mention") or "").strip()
        name = str(js.get("mention") or sid or fallback_sid)
        importance = str(js.get("importance") or "must")
        weight = _importance_weight(importance)
        required_prof = _required_skill_proficiency(js, job_profile, str((db.get_job(job_id) or {}).get("title") or ""))
        denom += weight
        if sid and sid in student_skills:
            s = student_skills[sid]
            student_prof = _student_effective_proficiency(name, s, student_profile, verification_map)
            prof_ratio = min(1.0, float(student_prof.get("score") or 0.0) / max(0.35, float(required_prof.get("score") or 1.0)))
            numer += weight * prof_ratio
            row = MatchedSkill(skill_id=sid, name=name, match=round(prof_ratio, 2), importance=importance, confidence=js.get("confidence"), evidence=EvidenceSpan(doc_type="resume", section=s.get("source_section"), text=s.get("evidence") or s.get("mention") or name)).model_dump()
            row["student_proficiency"] = student_prof
            row["required_proficiency"] = required_prof
            matched.append(row)
            continue

        job_tokens = _skill_token_set(sid, name)
        token_hit = next((student_skill_tokens[token] for token in job_tokens if token in student_skill_tokens), None)
        if token_hit and relation != "low":
            from_name = str(token_hit.get("mention") or token_hit.get("skill_id") or "可迁移技能").strip()
            student_prof = _student_effective_proficiency(from_name, token_hit, student_profile, verification_map)
            prof_ratio = min(1.0, float(student_prof.get("score") or 0.0) / max(0.35, float(required_prof.get("score") or 1.0)))
            match_value = 0.62 * prof_ratio
            numer += weight * match_value
            transferable.append(
                TransferableSkill(
                    from_skill=from_name,
                    to_skill=sid or fallback_sid or name,
                    reason="别名/同义词语义匹配",
                    confidence=0.74,
                ).model_dump()
            )
            matched.append(
                MatchedSkill(
                    skill_id=sid,
                    name=name,
                    match=round(match_value, 2),
                    importance=importance,
                    confidence=js.get("confidence"),
                    evidence=EvidenceSpan(
                        doc_type="resume",
                        section=token_hit.get("source_section") or "skills",
                        text=token_hit.get("evidence") or f"{from_name} -> {name}",
                    ),
                ).model_dump()
            )
            matched[-1]["student_proficiency"] = student_prof
            matched[-1]["required_proficiency"] = required_prof
            continue

        target_skill_id = sid or fallback_sid or name
        cat = _skill_category(sid) if sid else None
        candidate = (student_categories.get(cat) or [None])[0] if cat else None
        if candidate and relation != "low":
            numer += weight * 0.28
            transferable.append(TransferableSkill(from_skill=candidate, to_skill=target_skill_id, reason=f"同类技能迁移（{cat}）", confidence=0.62).model_dump())
            matched.append(MatchedSkill(skill_id=sid or fallback_sid, name=name, match=0.28, importance=importance, confidence=js.get("confidence"), evidence=EvidenceSpan(doc_type="resume", section="skills", text="可迁移技能")).model_dump())
            matched[-1]["student_proficiency"] = proficiency_info(DEFAULT_STUDENT_LEVEL, default=DEFAULT_STUDENT_LEVEL)
            matched[-1]["required_proficiency"] = required_prof
        else:
            missing.append(MatchedSkill(skill_id=sid or fallback_sid, name=name, match=0.0, importance=importance, confidence=js.get("confidence"), evidence=EvidenceSpan(doc_type="job", section=js.get("source_section"), text=js.get("evidence") or name)).model_dump())
            missing[-1]["required_proficiency"] = required_prof
            if importance == "must":
                missing_must += 1
    if denom > 0:
        skills_score = 100.0 * numer / denom
        skills_score *= relation_factor
        if missing_must >= 3:
            skills_score = min(skills_score, 55.0)
    else:
        # No explicit hard-skill requirement in JD:
        # keep it neutral-high instead of forcing 0, and still respect family relation.
        student_hard_count = len(student_skills)
        base_free_skill_score = 82.0 if student_hard_count == 0 else 74.0
        skills_score = base_free_skill_score
        if relation == "medium":
            skills_score *= 0.9
        elif relation == "low":
            skills_score *= 0.65
    skills_score = max(0.0, min(100.0, skills_score))

    # Qualities
    student_soft = {str(s.get("name") or "").strip() for s in student_profile.get("soft_skills") or [] if str(s.get("name") or "").strip()}
    job_soft = [str(s.get("name") or "").strip() for s in job_profile.get("soft_skills") or [] if str(s.get("name") or "").strip()]
    soft_hit = len(student_soft & set(job_soft))
    q_score = 45.0 + soft_hit * 10.0 + min(15.0, len(student_soft) * 2.0)
    if relation == "low":
        q_score -= 10
    q_score = max(0.0, min(100.0, q_score))
    q_signals = [{"name": s.get("name"), "evidence": s.get("evidence"), "strength": s.get("strength") or "weak"} for s in (student_profile.get("soft_skills") or [])[:10]]

    # Potential
    exp = student_profile.get("experience") or {}
    exp_evidence = ((student_profile.get("extraction_meta") or {}).get("experience_evidence") or {})
    evidence_lines = 0
    for value in exp_evidence.values():
        if isinstance(value, list):
            evidence_lines += len([x for x in value if str(x or "").strip()])
    p_score = 35.0
    p_score += min(22.0, float(exp.get("projects") or 0) * 4.0)
    p_score += min(18.0, float(exp.get("internships") or 0) * 9.0)
    p_score += min(10.0, float(exp.get("open_source") or 0) * 4.0)
    p_score += min(8.0, float(exp.get("awards") or 0) * 2.5)
    p_score += min(7.0, float(exp.get("leadership") or 0) * 3.5)
    p_score += min(12.0, evidence_lines * 1.5)
    if (
        float(exp.get("projects") or 0)
        + float(exp.get("internships") or 0)
        + float(exp.get("open_source") or 0)
        + float(exp.get("awards") or 0)
        + float(exp.get("leadership") or 0)
    ) > 0 and evidence_lines == 0:
        p_score -= 8.0
    if relation == "low":
        p_score -= 12
    p_score = max(0.0, min(100.0, p_score))
    p_signals = [{"name": k, "value": v} for k, v in exp.items()]
    p_signals.append({"name": "experience_evidence_lines", "value": evidence_lines})

    pre = {
        "basic": basic_score,
        "skills": skills_score,
        "qualities": q_score,
        "potential": p_score,
        "relation": relation,
    }
    semantic = None
    if use_semantic_review:
        semantic = _semantic_review(student_profile, job_profile, pre, candidate_skills=llm_candidate_skills)
    if semantic:
        # blend with AI review but keep guardrails
        for key, base in [("basic", basic_score), ("skills", skills_score), ("qualities", q_score), ("potential", p_score)]:
            try:
                ai = float(semantic.get(key))
            except Exception:
                ai = base
            blended = base * 0.65 + ai * 0.35
            if key == "skills":
                skills_score = max(0.0, min(100.0, blended))
            elif key == "basic":
                basic_score = max(0.0, min(100.0, blended))
            elif key == "qualities":
                q_score = max(0.0, min(100.0, blended))
            elif key == "potential":
                p_score = max(0.0, min(100.0, blended))
        if semantic.get("relevance") == "low":
            skills_score = min(skills_score, 45.0)
            basic_score = min(basic_score, 58.0)
        semantic_matched = set(semantic.get("matched_skills") or [])
        semantic_gaps = set(semantic.get("gap_skills") or [])
    else:
        semantic_matched = set()
        semantic_gaps = set()

    overall = (
        weights.get("basic", DEFAULT_WEIGHTS["basic"]) * basic_score
        + weights.get("skills", DEFAULT_WEIGHTS["skills"]) * skills_score
        + weights.get("qualities", DEFAULT_WEIGHTS["qualities"]) * q_score
        + weights.get("potential", DEFAULT_WEIGHTS["potential"]) * p_score
    )
    if relation == "low":
        overall = min(overall, 52.0)
    overall = round(max(0.0, min(100.0, overall)), 2)

    result = MatchResult(
        student_id=student_id,
        job_id=job_id,
        overall_score=overall,
        weights=weights,
        version=SCORE_VERSION,
        dimension_scores={
            "basic": {"score": round(basic_score, 2), "passed_gates": relation != "low", "details": basic_details},
            "skills": {
                "score": round(skills_score, 2),
                "matched": matched,
                "missing": missing,
                "transferable": transferable,
                "relation": relation,
                "llm_candidate_top20": llm_candidate_skills,
                "semantic_matched_skills": list(semantic_matched),
                "semantic_gap_skills": list(semantic_gaps),
                "proficiency_evidence": [row for row in matched if row.get("student_proficiency") or row.get("required_proficiency")][:10],
                "ability_verification": list((student_profile.get("extraction_meta") or {}).get("ability_verification") or [])[-3:],
            },
            "qualities": {"score": round(q_score, 2), "signals": q_signals},
            "potential": {"score": round(p_score, 2), "signals": p_signals},
        },
    )
    data = result.model_dump()
    if semantic:
        data["semantic_review"] = semantic
    db.upsert_match_cache(student_id, job_id, json.dumps(data, ensure_ascii=False), updated_at=now_iso())
    return MatchResult(**data)
