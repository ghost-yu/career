from __future__ import annotations

from collections import Counter
import json
import re
from typing import Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, Response

from app.api.routes import match as match_routes
from app.db import sqlite as db
from app.services.exporter import export_report
from app.services.reporting import generate_report
from app.services.report_quality import check_markdown, polish_markdown
from app.services.retrieval import search_jobs
from app.services.scoring import score
from app.services.skill_proficiency import ability_verification_from_review
from app.services.student_profile import build_student_profile_from_manual, generate_student_profile_from_latest_resume
from app.utils.ids import now_iso
from app.utils.text import normalize_token

router = APIRouter()

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.#/_-]{1,}|[\u4e00-\u9fff]{2,}")
_MARKET_TOKEN_STOPWORDS = {
    "负责",
    "参与",
    "进行",
    "相关",
    "岗位",
    "职位",
    "工作",
    "要求",
    "经验",
    "能力",
    "优先",
    "以上",
    "公司",
    "我们",
    "团队",
    "完成",
    "良好",
    "熟悉",
}


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


def _weighted_overlap(text: str, terms: list[str], *, cap: int = 12) -> float:
    if not text or not terms:
        return 0.0
    total = 0.0
    for term in terms:
        if term and term in text:
            total += 1.0
            if total >= cap:
                return float(cap)
    return total


def _clamp_int(value: Any, *, default: int, min_value: int, max_value: int) -> int:
    try:
        out = int(value)
    except Exception:
        out = default
    return max(min_value, min(max_value, out))


def _clamp_float(value: Any, *, default: float, min_value: float, max_value: float) -> float:
    try:
        out = float(value)
    except Exception:
        out = default
    return max(min_value, min(max_value, out))


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


def _ensure_student_profile(student_id: str) -> dict[str, Any]:
    current = db.get_student_profile(student_id)
    if current and isinstance(current.get("profile"), dict):
        return current["profile"]
    try:
        generate_student_profile_from_latest_resume(student_id)
    except Exception:
        pass
    current = db.get_student_profile(student_id)
    if current and isinstance(current.get("profile"), dict):
        return current["profile"]
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
        return profile.model_dump()
    except Exception:
        return {}


def _build_student_terms(student_profile: dict[str, Any], *, role: dict[str, Any]) -> dict[str, Any]:
    hard_terms = _pick_terms(
        [item.get("mention") or item.get("name") for item in (student_profile.get("hard_skills") or [])[:20]],
        limit=28,
    )
    soft_terms = _pick_terms(
        [item.get("name") or item.get("mention") for item in (student_profile.get("soft_skills") or [])[:10]],
        limit=10,
    )
    role_terms = _pick_terms(
        [role.get("title_rep"), role.get("base_role"), role.get("role_key"), role.get("job_family")],
        limit=12,
    )
    pref = student_profile.get("preferences") or {}
    preferred_locations = [str(x).strip().lower() for x in (pref.get("preferred_locations") or []) if str(x).strip()]
    return {
        "hard_terms": hard_terms,
        "soft_terms": soft_terms,
        "role_terms": role_terms,
        "preferred_locations": preferred_locations,
    }


def _build_role_member_vector_scores(role: dict[str, Any], signals: dict[str, Any], member_ids: set[str], *, top_k_each: int) -> dict[str, float]:
    role_title = str(role.get("title_rep") or role.get("base_role") or "").strip()
    hard_terms = [str(x).strip() for x in (signals.get("hard_terms") or []) if str(x).strip()]
    queries = [role_title]
    if role_title and hard_terms:
        queries.append(f"{role_title} {' '.join(hard_terms[:2])}")
    if hard_terms:
        queries.append(" ".join(hard_terms[:3]))
    queries = [q for q in queries if q]
    if not queries:
        return {}
    score_map: dict[str, float] = {}
    k = max(40, min(800, int(top_k_each)))
    for query in queries[:3]:
        try:
            rows = search_jobs(query, top_k=k, use_embedding=False)
        except Exception:
            rows = []
        for rank, row in enumerate(rows):
            job_id = str(row.get("job_id") or "").strip()
            if not job_id or job_id not in member_ids:
                continue
            base = float(row.get("score") or row.get("tfidf_score") or 0.0)
            rank_gain = max(0.0, 1.0 - (rank / max(1.0, float(k))))
            merged = base * 0.72 + rank_gain * 0.28
            if merged > float(score_map.get(job_id) or 0.0):
                score_map[job_id] = merged
    if not score_map:
        return {}
    max_score = max(score_map.values())
    if max_score <= 0:
        return {}
    return {k: max(0.0, float(v) / max_score) for k, v in score_map.items()}


