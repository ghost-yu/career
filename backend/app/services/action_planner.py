from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.schemas.report import ActionItem, PhasePlan
from app.services.kb import search_kb


def _load_project_templates() -> list[dict[str, Any]]:
    p = Path(settings.kb_dir) / "templates" / "project_templates.json"
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8", errors="ignore"))
        return list(data.get("templates") or [])
    except Exception:
        return []


def _resources_for_skill(skill_name: str, top_k: int = 2) -> list[str]:
    # 1) KB docs
    docs = search_kb(skill_name, top_k=top_k)
    res = []
    for d in docs:
        title = d.get("title")
        if title:
            res.append(f"知识库：{title}")

    # 2) project templates
    tmpls = _load_project_templates()
    for t in tmpls:
        skills = [str(s).lower() for s in (t.get("skills") or [])]
        if skill_name.lower() in skills or any(skill_name.lower() in s for s in skills):
            res.append(f"项目模板：{t.get('title')}")

    # 3) fallback
    if not res:
        res = [f"{skill_name} 官方文档/教程", "入门课程（MOOC/官方教程）", "开源项目阅读与复刻"]

    # de-dup keep order
    seen = set()
    out = []
    for r in res:
        if r in seen:
            continue
        seen.add(r)
        out.append(r)
    return out[:6]


def build_action_plan_from_gaps(missing: list[dict[str, Any]]) -> list[PhasePlan]:
    """Convert top missing skills into a 3-phase plan.

    This is intentionally deterministic; LLM can be added later for richer text.
    """

    top = []
    seen_skills = set()
    for item in missing or []:
        key = str(item.get("name") or item.get("skill_id") or "能力项").strip().casefold()
        if key in seen_skills:
            continue
        seen_skills.add(key)
        top.append(item)
        if len(top) >= 9:
            break
    short_actions: list[ActionItem] = []
    mid_actions: list[ActionItem] = []
    final_actions: list[ActionItem] = []
    skill_names: list[str] = []

    for i, m in enumerate(top):
        name = m.get("name") or m.get("skill_id") or "能力项"
        skill_names.append(str(name))
        resources = _resources_for_skill(str(name), top_k=2)

        if i < 3:
            short_actions.append(
                ActionItem(
                    title=f"补齐核心技能：{name}",
                    description=(
                        f"围绕 {name} 完成系统学习 + 小项目落地，并在简历中形成可量化成果。"
                        "优先补齐岗位必须项（must）。"
                    ),
                    metrics=[
                        f"完成 {name} 学习笔记/总结 1 份",
                        "完成可展示 Demo 1 个（含 README/部署）",
                        "在简历技能/项目中补充证据句（STAR + 指标）",
                    ],
                    resources=resources,
                    deadline="4周内",
                )
            )
        elif i < 6:
            mid_actions.append(
                ActionItem(
                    title=f"进阶提升：{name}",
                    description=f"将 {name} 应用于完整项目或实习场景，提升熟练度与工程化经验。",
                    metrics=[
                        "完成中等规模项目 1 个（含部署/文档）",
                        "沉淀技术复盘 1 篇（问题→方案→效果）",
                        "补充面试题整理（与项目强相关）",
                    ],
                    resources=resources,
                    deadline="8-12周",
                )
            )
        else:
            final_actions.append(
                ActionItem(
                    title=f"求职冲刺：{name}",
                    description=f"围绕 {name} 打磨作品集、面试表达与投递策略，形成闭环成果。",
                    metrics=[
                        "完成 1 份可展示的项目作品集页面/文档",
                        "完成 2 轮岗位模拟面试并复盘改进",
                        "形成投递清单并跟踪反馈，完成至少 10 次有效投递",
                    ],
                    resources=resources,
                    deadline="13-24周",
                )
            )

    if not skill_names:
        skill_names = ["岗位通用能力"]

    if not short_actions:
        seed = skill_names[0]
        short_actions.append(
            ActionItem(
                title=f"补齐核心技能：{seed}",
                description="先完成基础能力补齐，并输出可验证成果。",
                metrics=[
                    "完成学习计划并按周执行",
                    "完成至少 1 个可展示的小项目",
                ],
                resources=_resources_for_skill(seed, top_k=2),
                deadline="4周内",
            )
        )

    if not mid_actions:
        seed = skill_names[1] if len(skill_names) > 1 else skill_names[0]
        mid_actions.append(
            ActionItem(
                title=f"项目强化：{seed}",
                description="将所学能力整合进完整项目，提升交付与工程化能力。",
                metrics=[
                    "完成中等规模项目并沉淀文档",
                    "补齐项目中的量化结果与复盘",
                ],
                resources=_resources_for_skill(seed, top_k=2),
                deadline="8-12周",
            )
        )

    if not final_actions:
        seed = skill_names[-1]
        final_actions.append(
            ActionItem(
                title=f"求职冲刺：{seed}",
                description="围绕目标岗位进行作品、面试、投递三线冲刺。",
                metrics=[
                    "完成简历与作品集定稿",
                    "完成模拟面试并形成改进闭环",
                    "形成并执行阶段性投递计划",
                ],
                resources=_resources_for_skill(seed, top_k=2),
                deadline="13-24周",
            )
        )

    return [
        PhasePlan(phase="short", duration_weeks=4, actions=short_actions),
        PhasePlan(phase="mid", duration_weeks=12, actions=mid_actions),
        PhasePlan(phase="final", duration_weeks=24, actions=final_actions),
    ]
