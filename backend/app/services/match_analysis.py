from __future__ import annotations

import json
from typing import Any

from app.db import sqlite as db
from app.services.llm import llm_client
from app.utils.labels import job_family_label


def _name_list(items: Any, *keys: str, limit: int = 6) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items or []:
        if isinstance(item, str):
            raw = item
        elif isinstance(item, dict):
            raw = ""
            for key in keys:
                value = item.get(key)
                if value:
                    raw = str(value)
                    break
        else:
            raw = ""
        name = str(raw or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(name)
        if len(out) >= limit:
            break
    return out


def _fallback_match_analysis(student_id: str, job_id: str, score_result: dict[str, Any], reason: str) -> dict[str, Any]:
    profile = (db.get_student_profile(student_id) or {}).get("profile") or {}
    job = db.get_job(job_id) or {}
    dims = score_result.get("dimension_scores") or {}
    skills_dim = dims.get("skills") or {}
    overall = round(float(score_result.get("overall_score") or 0.0))
    matched = _name_list(skills_dim.get("matched"), "name", "mention", "skill_id", limit=5)
    missing = _name_list(skills_dim.get("missing"), "name", "mention", "skill_id", limit=5)
    soft = _name_list(profile.get("soft_skills"), "name", "mention", limit=3)
    title = str(job.get("title") or "该岗位").strip()

    strengths = []
    if matched:
        strengths.append(f"已命中岗位关键技能：{'、'.join(matched[:4])}")
    if soft:
        strengths.append(f"画像中具备通用素质：{'、'.join(soft[:3])}")
    if not strengths:
        strengths.append("当前画像与岗位存在一定基础相关性，但可解释证据仍需补充。")

    gaps = [f"建议补齐或强化：{name}" for name in missing[:3]]
    if not gaps:
        gaps = ["当前未识别到明显硬技能缺口，建议继续补充项目证据提升可信度。"]

    next_actions = []
    for name in missing[:3]:
        next_actions.append(f"围绕 {name} 完成一个可展示的小项目，并在简历中写清使用场景和结果。")
    if not next_actions:
        next_actions = ["补充1个与目标岗位相关的项目案例，突出技术栈、个人职责和量化结果。"]

    return {
        "summary": f"{title} 当前综合匹配度约为 {overall} 分，建议结合技能命中与缺口继续评估。",
        "strengths": strengths[:3],
        "gaps": gaps[:3],
        "next_actions": next_actions[:3],
        "risk_hint": "该诊断为规则兜底生成，大模型未参与或调用失败，建议以岗位原文和简历证据复核。",
        "source": "rule_fallback",
        "llm_used": False,
        "fallback_reason": reason,
    }


def _normalize_ai_analysis(data: Any, *, fallback: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict):
        return fallback
    out = {
        "summary": str(data.get("summary") or fallback.get("summary") or "").strip(),
        "strengths": [str(x).strip() for x in (data.get("strengths") or []) if str(x).strip()][:4],
        "gaps": [str(x).strip() for x in (data.get("gaps") or []) if str(x).strip()][:4],
        "next_actions": [str(x).strip() for x in (data.get("next_actions") or []) if str(x).strip()][:6],
        "risk_hint": str(data.get("risk_hint") or fallback.get("risk_hint") or "").strip(),
        "source": "llm",
        "llm_used": True,
        "fallback_reason": "",
    }
    if not out["summary"]:
        out["summary"] = fallback["summary"]
    if not out["strengths"]:
        out["strengths"] = fallback["strengths"]
    if not out["gaps"]:
        out["gaps"] = fallback["gaps"]
    if not out["next_actions"]:
        out["next_actions"] = fallback["next_actions"]
    return out


def build_match_ai_analysis(student_id: str, job_id: str, score_result: dict[str, Any]) -> dict[str, Any] | None:
    fallback = _fallback_match_analysis(student_id, job_id, score_result, "llm_not_called")
    if not llm_client.is_enabled():
        return {**fallback, "fallback_reason": "llm_not_enabled"}
    student = db.get_student(student_id) or {}
    profile = (db.get_student_profile(student_id) or {}).get('profile') or {}
    job = db.get_job(job_id) or {}
    job_profile = (db.get_job_profile(job_id) or {}).get('profile') or {}
    skills_dim = (score_result.get("dimension_scores") or {}).get("skills") or {}
    candidate_top20 = skills_dim.get("llm_candidate_top20") or []
    candidate_names = [str(x.get("name") or "") for x in candidate_top20 if str(x.get("name") or "").strip()]

    payload = {
        'student': {
            'student_id': student_id,
            'name': student.get('name'),
            'hard_skills': [x.get('mention') for x in profile.get('hard_skills') or []][:15],
            'soft_skills': [x.get('name') for x in profile.get('soft_skills') or []][:10],
            'certificates': [x.get('name') for x in profile.get('certificates') or []][:8],
            'experience': profile.get('experience') or {},
            'preferences': profile.get('preferences') or {},
        },
        'job': {
            'job_id': job_id,
            'title': job.get('title'),
            'company_name': job.get('company_name'),
            'job_family': job_profile.get('job_family'),
            'job_family_label': job_family_label(job_profile.get('job_family')),
            'hard_skills': candidate_names[:20] if candidate_names else [x.get('mention') for x in job_profile.get('hard_skills') or []][:15],
            'soft_skills': [x.get('name') for x in job_profile.get('soft_skills') or []][:10],
            'certificates': [x.get('name') for x in job_profile.get('certificates') or []][:8],
        },
        'token_optimization': {
            'candidate_hard_skills_top20': candidate_top20[:20],
            'candidate_used': bool(candidate_top20),
            'original_job_hard_skill_count': len(job_profile.get('hard_skills') or []),
        },
        'score': score_result,
    }
    system = """你是大学生求职匹配分析助手。请根据学生画像、岗位画像和现有评分结果，输出一个 JSON：
{
  "summary": "一句话总结",
  "strengths": ["优势1", "优势2", "优势3"],
  "gaps": ["差距1", "差距2", "差距3"],
  "next_actions": ["行动1", "行动2", "行动3"],
  "risk_hint": "一句风险提醒"
}
要求：
1. 必须与输入数据一致，不得编造不存在的经历。
2. 行动建议要能在 2~8 周内执行。
3. 技能差距分析优先参考 token_optimization.candidate_hard_skills_top20。
4. 所有结论必须锚定到当前具体岗位 job.title，不要写岗位大类空话，不要写“申请者/候选人”泛化措辞。
5. strengths/gaps 里的每一条应尽量包含具体技能名或经历证据词。
6. 只输出 JSON。
"""
    try:
        data = llm_client.chat_json_sync(
            system,
            json.dumps(payload, ensure_ascii=False),
            trace_context="match_analysis.summary",
        )
        return _normalize_ai_analysis(data, fallback=fallback)
    except Exception as exc:
        return {**fallback, "fallback_reason": f"llm_failed:{type(exc).__name__}: {str(exc)[:120]}"}
