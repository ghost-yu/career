from __future__ import annotations

import json
from typing import Any

from app.db import sqlite as db
from app.schemas.report import ActionItem, CareerReport, PhasePlan
from app.services.graph_store import graph_store
from app.services.role_graph import role_graph
from app.services.scoring import score
from app.services.action_planner import build_action_plan_from_gaps
from app.services.kb_bridge import collect_kb_references
from app.services.llm import llm_client
from app.services.mbti import get_mbti_brief, normalize_mbti_type
from app.services.profile_snapshot import build_student_profile_snapshot
from app.utils.labels import enrich_student_profile_labels, job_family_label
from app.utils.ids import gen_id, now_iso


def _build_action_plan_from_gaps(missing: list[dict[str, Any]]) -> list[PhasePlan]:
    # Kept for backward compatibility; actual logic moved to action_planner.py
    return build_action_plan_from_gaps(missing)


def _compact_student_profile_for_ai(profile: dict[str, Any]) -> dict[str, Any]:
    return build_student_profile_snapshot(
        profile,
        hard_limit=30,
        soft_limit=20,
        cert_limit=15,
        detail_limit_per_field=6,
        include_detail_items=True,
        include_education=True,
        notes_limit=360,
        profile_notes_limit=520,
    )


_SKILL_LABEL_FIXUPS = {
    "herbernate": "Hibernate",
    "hibernate": "Hibernate",
    "mybatis": "MyBatis",
    "springboot": "Spring Boot",
    "spring boot": "Spring Boot",
    "apache druid": "Apache Druid",
}


