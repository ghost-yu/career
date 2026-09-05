from __future__ import annotations

import io
import json
from typing import Any, Literal

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.db import sqlite as db


DIMENSION_LABELS = {
    "basic": "基础要求",
    "skills": "职业技能",
    "literacy": "职业素养",
    "qualities": "职业素养",
    "potential": "发展潜力",
    "stability": "岗位稳定性",
}


def export_report(report_id: str, fmt: Literal["pdf", "docx"]) -> tuple[bytes, str]:
    row = db.get_report(report_id)
    if not row:
        raise ValueError("Report not found")

    markdown = row.get("content_md") or ""
    try:
        payload = json.loads(row.get("content_json") or "{}")
    except Exception:
        payload = {}

    report = _normalize_report_payload(report_id=report_id, row=row, payload=payload, markdown=markdown)

    if fmt == "pdf":
        return _export_pdf(report), "职业规划报告-打印版.pdf"
    if fmt == "docx":
        return _export_docx(report), "职业规划报告-可编辑版.docx"
    raise ValueError("Unsupported format")


# ---------------------------------------------------------------------------
# Structured payload helpers
# ---------------------------------------------------------------------------

def _normalize_report_payload(report_id: str, row: dict[str, Any], payload: dict[str, Any], markdown: str) -> dict[str, Any]:
    fit = payload.get("fit_analysis") or {}
    path = payload.get("career_path") or {}
    action_plan = payload.get("action_plan") or []
    evaluation = payload.get("evaluation") or {}
    target_job = path.get("target_job") or {}

    dimension_rows: list[dict[str, Any]] = []
    for key, value in (fit.get("dimension_scores") or {}).items():
        if isinstance(value, dict):
            score = value.get("score")
        else:
            score = value
        dimension_rows.append(
            {
                "key": key,
                "label": DIMENSION_LABELS.get(str(key), str(key)),
                "score": _safe_number(score),
            }
        )

    vertical_titles = []
    for node in (path.get("role_vertical_path") or path.get("vertical_path") or []):
        title = str(node.get("title") or node.get("title_rep") or node.get("base_role") or "").strip()
        if title:
            vertical_titles.append(title)

    switch_paths: list[str] = []
    role_switches = path.get("role_switch_paths") or []
    if role_switches:
        for seq in role_switches:
            titles = [str(item.get("title") or item.get("title_rep") or item.get("base_role") or "").strip() for item in seq or []]
            titles = [t for t in titles if t]
            if len(titles) >= 2:
                switch_paths.append(" → ".join(titles))
    else:
        for seq in path.get("switch_paths") or []:
            titles = [str(item.get("title") or item.get("title_rep") or item.get("base_role") or "").strip() for item in seq or []]
            titles = [t for t in titles if t]
            if len(titles) >= 2:
                switch_paths.append(" → ".join(titles))

    phases: list[dict[str, Any]] = []
    for phase in action_plan:
        phases.append(
            {
                "phase": {"short": "近期行动", "mid": "中期提升", "final": "求职冲刺"}.get(str(phase.get("phase")), str(phase.get("phase") or "阶段规划")),
                "duration_weeks": int(phase.get("duration_weeks") or 0),
                "actions": [
                    {
                        "title": str(action.get("title") or "行动项"),
                        "description": str(action.get("description") or ""),
                        "metrics": [str(x) for x in (action.get("metrics") or []) if str(x).strip()],
                        "resources": [str(x) for x in (action.get("resources") or []) if str(x).strip()],
                        "deadline": str(action.get("deadline") or "").strip(),
                    }
                    for action in (phase.get("actions") or [])
                ],
            }
        )

    student_id = row.get("student_id") or payload.get("student_id") or ""
    student_row = db.get_student(student_id) if student_id else None
    student_name = str((student_row or {}).get("name") or payload.get("student_name") or "").strip()

    return {
        "report_id": report_id,
        "student_id": student_id,
        "student_name": student_name,
        "version": int(row.get("version") or payload.get("version") or 1),
        "created_at": str(row.get("created_at") or ""),
        "updated_at": str(row.get("updated_at") or ""),
        "summary": str(payload.get("summary") or "").strip() or _summary_from_markdown(markdown),
        "overall_score": _safe_number(fit.get("overall_score")),
        "dimension_rows": dimension_rows,
        "strengths": [str(x) for x in (fit.get("top_strengths") or []) if str(x).strip()],
        "gaps": [str(x) for x in (fit.get("top_gaps") or []) if str(x).strip()],
        "target_job_title": str(target_job.get("title") or payload.get("target_role_title") or path.get("target_role") or "").strip(),
        "target_company": str(target_job.get("company") or "").strip(),
        "vertical_titles": vertical_titles,
        "switch_paths": switch_paths,
        "action_plan": phases,
        "evaluation": {
            "cycle": str(evaluation.get("cycle") or "").strip(),
            "kpis": [str(x) for x in (evaluation.get("kpis") or []) if str(x).strip()],
            "adjustment": str(evaluation.get("adjustment") or "").strip(),
        },
        "markdown": markdown,
    }


