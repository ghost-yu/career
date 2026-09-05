from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.db import sqlite as db
from app.services.llm import llm_client
from app.services.student_profile import generate_student_profile_from_text
from app.utils.docx import extract_text_from_docx
from app.utils.ids import gen_id, now_iso
from app.utils.pdf import extract_text_from_pdf
from app.utils.text import normalize_text

_WORD_GLOB = "*.docx"
_PDF_GLOB = "*.pdf"
_SEQ_RE = re.compile(r"(\d+)$")
_NUMERIC_STEM_RE = re.compile(r"^\d+$")


def _candidate_roots(source_root: str | None) -> list[Path]:
    if source_root:
        return [Path(source_root).resolve()]
    cwd = Path.cwd().resolve()
    return [cwd, cwd.parent, cwd.parent.parent]


def _is_resume_like_file(path: Path) -> bool:
    suffix = path.suffix.lower()
    if suffix not in {".docx", ".pdf"}:
        return False
    stem = path.stem.strip().lower()
    if not stem:
        return False
    if stem.startswith("student_resume_"):
        return True
    if _NUMERIC_STEM_RE.fullmatch(stem):
        return True
    if "resume" in stem:
        return True
    if "简历" in path.stem:
        return True
    return False


def _discover_resume_files(source_root: str | None = None) -> tuple[Path | None, list[Path]]:
    for root in _candidate_roots(source_root):
        files = sorted(list(root.glob(_WORD_GLOB)) + list(root.glob(_PDF_GLOB)), key=lambda p: p.name)
        files = [p for p in files if _is_resume_like_file(p)]
        if files:
            return root, files
    return None, []


def _seq_from_filename(path: Path, fallback: int) -> int:
    m = _SEQ_RE.search(path.stem)
    if not m:
        return fallback
    try:
        return int(m.group(1))
    except Exception:
        return fallback


def _extract_resume_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return extract_text_from_pdf(str(path))
    if suffix == ".docx":
        return extract_text_from_docx(str(path))
    raise ValueError(f"Unsupported resume format: {suffix}")


def import_competition_resumes_with_ai(
    *,
    source_root: str | None = None,
    student_id_prefix: str = "STU",
    overwrite_existing: bool = True,
    limit: int | None = None,
    require_llm: bool = False,
) -> dict[str, Any]:
    root, files = _discover_resume_files(source_root=source_root)
    llm_enabled = llm_client.is_enabled()
    if require_llm and not llm_enabled:
        return {
            "ok": False,
            "message": "LLM is disabled; enable provider/api_key/model before strict AI import",
            "source_root": str(root) if root else None,
            "llm_enabled": llm_enabled,
            "llm_required": True,
            "items": [],
        }
    if limit is not None:
        files = files[: max(0, int(limit))]
    if not files:
        return {"ok": False, "message": "No competition resumes found", "source_root": str(root) if root else None, "items": []}

    items: list[dict[str, Any]] = []
    imported = 0
    skipped = 0
    failed = 0

    for idx, src in enumerate(files, start=1):
        seq = _seq_from_filename(src, idx)
        student_id = f"{student_id_prefix}{seq:03d}"
        student_name = f"学生{seq:02d}"
        current = db.get_student_profile(student_id)
        if current and not overwrite_existing:
            skipped += 1
            items.append(
                {
                    "student_id": student_id,
                    "filename": src.name,
                    "status": "skipped_existing_profile",
                }
            )
            continue

        try:
            db.upsert_student(student_id, student_name, created_at=now_iso())

            file_id = gen_id("FILE", 10)
            dst_dir = Path(settings.data_dir) / "resumes" / student_id
            dst_dir.mkdir(parents=True, exist_ok=True)
            dst_path = dst_dir / f"{file_id}{src.suffix.lower()}"
            shutil.copy2(src, dst_path)
            db.insert_student_file(
                file_id=file_id,
                student_id=student_id,
                filename=src.name,
                path=str(dst_path).replace("\\", "/"),
                created_at=now_iso(),
            )

            text = normalize_text(_extract_resume_text(src))
            if not text:
                raise ValueError("resume_text_empty_after_extraction")

            profile = generate_student_profile_from_text(
                student_id=student_id,
                text=text,
                persist=True,
                manual_payload={"name": student_name, "resume_filename": src.name},
                require_llm=require_llm,
            )

            imported += 1
            items.append(
                {
                    "student_id": student_id,
                    "filename": src.name,
                    "status": "imported",
                    "text_chars": len(text),
                    "hard_skill_count": len(profile.hard_skills),
                    "certificate_count": len(profile.certificates),
                    "completeness_score": profile.completeness_score,
                    "competitiveness_score": profile.competitiveness_score,
                    "ai_mode": "llm" if llm_enabled else "rules",
                }
            )
        except Exception as exc:
            failed += 1
            items.append(
                {
                    "student_id": student_id,
                    "filename": src.name,
                    "status": "failed",
                    "error": str(exc),
                }
            )

    return {
        "ok": failed == 0,
        "source_root": str(root) if root else None,
        "llm_enabled": llm_enabled,
        "llm_required": bool(require_llm),
        "total": len(files),
        "imported": imported,
        "skipped": skipped,
        "failed": failed,
        "items": items,
    }
