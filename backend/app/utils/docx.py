from __future__ import annotations

import re
import zipfile
from xml.etree import ElementTree as ET

from app.utils.text import normalize_text

WORD_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


def _extract_paragraph_lines(xml_raw: bytes) -> list[str]:
    try:
        root = ET.fromstring(xml_raw)
    except Exception:
        return []

    lines: list[str] = []
    # Use `.//w:p` so we can read paragraphs in tables as well.
    for para in root.findall(".//w:p", WORD_NS):
        chunks = [node.text for node in para.findall(".//w:t", WORD_NS) if node.text]
        line = "".join(chunks).strip()
        if line:
            lines.append(line)
    return lines


def extract_text_from_docx(path: str) -> str:
    """Extract plain text from DOCX file.

    Includes document body + headers/footers and keeps paragraph boundaries.
    Returns an empty string on parse failure.
    """

    try:
        with zipfile.ZipFile(path, "r") as zf:
            xml_names = [
                name
                for name in zf.namelist()
                if name.startswith("word/")
                and name.endswith(".xml")
                and (
                    name == "word/document.xml"
                    or name.startswith("word/header")
                    or name.startswith("word/footer")
                )
            ]
            # Always process main document first.
            xml_names.sort(key=lambda n: (0 if n == "word/document.xml" else 1, n))

            lines: list[str] = []
            for name in xml_names:
                try:
                    raw = zf.read(name)
                except Exception:
                    continue
                lines.extend(_extract_paragraph_lines(raw))
    except Exception:
        return ""

    if not lines:
        return ""

    # Drop exact consecutive duplicates that are common in templates.
    deduped: list[str] = []
    for line in lines:
        if deduped and deduped[-1] == line:
            continue
        deduped.append(line)

    text = "\n".join(deduped)
    text = normalize_text(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
