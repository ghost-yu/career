from __future__ import annotations

from pathlib import Path
from typing import Tuple

import fitz  # PyMuPDF

from app.utils.text import normalize_text


def extract_text_from_pdf(path: str) -> str:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(path)
    doc = fitz.open(path)
    texts = []
    for page in doc:
        texts.append(page.get_text("text"))
    doc.close()
    return normalize_text("\n".join(texts))