def _select_role_candidate_job_ids(
    student_id: str,
    role_id: str,
    *,
    max_jobs: int,
    coarse_pool: int,
    score_pool: int,
    vector_top_k_each: int,
    location_weight: float,
) -> tuple[list[str], dict[str, Any]]:
    members = [str(x).strip() for x in db.list_role_members(role_id) if str(x).strip()]
    dedup_members = list(dict.fromkeys(members))
    if not dedup_members:
        return [], {"role_member_total": 0}
    role = db.get_role(role_id) or {}
    student_profile = _ensure_student_profile(student_id)
    student_hard_count = _student_hard_skill_count(student_profile)
    role_query = str(role.get("title_rep") or role.get("base_role") or "").strip()
    signals = _build_student_terms(student_profile, role=role)
    match_signals = match_routes._student_signal_terms(student_profile, role_query)
    member_ids = set(dedup_members)
    vector_scores = _build_role_member_vector_scores(
        role,
        signals,
        member_ids,
        top_k_each=vector_top_k_each,
    )
    global_vector_scores = match_routes._job_vector_recall_scores(match_signals, role_query, top_k_each=vector_top_k_each)
    query_tokens = {normalize_token(x) for x in (match_signals.get("query_terms") or []) if normalize_token(x)}
    fusion_local_weight = 0.64
    fusion_match_weight = 0.36
    ranked_rows: list[dict[str, Any]] = []
    for job_id in dedup_members:
        job = db.get_job(job_id) or {}
        if not job:
            continue
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
        local_coarse = 0.0
        local_coarse += _weighted_overlap(text, signals.get("role_terms") or [], cap=8) * 3.2
        local_coarse += _weighted_overlap(text, signals.get("hard_terms") or [], cap=14) * 1.8
        local_coarse += _weighted_overlap(text, signals.get("soft_terms") or [], cap=8) * 0.8
        if signals.get("preferred_locations"):
            location_text = _norm_text(job.get("location"))
            for pref_loc in signals["preferred_locations"]:
                if pref_loc and pref_loc in location_text:
                    local_coarse += 5.0 * max(0.0, float(location_weight))
                    break
        local_coarse += 28.0 * float(vector_scores.get(job_id) or 0.0)
        profile = db.get_job_profile(job_id) or {}
        hard_count = len(((profile.get("profile") or {}).get("hard_skills") or []))
        local_coarse += _hard_skill_presence_adjust(student_hard_count, hard_count)

        match_coarse = float(match_routes._coarse_job_score(job, match_signals, location_weight=location_weight))
        match_coarse += 28.0 * float(global_vector_scores.get(job_id) or 0.0)
        keyword_bonus = 0.0
        if query_tokens:
            token_text = normalize_token(
                " ".join(
                    [
                        str(job.get("title") or ""),
                        str(job.get("company_name") or ""),
                        str(job.get("description") or "")[:1200],
                    ]
                )
            )
            if token_text:
                hits = sum(1 for tk in query_tokens if tk and tk in token_text)
                keyword_bonus = min(8.0, float(hits) * 2.2)
        match_coarse += keyword_bonus

        coarse = local_coarse * fusion_local_weight + match_coarse * fusion_match_weight
        ranked_rows.append(
            {
                "job_id": job_id,
                "coarse_score": coarse,
                "local_coarse_score": local_coarse,
                "match_coarse_score": match_coarse,
            }
        )
    ranked_rows.sort(key=lambda x: float(x.get("coarse_score") or 0.0), reverse=True)
    coarse_rows = ranked_rows[: max(1, min(len(ranked_rows), coarse_pool))]
    scoring_rows = coarse_rows[: max(0, min(len(coarse_rows), score_pool))]
    scored_rows: list[dict[str, Any]] = []
    score_failed = 0
    for row in scoring_rows:
        job_id = str(row.get("job_id") or "").strip()
        if not job_id:
            continue
        try:
            res = score(student_id, job_id, use_cache=True, use_semantic_review=False)
            scored_rows.append(
                {
                    "job_id": job_id,
                    "overall_score": float(res.overall_score),
                    "coarse_score": float(row.get("coarse_score") or 0.0),
                }
            )
        except Exception:
            score_failed += 1
            continue
    scored_rows.sort(
        key=lambda x: (float(x.get("overall_score") or 0.0), float(x.get("coarse_score") or 0.0)),
        reverse=True,
    )
    scored_id_set = {str(r.get("job_id") or "").strip() for r in scored_rows if str(r.get("job_id") or "").strip()}
    chosen: list[str] = []
    for row in scored_rows:
        job_id = str(row.get("job_id") or "").strip()
        if job_id and job_id not in chosen:
            chosen.append(job_id)
        if len(chosen) >= max_jobs:
            break
    if len(chosen) < max_jobs:
        for row in coarse_rows:
            job_id = str(row.get("job_id") or "").strip()
            if not job_id or job_id in chosen:
                continue
            chosen.append(job_id)
            if len(chosen) >= max_jobs:
                break
    diagnostics = {
        "role_title": str(role.get("title_rep") or role.get("base_role") or ""),
        "role_member_total": len(dedup_members),
        "fusion_enabled": True,
        "fusion_local_weight": fusion_local_weight,
        "fusion_match_weight": fusion_match_weight,
        "fusion_query": role_query,
        "vector_hits_in_role": len(vector_scores),
        "vector_hits_in_match_search": len([jid for jid in dedup_members if jid in global_vector_scores]),
        "coarse_pool": len(coarse_rows),
        "score_pool": len(scoring_rows),
        "scored_count": len(scored_rows),
        "score_failed": score_failed,
        "selected_from_scored": len([x for x in chosen if x in scored_id_set]),
        "student_hard_skill_count": student_hard_count,
        "location_weight": location_weight,
        "selected_count": len(chosen),
    }
    return chosen, diagnostics