def _safe_number(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return round(float(value), 2)
    except Exception:
        return None


def _summary_from_markdown(markdown: str) -> str:
    lines = [line.strip() for line in (markdown or "").splitlines() if line.strip()]
    for idx, line in enumerate(lines):
        if line.startswith("## 1.") and idx + 1 < len(lines):
            return lines[idx + 1]
    return lines[0] if lines else "职业规划报告"


# ---------------------------------------------------------------------------
# PDF export
# ---------------------------------------------------------------------------

def _register_pdf_font() -> str:
    try:
        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
        return "STSong-Light"
    except Exception:
        return "Helvetica"


def _pdf_styles(font_name: str) -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    styles = {
        "title": ParagraphStyle(
            "CareerTitle",
            parent=base["Title"],
            fontName=font_name,
            fontSize=22,
            leading=28,
            textColor=colors.HexColor("#12325c"),
            alignment=1,
            spaceAfter=14,
        ),
        "kicker": ParagraphStyle(
            "CareerKicker",
            parent=base["BodyText"],
            fontName=font_name,
            fontSize=9,
            leading=13,
            alignment=1,
            textColor=colors.HexColor("#4a7bb7"),
            spaceAfter=8,
        ),
        "section": ParagraphStyle(
            "CareerSection",
            parent=base["Heading2"],
            fontName=font_name,
            fontSize=14,
            leading=18,
            textColor=colors.HexColor("#0e2b52"),
            spaceBefore=12,
            spaceAfter=8,
        ),
        "sub": ParagraphStyle(
            "CareerSub",
            parent=base["Heading3"],
            fontName=font_name,
            fontSize=11,
            leading=14,
            textColor=colors.HexColor("#35537d"),
            spaceBefore=8,
            spaceAfter=6,
        ),
        "body": ParagraphStyle(
            "CareerBody",
            parent=base["BodyText"],
            fontName=font_name,
            fontSize=10.5,
            leading=16,
            textColor=colors.HexColor("#24354f"),
            spaceAfter=6,
        ),
        "bullet": ParagraphStyle(
            "CareerBullet",
            parent=base["BodyText"],
            fontName=font_name,
            fontSize=10,
            leading=15,
            leftIndent=14,
            bulletIndent=0,
            textColor=colors.HexColor("#24354f"),
            spaceAfter=2,
        ),
        "small": ParagraphStyle(
            "CareerSmall",
            parent=base["BodyText"],
            fontName=font_name,
            fontSize=9,
            leading=12,
            textColor=colors.HexColor("#5e6d84"),
            spaceAfter=4,
        ),
    }
    return styles


def _build_pdf_info_table(report: dict[str, Any], font_name: str):
    rows = [
        ["学生档案", report.get("student_name") or "当前学生", "目标方向", report.get("target_job_title") or "待选定"],
        ["报告版本", f"第 {report.get('version') or 1} 版", "更新日期", (report.get("updated_at") or report.get("created_at") or "").replace("T", " ")[:19] or "-"],
    ]
    table = Table(rows, colWidths=[22 * mm, 60 * mm, 22 * mm, 70 * mm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f3f7fd")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d8e3f3")),
                ("FONTNAME", (0, 0), (-1, -1), font_name),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#24354f")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return table


def _build_pdf_dimension_table(report: dict[str, Any], font_name: str):
    rows = [["维度", "得分"]]
    for row in report.get("dimension_rows") or []:
        score = row.get("score")
        rows.append([str(row.get("label") or row.get("key") or "维度"), "-" if score is None else str(score)])
    if len(rows) == 1:
        rows.append(["暂无结构化评分", "-"])
    table = Table(rows, colWidths=[90 * mm, 30 * mm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#153a6c")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, -1), font_name),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d6e1ef")),
                ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#f8fbff")),
                ("ALIGN", (1, 1), (1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return table


def _build_pdf_bullets(items: list[str], styles: dict[str, ParagraphStyle], empty_text: str) -> ListFlowable | Paragraph:
    if not items:
        return Paragraph(empty_text, styles["small"])
    return ListFlowable(
        [ListItem(Paragraph(_escape_pdf_text(item), styles["bullet"])) for item in items],
        bulletType="bullet",
        start="circle",
        bulletFontName=styles["bullet"].fontName,
    )


def _escape_pdf_text(text: str) -> str:
    return (
        str(text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", "<br/>")
    )


def _export_pdf(report: dict[str, Any]) -> bytes:
    buf = io.BytesIO()
    font_name = _register_pdf_font()
    styles = _pdf_styles(font_name)
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=16 * mm,
        title="职业规划报告",
    )

    story: list[Any] = []
    story.append(Paragraph("明杉科技 · 一人一策职业规划报告", styles["kicker"]))
    story.append(Paragraph("大学生职业生涯发展报告", styles["title"]))
    story.append(_build_pdf_info_table(report, font_name))
    story.append(Spacer(1, 10))

    story.append(Paragraph("一、报告总览", styles["section"]))
    story.append(Paragraph(_escape_pdf_text(report.get("summary") or "暂无摘要。"), styles["body"]))
    overall_score = report.get("overall_score")
    if overall_score is not None:
        story.append(Paragraph(f"综合匹配分：<b>{overall_score}</b>", styles["body"]))

    story.append(Paragraph("二、人岗匹配分析", styles["section"]))
    story.append(_build_pdf_dimension_table(report, font_name))
    story.append(Spacer(1, 8))
    story.append(Paragraph("优势能力", styles["sub"]))
    story.append(_build_pdf_bullets(report.get("strengths") or [], styles, "暂无结构化优势标签。"))
    story.append(Spacer(1, 6))
    story.append(Paragraph("关键差距", styles["sub"]))
    story.append(_build_pdf_bullets(report.get("gaps") or [], styles, "暂无结构化差距标签。"))

    story.append(Paragraph("三、职业路径规划", styles["section"]))
    story.append(Paragraph("垂直发展路径", styles["sub"]))
    story.append(_build_pdf_bullets(report.get("vertical_titles") or [], styles, "暂无垂直发展路径。"))
    story.append(Spacer(1, 6))
    story.append(Paragraph("转岗路径建议", styles["sub"]))
    story.append(_build_pdf_bullets(report.get("switch_paths") or [], styles, "暂无转岗路径建议。"))

    story.append(Paragraph("四、行动计划", styles["section"]))
    action_plan = report.get("action_plan") or []
    if not action_plan:
        story.append(Paragraph("暂无行动计划。", styles["small"]))
    else:
        for phase in action_plan:
            phase_title = f"{phase.get('phase') or '阶段规划'}"
            duration = phase.get("duration_weeks")
            if duration:
                phase_title += f"（{duration}周）"
            story.append(Paragraph(phase_title, styles["sub"]))
            action_items = phase.get("actions") or []
            if not action_items:
                story.append(Paragraph("暂无阶段行动项。", styles["small"]))
                continue
            rows = [["行动项", "说明", "指标 / 资源"]]
            for action in action_items:
                metrics = "；".join(action.get("metrics") or [])
                resources = "；".join(action.get("resources") or [])
                mix = "\n".join([part for part in [metrics, resources] if part]) or "-"
                rows.append([
                    str(action.get("title") or "行动项"),
                    str(action.get("description") or ""),
                    mix,
                ])
            action_table = Table(rows, colWidths=[34 * mm, 74 * mm, 44 * mm])
            action_table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#ebf2fb")),
                        ("FONTNAME", (0, 0), (-1, -1), font_name),
                        ("FONTSIZE", (0, 0), (-1, -1), 8.8),
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d6e1ef")),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#24354f")),
                        ("LEADING", (0, 0), (-1, -1), 12),
                        ("LEFTPADDING", (0, 0), (-1, -1), 5),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                        ("TOPPADDING", (0, 0), (-1, -1), 5),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ]
                )
            )
            story.append(action_table)
            story.append(Spacer(1, 6))

    story.append(Paragraph("五、评估与动态调整", styles["section"]))
    evaluation = report.get("evaluation") or {}
    if evaluation.get("cycle"):
        story.append(Paragraph(f"评估周期：{_escape_pdf_text(evaluation.get('cycle') or '')}", styles["body"]))
    story.append(Paragraph("评估指标", styles["sub"]))
    story.append(_build_pdf_bullets(evaluation.get("kpis") or [], styles, "暂无评估指标。"))
    if evaluation.get("adjustment"):
        story.append(Spacer(1, 6))
        story.append(Paragraph(f"动态调整：{_escape_pdf_text(evaluation.get('adjustment') or '')}", styles["body"]))

    doc.build(story)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# DOCX export