def _normalize_skill_label(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    fixed = _SKILL_LABEL_FIXUPS.get(text.lower())
    return fixed or text


def _normalize_skill_labels(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        name = _normalize_skill_label(raw)
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(name)
    return out


def generate_report(
    student_id: str,
    target_job_ids: list[str],
    planning_context: dict[str, Any] | None = None,
) -> CareerReport:
    if not target_job_ids:
        raise ValueError("target_job_ids is empty")
    planning_context = planning_context or {}

    # For now: pick best match among targets
    scored = []
    for jid in target_job_ids:
        mr = score(student_id, jid, use_cache=True)
        scored.append(mr)
    scored.sort(key=lambda x: x.overall_score, reverse=True)
    best = scored[0]
    best_job_id = best.job_id
    job = db.get_job(best_job_id) or {}
    student_profile_raw = (db.get_student_profile(student_id) or {}).get("profile") or {}
    student_profile = enrich_student_profile_labels(student_profile_raw) or {}
    student_profile_for_ai = _compact_student_profile_for_ai(student_profile)
    mbti_type = normalize_mbti_type(student_profile.get("mbti_type"))
    mbti_brief = get_mbti_brief(mbti_type) if mbti_type else None
    student_snapshot = {
        "mbti_type": mbti_type,
        "mbti_label": (mbti_brief or {}).get("subtitle"),
        "mbti_strengths": (mbti_brief or {}).get("strengths") or [],
        "mbti_challenges": (mbti_brief or {}).get("challenges") or [],
        "mbti_job_family_hints": (mbti_brief or {}).get("job_family_hints") or [],
        "mbti_job_family_hint_labels": [job_family_label(x) for x in ((mbti_brief or {}).get("job_family_hints") or []) if x],
    }

    # Job-level graph paths
    vertical = graph_store.get_vertical_path(best_job_id)
    switches = graph_store.get_switch_paths(best_job_id, top_k=5)

    # Role-level paths (more stable, recommended for career planning)
    role_id = None
    role_vertical = None
    role_switches = None
    try:
        role_ids = db.list_roles_for_job(best_job_id)
        if role_ids:
            role_id = role_ids[0]
            role_vertical = role_graph.get_vertical_path(role_id)
            role_switches = role_graph.get_switch_paths(role_id, top_k=5, max_hops=2)
    except Exception:
        pass

    missing = best.dimension_scores.get("skills", {}).get("missing", [])
    action_plan = _build_action_plan_from_gaps(missing)

    report_id = gen_id("RPT", 10)
    planning_role_title = str(planning_context.get("role_title") or "").strip()
    if planning_role_title:
        summary = (
            f"基于你的简历画像与目标方向《{planning_role_title}》岗位簇分析，你在该方向候选岗位中的最高匹配分为 {best.overall_score} 分。"
            "报告将基于岗位簇市场方向关键词给出差距分析、发展路径与可执行行动计划。"
        )
    else:
        summary = (
            f"基于你的简历画像与岗位画像匹配结果，你与目标岗位《{job.get('title')}》综合匹配度为 {best.overall_score} 分。"
            "报告将给出差距分析、发展路径与可执行行动计划。"
        )
    if student_snapshot.get("mbti_type"):
        summary += f" 当前人格倾向为 {student_snapshot.get('mbti_type')}（{student_snapshot.get('mbti_label') or 'MBTI'}），建议结合该倾向安排学习与求职节奏。"

    top_strengths = _normalize_skill_labels(
        [m.get("name") for m in best.dimension_scores.get("skills", {}).get("matched", [])[:5] if isinstance(m, dict)]
    )
    top_gaps = _normalize_skill_labels([m.get("name") for m in missing[:8] if isinstance(m, dict)])

    fit_analysis = {
        "overall_score": best.overall_score,
        "dimension_scores": best.dimension_scores,
        "top_strengths": top_strengths,
        "top_gaps": top_gaps,
        "student_mbti": {
            "type": student_snapshot.get("mbti_type"),
            "label": student_snapshot.get("mbti_label"),
            "strengths": student_snapshot.get("mbti_strengths"),
            "challenges": student_snapshot.get("mbti_challenges"),
            "job_family_hints": student_snapshot.get("mbti_job_family_hints"),
            "job_family_hint_labels": student_snapshot.get("mbti_job_family_hint_labels"),
        },
    }

    career_path = {
        "target_job": {"job_id": best_job_id, "title": job.get("title"), "company": job.get("company_name")},
        "vertical_path": vertical,
        "switch_paths": switches,
        "role_id": role_id,
        "role_vertical_path": role_vertical,
        "role_switch_paths": role_switches,
        "planning_context": planning_context,
    }

    evaluation = {
        "cycle": "每4周",
        "kpis": ["核心缺口技能完成学习与Demo产出", "新增项目/实习经历与简历证据补全", "目标岗位模拟面试通过率提升"],
        "adjustment": "根据新获得的实习/项目反馈，调整目标岗位与路径。",
    }

    kb_queries: list[str] = []
    kb_queries.extend([str(x) for x in (planning_context.get("market_keywords") or [])[:6] if str(x).strip()])
    kb_queries.append(str(job.get("title") or ""))
    kb_queries.extend([str(x) for x in (fit_analysis.get("top_gaps") or [])[:8]])
    knowledge_references = collect_kb_references(
        kb_queries,
        per_query=2,
        max_items=10,
    )

    md = _to_markdown(
        summary,
        fit_analysis,
        career_path,
        action_plan,
        evaluation,
        knowledge_references,
        student_snapshot=student_snapshot,
        planning_context=planning_context,
    )
    summary, md = _maybe_ai_enhance_report(
        summary,
        fit_analysis,
        career_path,
        action_plan,
        evaluation,
        md,
        student_profile_for_ai=student_profile_for_ai,
        student_snapshot=student_snapshot,
        target_job={
            "job_id": best_job_id,
            "title": str(job.get("title") or ""),
            "company": str(job.get("company_name") or ""),
            "location": str(job.get("location") or ""),
            "description": str(job.get("description") or "")[:2600],
        },
        planning_context=planning_context,
    )

    report = CareerReport(
        report_id=report_id,
        student_id=student_id,
        target_jobs=[{"job_id": r.job_id, "score": r.overall_score} for r in scored],
        summary=summary,
        fit_analysis=fit_analysis,
        student_snapshot=student_snapshot,
        career_path=career_path,
        action_plan=action_plan,
        evaluation=evaluation,
        knowledge_references=knowledge_references,
        markdown=md,
    )

    db.insert_report(
        {
            "report_id": report_id,
            "student_id": student_id,
            "content_json": json.dumps(report.model_dump(), ensure_ascii=False),
            "content_md": md,
            "version": 1,
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }
    )
    return report


def _maybe_ai_enhance_report(
    summary: str,
    fit: dict[str, Any],
    path: dict[str, Any],
    plan: list[PhasePlan],
    evaluation: dict[str, Any],
    markdown: str,
    *,
    student_profile_for_ai: dict[str, Any] | None = None,
    student_snapshot: dict[str, Any] | None = None,
    target_job: dict[str, Any] | None = None,
    planning_context: dict[str, Any] | None = None,
) -> tuple[str, str]:
    if not llm_client.is_enabled():
        return summary, markdown
    system = """你是大学生职业规划报告助手。请基于已有结构化结果，做轻量增强：
1. 不改变原有事实与评分。
2. summary 更自然、更像给学生看的建议。
3. markdown 保持 Markdown 格式，保留原有五个一级章节。
4. 不要虚构新的项目、实习或证书。
5. 只能使用输入中的学生画像、岗位信息、匹配结果。
6. 职业路径规划优先体现“岗位簇市场方向关键词”和趋势，不要把建议绑定在单一企业上。
请只输出 JSON：{"summary": "...", "markdown": "..."}
"""
    payload = {
        'summary': summary,
        'fit_analysis': fit,
        'career_path': path,
        'action_plan': [x.model_dump() for x in plan],
        'evaluation': evaluation,
        'markdown': markdown,
        'student_profile': student_profile_for_ai or {},
        'student_snapshot': student_snapshot or {},
        'target_job': target_job or {},
        'planning_context': planning_context or {},
    }
    try:
        data = llm_client.chat_json_sync(system, json.dumps(payload, ensure_ascii=False))
        new_summary = str(data.get('summary') or summary).strip()
        new_md = str(data.get('markdown') or markdown).strip()
        if not _is_complete_report_markdown(new_md, baseline=markdown):
            return new_summary or summary, markdown
        return new_summary or summary, new_md or markdown
    except Exception:
        return summary, markdown


def _is_complete_report_markdown(markdown: str, baseline: str = "") -> bool:
    text = str(markdown or "").strip()
    if not text:
        return False

    required_headings = [
        "## 1.",
        "## 2.",
        "## 3.",
        "## 4.",
        "## 5.",
        "## 4. 行动计划",
        "## 5. 评估与动态调整",
    ]
    if any(h not in text for h in required_headings):
        return False

    section4_pos = text.find("## 4. 行动计划")
    section5_pos = text.find("## 5. 评估与动态调整")
    if section4_pos < 0 or section5_pos <= section4_pos:
        return False

    tail = text[section5_pos:]
    if "\n-" not in tail:
        return False

    if baseline and len(text) < int(len(str(baseline)) * 0.85):
        return False

    if text.endswith(("：", ":", "；", ";", "，", ",", "（", "(")):
        return False

    return True


def _to_markdown(
    summary: str,
    fit: dict[str, Any],
    path: dict[str, Any],
    plan: list[PhasePlan],
    eval_: dict[str, Any],
    knowledge_references: list[dict[str, Any]] | None = None,
    student_snapshot: dict[str, Any] | None = None,
    planning_context: dict[str, Any] | None = None,
) -> str:
    student_snapshot = student_snapshot or {}
    planning_context = planning_context or {}
    lines = []
    lines.append(f"# 职业生涯发展报告\n")
    lines.append(f"## 1. 总览\n{summary}\n")
    if student_snapshot.get("mbti_type"):
        lines.append(f"- MBTI：**{student_snapshot.get('mbti_type')}**（{student_snapshot.get('mbti_label') or '人格倾向'}）\n")
        strengths = student_snapshot.get("mbti_strengths") or []
        if strengths:
            lines.append(f"- MBTI优势提示：{'；'.join([str(x) for x in strengths[:3]])}\n")
        hints = student_snapshot.get("mbti_job_family_hint_labels") or []
        if hints:
            lines.append(f"- MBTI建议方向：{'、'.join([str(x) for x in hints[:4]])}\n")
    lines.append("## 2. 人岗匹配分析\n")
    lines.append(f"- 综合匹配分：**{fit.get('overall_score')}**\n")
    ds = fit.get("dimension_scores") or {}
    for k, v in ds.items():
        lines.append(f"- {k}：{v.get('score')}\n")
    lines.append("\n### 2.1 优势\n")
    for s in (fit.get("top_strengths") or []):
        lines.append(f"- {s}\n")
    lines.append("\n### 2.2 差距（Top）\n")
    for g in (fit.get("top_gaps") or []):
        lines.append(f"- {g}\n")

    lines.append("\n## 3. 职业路径规划\n")
    market_keywords = [str(x).strip() for x in (planning_context.get("market_keywords") or []) if str(x).strip()]
    trend_points = [str(x).strip() for x in (planning_context.get("trend_points") or []) if str(x).strip()]
    if market_keywords or trend_points:
        lines.append("### 3.0 岗位簇市场方向\n")
        if market_keywords:
            lines.append(f"- 方向关键词：{'、'.join(market_keywords[:12])}\n")
        for point in trend_points[:4]:
            lines.append(f"- {point}\n")
        lines.append("\n")

    if path.get("role_id") and path.get("role_vertical_path"):
        lines.append("### 3.1 角色级垂直发展路径（推荐）\n")
        for n in path.get("role_vertical_path") or []:
            lines.append(f"- {n.get('title','')} ({n.get('level_label')})\n")
        lines.append("\n### 3.2 角色级换岗路径（推荐）\n")
        for p in path.get("role_switch_paths") or []:
            if len(p) >= 2:
                seq = " → ".join([x.get("title") or "" for x in p])
                lines.append(f"- {seq}\n")

        lines.append("\n---\n")

    lines.append("### 3.3 岗位级垂直发展路径（posting）\n")
    for n in path.get("vertical_path") or []:
        lines.append(f"- {n.get('title','')} ({n.get('job_id')})\n")
    lines.append("\n### 3.4 岗位级换岗路径（posting）\n")
    for p in path.get("switch_paths") or []:
        if len(p) >= 2:
            lines.append(f"- {p[0].get('title')} → {p[1].get('title')}\n")

    lines.append("\n## 4. 行动计划\n")
    for phase in plan:
        lines.append(f"### {phase.phase}（{phase.duration_weeks}周）\n")
        if not phase.actions:
            lines.append("- 暂无阶段动作，请在下一轮评估后补充。\n")
            continue
        for a in phase.actions:
            lines.append(f"- **{a.title}**：{a.description}\n")
            if a.metrics:
                lines.append(f"  - 指标：{'；'.join(a.metrics)}\n")
            if a.resources:
                lines.append(f"  - 资源：{'；'.join(a.resources)}\n")
            if a.deadline:
                lines.append(f"  - 截止：{a.deadline}\n")

    lines.append("\n## 5. 评估与动态调整\n")
    lines.append(f"- 周期：{eval_.get('cycle')}\n")
    lines.append("- 指标：\n")
    for k in eval_.get("kpis") or []:
        lines.append(f"  - {k}\n")
    lines.append(f"- 调整机制：{eval_.get('adjustment')}\n")
    return "".join(lines)