def _term_from_skill_item(item: Any) -> str:
    if isinstance(item, dict):
        for key in ("name", "mention", "skill_id"):
            text = str(item.get(key) or "").strip()
            if text:
                return text
    text = str(item or "").strip()
    return text


def _build_role_planning_context(role_id: str, candidate_job_ids: list[str]) -> dict[str, Any]:
    role = db.get_role(role_id) or {}
    role_profile = db.get_role_profile(role_id) or {}
    role_profile_data = (role_profile.get("profile") or {}) if isinstance(role_profile, dict) else {}
    top_hard_skills = [
        _term_from_skill_item(x)
        for x in (role_profile_data.get("top_hard_skills") or [])[:16]
        if _term_from_skill_item(x)
    ]
    salary_stats = role_profile_data.get("salary_stats") or {}

    company_counter: Counter[str] = Counter()
    location_counter: Counter[str] = Counter()
    token_counter: Counter[str] = Counter()
    for job_id in candidate_job_ids:
        job = db.get_job(str(job_id).strip()) or {}
        company = str(job.get("company_name") or "").strip()
        location = str(job.get("location") or "").strip()
        if company:
            company_counter[company] += 1
        if location:
            location_counter[location] += 1
        title = str(job.get("title") or "")
        desc = str(job.get("description") or "")[:800]
        for token in _tokenize(f"{title} {desc}"):
            t = str(token).strip()
            if not t:
                continue
            if t.lower() in _MARKET_TOKEN_STOPWORDS or t in _MARKET_TOKEN_STOPWORDS:
                continue
            if len(t) <= 1:
                continue
            token_counter[t] += 1

    frequent_terms = [name for name, _ in token_counter.most_common(16)]
    keyword_candidates = _pick_terms(
        [
            role.get("title_rep"),
            role.get("base_role"),
            role.get("job_family"),
            " ".join(top_hard_skills[:12]),
            " ".join(frequent_terms[:12]),
        ],
        limit=24,
    )
    market_keywords: list[str] = []
    seen: set[str] = set()
    for term in top_hard_skills + keyword_candidates + frequent_terms:
        text = str(term).strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        market_keywords.append(text)
        if len(market_keywords) >= 18:
            break

    top_locations = [name for name, _ in location_counter.most_common(5)]
    top_companies = [name for name, _ in company_counter.most_common(8)]
    trend_points: list[str] = []
    if top_hard_skills:
        trend_points.append(f"方向高频技能集中在：{'、'.join(top_hard_skills[:8])}")
    if top_locations:
        trend_points.append(f"岗位需求更集中的城市：{'、'.join(top_locations[:4])}")
    if isinstance(salary_stats, dict) and salary_stats:
        median_min = salary_stats.get("median_min")
        median_max = salary_stats.get("median_max")
        if median_min or median_max:
            trend_points.append(f"样本薪资中位区间约：{median_min or '-'} ~ {median_max or '-'}")
    if top_companies:
        trend_points.append(f"样本企业分布（非唯一目标）：{'、'.join(top_companies[:5])}")

    return {
        "role_id": str(role_id or "").strip(),
        "role_title": str(role.get("title_rep") or role.get("base_role") or "").strip(),
        "job_family": str(role.get("job_family") or "").strip(),
        "candidate_job_count": len(candidate_job_ids),
        "market_keywords": market_keywords,
        "top_hard_skills": top_hard_skills[:12],
        "top_locations": top_locations,
        "top_companies": top_companies,
        "salary_stats": salary_stats if isinstance(salary_stats, dict) else {},
        "trend_points": trend_points,
    }


