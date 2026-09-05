from __future__ import annotations

import re

from app.utils.text import normalize_text, normalize_token

# Lightweight Chinese section heuristics for JD/resume.
JD_HEADERS = [
    ("responsibilities", ["岗位职责", "工作职责", "职位描述", "职责描述", "主要职责"]),
    ("requirements", ["任职要求", "岗位要求", "职位要求", "任职资格", "能力要求"]),
    ("plus", ["加分项", "优先", "优先考虑", "加分", "加分条件"]),
    ("benefits", ["福利", "待遇", "我们提供", "薪酬福利", "公司福利"]),
]

RESUME_HEADERS = [
    ("education", ["教育经历", "教育背景", "学历背景", "教育信息", "学习经历", "学历信息"]),
    ("internship", ["实习", "实习详情", "实习经历", "实习经验", "工作经历", "工作经验", "实践经历", "实践经验", "任职经历"]),
    ("project", ["项目", "项目经历", "项目经验", "项目实践", "项目详情", "项目介绍", "实践项目", "科研项目", "课程项目"]),
    ("skills", ["技能", "专业技能", "技能清单", "技术栈", "能力清单", "技术技能", "核心技能", "专业能力", "技能特长"]),
    ("certificates", ["证书", "资格证书", "证照", "语言能力", "资格认证", "证书奖项", "语言证书"]),
    ("awards", ["获奖", "奖项", "荣誉", "荣誉奖项", "荣誉奖励", "竞赛获奖", "奖励情况"]),
    ("publications", ["论文", "发表", "科研成果", "学术成果", "科研论文", "论文成果"]),
    ("self_eval", ["自我评价", "个人总结", "个人优势", "自我介绍", "个人评价"]),
]


def _line_key(line: str) -> str:
    # Drop trailing ":" for heading lines.
    cleaned = re.sub(r"[:：]\s*$", "", line.strip())
    cleaned = re.sub(r"^[\-\*•·\d一二三四五六七八九十、.)）\s]+", "", cleaned)
    cleaned = re.sub(r"[（(][^()（）]{0,30}[)）]\s*$", "", cleaned)
    return normalize_token(cleaned)


def _append_section(sections: dict[str, str], key: str, lines: list[str]) -> None:
    chunk = "\n".join([x for x in lines if x]).strip()
    if not chunk:
        return
    if sections.get(key):
        sections[key] = f"{sections[key]}\n{chunk}".strip()
    else:
        sections[key] = chunk


def _split_by_headers(text: str, headers: list[tuple[str, list[str]]]) -> dict[str, str]:
    text = normalize_text(text)
    if not text:
        return {"body": ""}

    header_map: dict[str, str] = {}
    for key, aliases in headers:
        for alias in aliases:
            header_map[_line_key(alias)] = key

    sections: dict[str, str] = {}
    current = "body"
    buf: list[str] = []
    matched_header = False

    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line:
            if buf and buf[-1] != "":
                buf.append("")
            continue

        key = header_map.get(_line_key(line))
        # Heading lines are usually short and standalone.
        if key and len(line) <= 24:
            matched_header = True
            _append_section(sections, current, buf)
            current = key
            buf = []
            continue

        buf.append(line)

    _append_section(sections, current, buf)

    if not matched_header:
        return {"body": text}
    sections.setdefault("body", text)
    return sections


def split_jd(text: str) -> dict[str, str]:
    return _split_by_headers(text, JD_HEADERS)


def split_resume(text: str) -> dict[str, str]:
    return _split_by_headers(text, RESUME_HEADERS)
