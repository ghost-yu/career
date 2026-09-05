from __future__ import annotations

import csv
import io
import json
import random
from pathlib import Path
from typing import Any

from app.db import sqlite as db

SKILL_CSV_FIELDS = [
    "student_id",
    "job_id",
    "overall_score",
    "skill_id",
    "skill_name",
    "importance",
    "predicted_match",
    "predicted_match_score",
    "source_list",
    "true_match",
    "reviewer_note",
]

PROFILE_CSV_FIELDS = [
    "entity_type",
    "entity_id",
    "field_name",
    "predicted_value",
    "true_value",
    "is_correct",
    "reviewer_note",
]


def split_csv_arg(raw: str | list[str] | None) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        return [x.strip() for x in raw.split(",") if x.strip()]
    out: list[str] = []
    for item in raw:
        val = str(item or "").strip()
        if val:
            out.append(val)
    return out


def _safe_json(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return {}
    try:
        obj = json.loads(raw)
    except Exception:
        return {}
    return obj if isinstance(obj, dict) else {}


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


def export_skill_match_label_rows(students: list[str] | None = None, jobs: list[str] | None = None) -> tuple[list[dict[str, Any]], int]:
    db.init_db()
    conn = db.get_conn()
    students = students or []
    jobs = jobs or []

    sql = "SELECT student_id, job_id, result_json FROM match_cache WHERE 1=1"
    params: list[Any] = []
    if students:
        sql += f" AND student_id IN ({','.join(['?'] * len(students))})"
        params.extend(students)
    if jobs:
        sql += f" AND job_id IN ({','.join(['?'] * len(jobs))})"
        params.extend(jobs)
    sql += " ORDER BY student_id, job_id"

    source_rows = list(conn.execute(sql, params).fetchall())
    out: list[dict[str, Any]] = []
    for row in source_rows:
        sid = str(row["student_id"])
        jid = str(row["job_id"])
        result = _safe_json(row["result_json"])

        overall = _to_float(result.get("overall_score"))
        dim = (result.get("dimension_scores") or {}).get("skills") or {}
        matched = dim.get("matched") or []
        missing = dim.get("missing") or []

        for item in matched:
            match_score = _to_float(item.get("match"))
            out.append(
                {
                    "student_id": sid,
                    "job_id": jid,
                    "overall_score": round(overall, 4),
                    "skill_id": str(item.get("skill_id") or "").strip(),
                    "skill_name": str(item.get("name") or item.get("skill_id") or "").strip(),
                    "importance": str(item.get("importance") or "").strip(),
                    "predicted_match": 1 if match_score > 0 else 0,
                    "predicted_match_score": round(match_score, 4),
                    "source_list": "matched",
                    "true_match": "",
                    "reviewer_note": "",
                }
            )

        for item in missing:
            out.append(
                {
                    "student_id": sid,
                    "job_id": jid,
                    "overall_score": round(overall, 4),
                    "skill_id": str(item.get("skill_id") or "").strip(),
                    "skill_name": str(item.get("name") or item.get("skill_id") or "").strip(),
                    "importance": str(item.get("importance") or "").strip(),
                    "predicted_match": 0,
                    "predicted_match_score": 0.0,
                    "source_list": "missing",
                    "true_match": "",
                    "reviewer_note": "",
                }
            )

        if not matched and not missing:
            out.append(
                {
                    "student_id": sid,
                    "job_id": jid,
                    "overall_score": round(overall, 4),
                    "skill_id": "",
                    "skill_name": "",
                    "importance": "",
                    "predicted_match": "",
                    "predicted_match_score": "",
                    "source_list": "no_skill_items",
                    "true_match": "",
                    "reviewer_note": "",
                }
            )

    return out, len(source_rows)


def _join_values(values: list[Any], *, key: str, limit: int) -> str:
    out: list[str] = []
    for item in values[:limit]:
        if isinstance(item, dict):
            raw = str(item.get(key) or item.get("name") or item.get("mention") or "").strip()
        else:
            raw = str(item or "").strip()
        if raw:
            out.append(raw)
    return " | ".join(out)


def _job_profile_rows(job_id: str, profile: dict[str, Any]) -> list[dict[str, str]]:
    basic = profile.get("basic_requirements") or {}
    return [
        {"entity_type": "job", "entity_id": job_id, "field_name": "job_family", "predicted_value": str(profile.get("job_family") or "")},
        {
            "entity_type": "job",
            "entity_id": job_id,
            "field_name": "hard_skills_top10",
            "predicted_value": _join_values(profile.get("hard_skills") or [], key="mention", limit=10),
        },
        {
            "entity_type": "job",
            "entity_id": job_id,
            "field_name": "soft_skills_top5",
            "predicted_value": _join_values(profile.get("soft_skills") or [], key="name", limit=5),
        },
        {
            "entity_type": "job",
            "entity_id": job_id,
            "field_name": "certificates_top5",
            "predicted_value": _join_values(profile.get("certificates") or [], key="name", limit=5),
        },
        {"entity_type": "job", "entity_id": job_id, "field_name": "education", "predicted_value": str(basic.get("education") or "")},
        {
            "entity_type": "job",
            "entity_id": job_id,
            "field_name": "experience_years_min",
            "predicted_value": str(basic.get("experience_years_min") if basic.get("experience_years_min") is not None else ""),
        },
    ]


def _student_profile_rows(student_id: str, profile: dict[str, Any]) -> list[dict[str, str]]:
    exp = profile.get("experience") or {}
    pref = profile.get("preferences") or {}
    return [
        {
            "entity_type": "student",
            "entity_id": student_id,
            "field_name": "hard_skills_top10",
            "predicted_value": _join_values(profile.get("hard_skills") or [], key="mention", limit=10),
        },
        {
            "entity_type": "student",
            "entity_id": student_id,
            "field_name": "soft_skills_top5",
            "predicted_value": _join_values(profile.get("soft_skills") or [], key="name", limit=5),
        },
        {
            "entity_type": "student",
            "entity_id": student_id,
            "field_name": "certificates_top5",
            "predicted_value": _join_values(profile.get("certificates") or [], key="name", limit=5),
        },
        {
            "entity_type": "student",
            "entity_id": student_id,
            "field_name": "preferred_job_families",
            "predicted_value": " | ".join([str(x).strip() for x in (pref.get("preferred_job_families") or []) if str(x).strip()]),
        },
        {
            "entity_type": "student",
            "entity_id": student_id,
            "field_name": "preferred_locations",
            "predicted_value": " | ".join([str(x).strip() for x in (pref.get("preferred_locations") or []) if str(x).strip()]),
        },
        {"entity_type": "student", "entity_id": student_id, "field_name": "internships", "predicted_value": str(exp.get("internships") or 0)},
        {"entity_type": "student", "entity_id": student_id, "field_name": "projects", "predicted_value": str(exp.get("projects") or 0)},
        {"entity_type": "student", "entity_id": student_id, "field_name": "awards", "predicted_value": str(exp.get("awards") or 0)},
        {"entity_type": "student", "entity_id": student_id, "field_name": "open_source", "predicted_value": str(exp.get("open_source") or 0)},
        {"entity_type": "student", "entity_id": student_id, "field_name": "leadership", "predicted_value": str(exp.get("leadership") or 0)},
    ]


def _with_label_slots(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for row in rows:
        out.append({**row, "true_value": "", "is_correct": "", "reviewer_note": ""})
    return out


def export_profile_label_rows(
    random_jobs: int = 0,
    random_students: int = 0,
    seed: int = 42,
    jobs: list[str] | None = None,
    students: list[str] | None = None,
) -> tuple[list[dict[str, str]], int, int]:
    db.init_db()
    conn = db.get_conn()

    rng = random.Random(seed)
    jobs = jobs or []
    students = students or []

    job_rows = list(conn.execute("SELECT job_id, profile_json FROM job_profiles").fetchall())
    student_rows = list(conn.execute("SELECT student_id, profile_json FROM student_profiles").fetchall())

    if jobs:
        allow_jobs = set(jobs)
        job_rows = [row for row in job_rows if str(row["job_id"]) in allow_jobs]
    if students:
        allow_students = set(students)
        student_rows = [row for row in student_rows if str(row["student_id"]) in allow_students]

    sampled_jobs = job_rows if random_jobs <= 0 or len(job_rows) <= random_jobs else rng.sample(job_rows, random_jobs)
    sampled_students = student_rows if random_students <= 0 or len(student_rows) <= random_students else rng.sample(student_rows, random_students)

    rows: list[dict[str, str]] = []
    for item in sampled_jobs:
        profile = _safe_json(item["profile_json"])
        rows.extend(_with_label_slots(_job_profile_rows(str(item["job_id"]), profile)))
    for item in sampled_students:
        profile = _safe_json(item["profile_json"])
        rows.extend(_with_label_slots(_student_profile_rows(str(item["student_id"]), profile)))

    return rows, len(sampled_jobs), len(sampled_students)


def write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> Path:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return path


def _read_csv_rows_from_text(text: str) -> list[dict[str, Any]]:
    reader = csv.DictReader(io.StringIO(text))
    return [dict(row) for row in reader]


def read_csv_rows_from_bytes(data: bytes) -> list[dict[str, Any]]:
    try:
        text = data.decode("utf-8-sig")
    except Exception:
        text = data.decode("gbk", errors="ignore")
    return _read_csv_rows_from_text(text)


def read_csv_rows_from_path(path: str | Path) -> list[dict[str, Any]]:
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError(f"csv not found: {p}")
    text = p.read_text(encoding="utf-8-sig", errors="ignore")
    return _read_csv_rows_from_text(text)


def _parse_binary(value: Any) -> int | None:
    raw = str(value or "").strip().lower()
    if raw == "":
        return None
    if raw in {"1", "true", "yes", "y", "matched", "hit"}:
        return 1
    if raw in {"0", "false", "no", "n", "missing", "miss"}:
        return 0
    try:
        num = float(raw)
    except Exception:
        return None
    return 1 if num >= 0.5 else 0


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _parse_bool(value: Any) -> bool | None:
    raw = str(value or "").strip().lower()
    if raw == "":
        return None
    if raw in {"1", "true", "yes", "y", "ok", "correct"}:
        return True
    if raw in {"0", "false", "no", "n", "wrong", "incorrect"}:
        return False
    return None


def _safe_ratio(numer: float, denom: float) -> float:
    if denom <= 0:
        return 0.0
    return float(numer) / float(denom)


def compute_skill_match_accuracy(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total_rows = 0
    labeled_rows = 0
    correct_rows = 0
    tp = fp = tn = fn = 0
    by_importance: dict[str, dict[str, int]] = {}

    for row in rows:
        total_rows += 1
        pred = _parse_binary(row.get("predicted_match"))
        true = _parse_binary(row.get("true_match"))
        if pred is None or true is None:
            continue

        labeled_rows += 1
        if pred == true:
            correct_rows += 1
        if pred == 1 and true == 1:
            tp += 1
        elif pred == 1 and true == 0:
            fp += 1
        elif pred == 0 and true == 0:
            tn += 1
        else:
            fn += 1

        imp = str(row.get("importance") or "unknown").strip().lower() or "unknown"
        bucket = by_importance.setdefault(imp, {"labeled": 0, "correct": 0})
        bucket["labeled"] += 1
        if pred == true:
            bucket["correct"] += 1

    accuracy = _safe_ratio(correct_rows, labeled_rows)
    precision = _safe_ratio(tp, tp + fp)
    recall = _safe_ratio(tp, tp + fn)
    f1 = _safe_ratio(2 * precision * recall, precision + recall if precision + recall else 0)

    return {
        "ok": True,
        "total_rows": total_rows,
        "labeled_rows": labeled_rows,
        "unlabeled_rows": total_rows - labeled_rows,
        "accuracy": round(accuracy, 6),
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "f1": round(f1, 6),
        "confusion": {"tp": tp, "fp": fp, "tn": tn, "fn": fn},
        "by_importance": {
            key: {
                "labeled": val["labeled"],
                "correct": val["correct"],
                "accuracy": round(_safe_ratio(val["correct"], val["labeled"]), 6),
            }
            for key, val in sorted(by_importance.items(), key=lambda x: x[0])
        },
    }


def compute_profile_accuracy(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total_rows = 0
    labeled_rows = 0
    correct_rows = 0

    by_field: dict[str, dict[str, int]] = {}
    by_entity: dict[str, dict[str, int]] = {}

    for row in rows:
        total_rows += 1
        entity = str(row.get("entity_type") or "unknown").strip().lower() or "unknown"
        field_name = str(row.get("field_name") or "unknown").strip().lower() or "unknown"

        is_correct = _parse_bool(row.get("is_correct"))
        if is_correct is None:
            true_val = row.get("true_value")
            if str(true_val or "").strip() == "":
                continue
            is_correct = _normalize_text(row.get("predicted_value")) == _normalize_text(true_val)

        labeled_rows += 1
        if is_correct:
            correct_rows += 1

        fb = by_field.setdefault(field_name, {"labeled": 0, "correct": 0})
        fb["labeled"] += 1
        if is_correct:
            fb["correct"] += 1

        eb = by_entity.setdefault(entity, {"labeled": 0, "correct": 0})
        eb["labeled"] += 1
        if is_correct:
            eb["correct"] += 1

    return {
        "ok": True,
        "total_rows": total_rows,
        "labeled_rows": labeled_rows,
        "unlabeled_rows": total_rows - labeled_rows,
        "accuracy": round(_safe_ratio(correct_rows, labeled_rows), 6),
        "by_field": {
            key: {
                "labeled": val["labeled"],
                "correct": val["correct"],
                "accuracy": round(_safe_ratio(val["correct"], val["labeled"]), 6),
            }
            for key, val in sorted(by_field.items(), key=lambda x: x[0])
        },
        "by_entity_type": {
            key: {
                "labeled": val["labeled"],
                "correct": val["correct"],
                "accuracy": round(_safe_ratio(val["correct"], val["labeled"]), 6),
            }
            for key, val in sorted(by_entity.items(), key=lambda x: x[0])
        },
    }