@router.post("/generate")
def gen(body: dict[str, Any]) -> dict[str, Any]:
    student_id = body.get("student_id")
    target_job_ids = body.get("target_job_ids") or []
    if not student_id or not target_job_ids:
        return {"error": "student_id and target_job_ids required"}
    report = generate_report(student_id, target_job_ids)
    return report.model_dump()


@router.post("/generate_for_role")
def gen_for_role(body: dict[str, Any]) -> dict[str, Any]:
    student_id = body.get("student_id")
    role_id = body.get("role_id")
    max_jobs = _clamp_int(body.get("max_jobs"), default=12, min_value=5, max_value=30)
    coarse_pool = _clamp_int(body.get("coarse_pool"), default=max(80, max_jobs * 4), min_value=max_jobs, max_value=300)
    score_pool = _clamp_int(body.get("score_pool"), default=max(6, min(10, max_jobs)), min_value=0, max_value=80)
    vector_top_k_each = _clamp_int(body.get("vector_top_k_each"), default=320, min_value=80, max_value=800)
    location_weight = _clamp_float(body.get("location_weight"), default=1.0, min_value=0.0, max_value=2.0)
    if not student_id or not role_id:
        return {"error": "student_id and role_id required"}
    selected_job_ids, diagnostics = _select_role_candidate_job_ids(
        student_id,
        role_id,
        max_jobs=max_jobs,
        coarse_pool=coarse_pool,
        score_pool=score_pool,
        vector_top_k_each=vector_top_k_each,
        location_weight=location_weight,
    )
    if not selected_job_ids:
        return {"error": "role_has_no_jobs"}
    planning_context = _build_role_planning_context(role_id, selected_job_ids)
    report = generate_report(student_id, selected_job_ids, planning_context=planning_context)
    data = report.model_dump()
    data["role_id"] = role_id
    data["candidate_job_ids"] = selected_job_ids
    data["candidate_diagnostics"] = diagnostics
    data["planning_context"] = planning_context
    return data


