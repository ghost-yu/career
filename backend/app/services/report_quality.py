from __future__ import annotations

import re
from typing import Any

from app.services.llm import llm_client


_REQUIRED_HEADINGS = [
    "## 1. 总览",
    "## 2. 人岗匹配分析",
    "## 3. 职业路径规划",
    "## 4. 行动计划",
    "## 5. 评估与动态调整",
]


def check_markdown(markdown: str) -> list[dict[str, Any]]:
    """Return a list of issues.

    This is a rule-based checker so the result is deterministic.
    """

    md = markdown or ""
    issues: list[dict[str, Any]] = []

    # 1) headings
    for h in _REQUIRED_HEADINGS:
        if h not in md:
            issues.append({"type": "missing_heading", "severity": "high", "message": f"缺少章节标题：{h}"})

    # 2) gaps count
    gap_lines = [ln for ln in md.splitlines() if ln.strip().startswith("-") and ("差距" in md or "差距" in ln)]
    # Not perfect; we also check for '差距（Top）' section block
    if "### 2.2 差距" in md:
        block = md.split("### 2.2 差距")[1]
        block = block.split("## ")[0] if "## " in block else block
        gaps = [ln for ln in block.splitlines() if ln.strip().startswith("-")]
        if len(gaps) < 3:
            issues.append({"type": "few_gaps", "severity": "medium", "message": "差距项过少（建议 >= 3 条）"})

    # 3) action plan items
    if "## 4. 行动计划" in md:
        plan = md.split("## 4. 行动计划")[1]
        plan = re.split(r"(?m)^##\s+", plan, maxsplit=1)[0]
        actions = [ln for ln in plan.splitlines() if ln.strip().startswith("- **")]
        if len(actions) < 4:
            issues.append({"type": "few_actions", "severity": "high", "message": "行动计划条目过少（建议 >= 4 条）"})

    # 4) evidence hint
    if "证据" not in md and "evidence" not in md.lower():
        issues.append({"type": "no_evidence_hint", "severity": "low", "message": "建议在优势/差距中补充证据句或简历定位信息（提升可解释性）"})

    return issues


async def polish_markdown(markdown: str, style: str = "professional") -> str:
    """Polish markdown using LLM (optional).

    - In mock mode, return the original markdown.
    - In openai mode, return revised markdown.
    """

    if not llm_client.is_enabled():
        return markdown

    system = """你是职业规划报告写作助手。请对用户提供的 Markdown 报告进行润色：
- 保持原有结构与标题不变
- 语言更专业、表达更清晰
- 避免夸张承诺，保持可操作性
- 不要新增与原内容无关的虚构经历

只输出润色后的 Markdown，不要输出其他解释。"""

    user = markdown
    resp = await llm_client.chat(system, user)
    return (resp.text or markdown).strip()
