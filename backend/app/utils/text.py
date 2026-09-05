from __future__ import annotations

import re
import unicodedata

_SPLIT_RE = re.compile(r"[\s,，、;；|/]+")
_HTML_RE = re.compile(r"<[^>]+>")


def normalize_text(s: str) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    s = _HTML_RE.sub(" ", s)
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = s.replace("\u3000", " ")
    # Keep line boundaries for section splitting while normalizing intra-line spaces.
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in s.split("\n")]
    s = "\n".join(lines)
    s = re.sub(r"\n{3,}", "\n\n", s).strip()
    return s


def normalize_token(s: str) -> str:
    s = normalize_text(s)
    s = s.lower()
    # remove common punctuation / quotes
    s = re.sub(r"[()\[\]{}<>\"'“”‘’`]", "", s)
    s = re.sub(r"\s+", "", s)
    return s


def split_tokens(s: str) -> list[str]:
    s = normalize_text(s)
    parts = [p.strip() for p in _SPLIT_RE.split(s) if p.strip()]
    return parts