@router.get("/{report_id}")
def get(report_id: str) -> dict[str, Any]:
    r = db.get_report(report_id)
    if not r:
        return {"error": "not_found"}
    return {
        "report_id": r["report_id"],
        "student_id": r["student_id"],
        "version": r["version"],
        "content_json": json.loads(r["content_json"]),
        "content_md": r["content_md"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
    }


@router.put("/{report_id}")
def update(report_id: str, body: dict[str, Any]) -> dict[str, Any]:
    content_md = body.get("content_md")
    content_json = body.get("content_json")
    if content_md is None or content_json is None:
        return {"error": "content_md and content_json required"}
    db.update_report(
        report_id,
        content_json=json.dumps(content_json, ensure_ascii=False),
        content_md=content_md,
        updated_at=now_iso(),
    )
    return {"ok": True}


@router.post("/{report_id}/check")
def check(report_id: str) -> dict[str, Any]:
    r = db.get_report(report_id)
    if not r:
        return {"error": "not_found"}
    issues = check_markdown(r["content_md"])
    return {"report_id": report_id, "issues": issues, "issue_count": len(issues)}


@router.post("/{report_id}/polish")
async def polish(report_id: str, body: dict[str, Any]) -> dict[str, Any]:
    r = db.get_report(report_id)
    if not r:
        return {"error": "not_found"}

    style = body.get("style") or "professional"
    apply = bool(body.get("apply", False))

    new_md = await polish_markdown(r["content_md"], style=style)
    content_json = json.loads(r["content_json"]) if r.get("content_json") else {}
    content_json["markdown"] = new_md

    if apply:
        db.update_report(
            report_id,
            content_json=json.dumps(content_json, ensure_ascii=False),
            content_md=new_md,
            updated_at=now_iso(),
        )

    return {"report_id": report_id, "applied": apply, "markdown": new_md}


@router.post("/{report_id}/append_interview_summary")
def append_interview_summary(report_id: str, body: dict[str, Any]) -> dict[str, Any]:
    r = db.get_report(report_id)
    if not r:
        return {"error": "not_found"}

    raw_md = str(body.get("report_markdown") or "").strip()
    if not raw_md:
        raw_md = _build_interview_markdown(body)
    if not raw_md:
        return {"error": "report_markdown required"}

    content_json = json.loads(r["content_json"]) if r.get("content_json") else {}
    interview_review = {
        "summary": str(body.get("summary") or "").strip(),
        "overall_score": body.get("overall_score"),
        "strengths": body.get("strengths") or [],
        "priority_gaps": body.get("priority_gaps") or [],
        "action_items": body.get("action_items") or [],
        "coding_practice_plan": body.get("coding_practice_plan") or [],
        "coding_review": body.get("coding_review") or {},
        "coding_challenge": body.get("coding_challenge") or {},
        "report_markdown": raw_md,
        "updated_at": now_iso(),
    }
    interview_review["report_id"] = report_id
    content_json["interview_review"] = interview_review
    _update_student_ability_verification(r.get("student_id"), interview_review)

    current_md = str(r.get("content_md") or "").rstrip()
    marker = "\n## 6. 模拟面试复盘\n"
    section_md = raw_md
    if not section_md.lstrip().startswith("## 6."):
        section_md = f"## 6. 模拟面试复盘\n{section_md.lstrip('# ').strip()}"

    if marker.strip() in current_md:
        prefix = current_md.split(marker.strip(), 1)[0].rstrip()
        next_md = f"{prefix}\n\n{section_md.strip()}\n"
    else:
        next_md = f"{current_md}\n\n{section_md.strip()}\n"

    content_json["markdown"] = next_md
    db.update_report(
        report_id,
        content_json=json.dumps(content_json, ensure_ascii=False),
        content_md=next_md,
        updated_at=now_iso(),
    )
    return {"ok": True, "report_id": report_id, "markdown": next_md, "interview_review": interview_review}


def _update_student_ability_verification(student_id: str | None, review_payload: dict[str, Any]) -> None:
    sid = str(student_id or "").strip()
    if not sid:
        return
    profile_row = db.get_student_profile(sid)
    if not profile_row or not isinstance(profile_row.get("profile"), dict):
        return
    coding_review = review_payload.get("coding_review") if isinstance(review_payload.get("coding_review"), dict) else {}
    coding_challenge = review_payload.get("coding_challenge") if isinstance(review_payload.get("coding_challenge"), dict) else {}
    verification = ability_verification_from_review(coding_review, coding_challenge)
    if not verification:
        return
    profile = dict(profile_row.get("profile") or {})
    meta = dict(profile.get("extraction_meta") or {})
    rows = list(meta.get("ability_verification") or [])
    rows.append(
        {
            **verification,
            "report_id": str(review_payload.get("report_id") or "").strip(),
            "updated_at": str(review_payload.get("updated_at") or now_iso()).strip(),
        }
    )
    meta["ability_verification"] = rows[-8:]
    meta["ability_verification_source"] = "interview_coding_report"
    profile["extraction_meta"] = meta
    db.upsert_student_profile(sid, profile_json=json.dumps(profile, ensure_ascii=False), updated_at=now_iso())


def _build_interview_markdown(body: dict[str, Any]) -> str:
    lines = ["## 6. 模拟面试复盘\n"]
    summary_text = str(body.get("summary") or "").strip()
    if summary_text:
        lines.append(f"{summary_text}\n")
    score = body.get("overall_score")
    if score is not None:
        lines.append(f"- 模拟面试综合分：**{score}**\n")
    strengths = [str(x).strip() for x in (body.get("strengths") or []) if str(x).strip()]
    gaps = [str(x).strip() for x in (body.get("priority_gaps") or []) if str(x).strip()]
    actions = [str(x).strip() for x in (body.get("action_items") or []) if str(x).strip()]
    coding_plan = [str(x).strip() for x in (body.get("coding_practice_plan") or []) if str(x).strip()]
    coding_review = body.get("coding_review") if isinstance(body.get("coding_review"), dict) else {}
    if strengths:
        lines.append("\n### 面试表现优势\n")
        lines.extend([f"- {x}\n" for x in strengths[:6]])
    if gaps:
        lines.append("\n### 优先改进短板\n")
        lines.extend([f"- {x}\n" for x in gaps[:6]])
    if actions:
        lines.append("\n### 后续训练动作\n")
        lines.extend([f"- {x}\n" for x in actions[:8]])
    if coding_review or coding_plan:
        lines.append("\n### 岗位代码小测\n")
        coding_score = coding_review.get("overall_score") if coding_review else None
        if coding_score is not None:
            lines.append(f"- 代码小测综合分：**{coding_score}**\n")
        coding_note = str(coding_review.get("interview_note") or "").strip() if coding_review else ""
        if coding_note:
            lines.append(f"- 技能验证结论：{coding_note}\n")
        if coding_plan:
            lines.append("\n### 代码能力补强计划\n")
            lines.extend([f"- {x}\n" for x in coding_plan[:6]])
    return "".join(lines).strip()


@router.get("/{report_id}/export")
def export(report_id: str, format: Literal["pdf", "docx"] = "pdf") -> Response:
    data, filename = export_report(report_id, format)
    media = "application/pdf" if format == "pdf" else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    disposition = f"attachment; filename=report.{format}; filename*=UTF-8''{quote(filename, safe='')}"
    return Response(content=data, media_type=media, headers={"Content-Disposition": disposition})