# ---------------------------------------------------------------------------

def _set_doc_default_font(document: Document, font_name: str = "Microsoft YaHei") -> None:
    normal_style = document.styles["Normal"]
    normal_style.font.name = font_name
    normal_style.font.size = Pt(10.5)
    normal_style._element.rPr.rFonts.set(qn("w:eastAsia"), font_name)


def _shade_cell(cell, fill: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), fill)
    tc_pr.append(shd)


def _set_table_font(table, font_name: str = "Microsoft YaHei", size: float = 9.5) -> None:
    for row in table.rows:
        for cell in row.cells:
            for paragraph in cell.paragraphs:
                for run in paragraph.runs:
                    run.font.name = font_name
                    run._element.rPr.rFonts.set(qn("w:eastAsia"), font_name)
                    run.font.size = Pt(size)


def _doc_add_list(document: Document, items: list[str], empty_text: str) -> None:
    if not items:
        document.add_paragraph(empty_text)
        return
    for item in items:
        document.add_paragraph(str(item), style="List Bullet")


def _export_docx(report: dict[str, Any]) -> bytes:
    document = Document()
    _set_doc_default_font(document)

    section = document.sections[0]
    section.top_margin = Inches(0.65)
    section.bottom_margin = Inches(0.65)
    section.left_margin = Inches(0.7)
    section.right_margin = Inches(0.7)

    title = document.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run("大学生职业生涯发展报告")
    run.bold = True
    run.font.size = Pt(22)
    run.font.name = "Microsoft YaHei"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")

    kicker = document.add_paragraph()
    kicker.alignment = WD_ALIGN_PARAGRAPH.CENTER
    kick_run = kicker.add_run("明杉科技 · 一人一策 · 人岗匹配 · 职业路径")
    kick_run.italic = True
    kick_run.font.size = Pt(10)
    kick_run.font.name = "Microsoft YaHei"
    kick_run._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")

    info_table = document.add_table(rows=2, cols=4)
    info_rows = [
        ["学生档案", report.get("student_name") or "当前学生", "目标方向", report.get("target_job_title") or "待选定"],
        ["报告版本", f"第 {report.get('version') or 1} 版", "更新日期", (report.get("updated_at") or report.get("created_at") or "").replace("T", " ")[:19] or "-"],
    ]
    for row_idx, row_data in enumerate(info_rows):
        row = info_table.rows[row_idx]
        for col_idx, value in enumerate(row_data):
            cell = row.cells[col_idx]
            cell.text = str(value)
            if col_idx in {0, 2}:
                _shade_cell(cell, "EAF2FD")
    _set_table_font(info_table)

    document.add_heading("一、报告总览", level=1)
    document.add_paragraph(report.get("summary") or "暂无摘要。")
    if report.get("overall_score") is not None:
        paragraph = document.add_paragraph()
        paragraph.add_run("综合匹配分：").bold = True
        paragraph.add_run(str(report.get("overall_score")))

    document.add_heading("二、人岗匹配分析", level=1)
    score_table = document.add_table(rows=1, cols=2)
    score_table.rows[0].cells[0].text = "能力维度"
    score_table.rows[0].cells[1].text = "得分"
    for cell in score_table.rows[0].cells:
        _shade_cell(cell, "153A6C")
        for p in cell.paragraphs:
            for r in p.runs:
                r.font.color.rgb = None
    for row in report.get("dimension_rows") or []:
        cells = score_table.add_row().cells
        cells[0].text = str(row.get("label") or row.get("key") or "维度")
        cells[1].text = "-" if row.get("score") is None else str(row.get("score"))
    if len(score_table.rows) == 1:
        cells = score_table.add_row().cells
        cells[0].text = "暂无结构化评分"
        cells[1].text = "-"
    _set_table_font(score_table)

    document.add_heading("优势能力", level=2)
    _doc_add_list(document, report.get("strengths") or [], "暂无结构化优势标签。")

    document.add_heading("关键差距", level=2)
    _doc_add_list(document, report.get("gaps") or [], "暂无结构化差距标签。")

    document.add_heading("三、职业路径规划", level=1)
    document.add_heading("垂直发展路径", level=2)
    _doc_add_list(document, report.get("vertical_titles") or [], "暂无垂直发展路径。")
    document.add_heading("转岗路径建议", level=2)
    _doc_add_list(document, report.get("switch_paths") or [], "暂无转岗路径建议。")

    document.add_heading("四、行动计划", level=1)
    action_plan = report.get("action_plan") or []
    if not action_plan:
        document.add_paragraph("暂无行动计划。")
    for phase in action_plan:
        phase_title = f"{phase.get('phase') or '阶段规划'}"
        duration = phase.get("duration_weeks")
        if duration:
            phase_title += f"（{duration}周）"
        document.add_heading(phase_title, level=2)
        for action in phase.get("actions") or []:
            paragraph = document.add_paragraph(style="List Bullet")
            head = paragraph.add_run(f"{action.get('title') or '行动项'}：")
            head.bold = True
            paragraph.add_run(str(action.get("description") or ""))
            if action.get("metrics"):
                document.add_paragraph(f"指标：{'；'.join(action.get('metrics') or [])}", style="List Continue")
            if action.get("resources"):
                document.add_paragraph(f"资源：{'；'.join(action.get('resources') or [])}", style="List Continue")
            if action.get("deadline"):
                document.add_paragraph(f"截止：{action.get('deadline')}", style="List Continue")

    document.add_heading("五、评估与动态调整", level=1)
    evaluation = report.get("evaluation") or {}
    if evaluation.get("cycle"):
        p = document.add_paragraph()
        p.add_run("评估周期：").bold = True
        p.add_run(str(evaluation.get("cycle") or ""))
    document.add_heading("评估指标", level=2)
    _doc_add_list(document, evaluation.get("kpis") or [], "暂无评估指标。")
    if evaluation.get("adjustment"):
        p = document.add_paragraph()
        p.add_run("动态调整：").bold = True
        p.add_run(str(evaluation.get("adjustment") or ""))

    buf = io.BytesIO()
    document.save(buf)
    return buf.getvalue()
