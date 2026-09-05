from __future__ import annotations

from typing import Any

EXPERIENCE_DETAIL_FIELDS = (
    "internships",
    "projects",
    "awards",
    "open_source",
    "leadership",
    "publications",
)


def _clean_text(value: Any, *, limit: int | None = None) -> str:
    text = str(value or "").strip()
    if limit is not None and len(text) > limit:
        return text[:limit].rstrip()
    return text


def _safe_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


def _safe_count(value: Any) -> int:
    try:
        return max(0, int(value))
    except Exception:
        return 0


def _dedupe_text_list(values: list[str], *, limit: int) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        text = _clean_text(raw)
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
        if len(out) >= max(1, limit):
            break
    return out


def _collect_skill_names(items: Any, *, keys: tuple[str, ...], limit: int) -> list[str]:
    if not isinstance(items, list):
        return []
    out: list[str] = []
    for item in items:
        if isinstance(item, dict):
            value = ""
            for key in keys:
                value = _clean_text(item.get(key))
                if value:
                    break
            if value:
                out.append(value)
        else:
            value = _clean_text(item)
            if value:
                out.append(value)
        if len(out) >= max(1, limit):
            break
    return _dedupe_text_list(out, limit=limit)


def _normalize_detail_items(raw: Any, *, limit_per_field: int) -> dict[str, list[dict[str, str]]]:
    result: dict[str, list[dict[str, str]]] = {field: [] for field in EXPERIENCE_DETAIL_FIELDS}
    if not isinstance(raw, dict):
        return result
    for field in EXPERIENCE_DETAIL_FIELDS:
        values = raw.get(field)
        if not isinstance(values, list):
            if isinstance(values, str):
                text = _clean_text(values)
                if text:
                    result[field].append({"content": text, "evidence": text})
            continue
        for item in values:
            content = ""
            evidence = ""
            if isinstance(item, dict):
                content = _clean_text(
                    item.get("content")
                    or item.get("text")
                    or item.get("summary")
                    or item.get("value")
                    or item.get("detail")
                )
                evidence = _clean_text(item.get("evidence") or item.get("quote") or item.get("source"))
            else:
                text = _clean_text(item)
                content = text
                evidence = text
            if not content and not evidence:
                continue
            if not content:
                content = evidence
            if not evidence:
                evidence = content
            result[field].append({"content": content, "evidence": evidence})
            if len(result[field]) >= max(1, limit_per_field):
                break
    return result


def _detail_items_from_evidence_map(raw: Any, *, limit_per_field: int) -> dict[str, list[dict[str, str]]]:
    result: dict[str, list[dict[str, str]]] = {field: [] for field in EXPERIENCE_DETAIL_FIELDS}
    if not isinstance(raw, dict):
        return result
    for field in EXPERIENCE_DETAIL_FIELDS:
        values = raw.get(field)
        if isinstance(values, str):
            text = _clean_text(values)
            if text:
                result[field].append({"content": text, "evidence": text})
            continue
        if not isinstance(values, list):
            continue
        for item in values:
            text = _clean_text(item)
            if not text:
                continue
            result[field].append({"content": text, "evidence": text})
            if len(result[field]) >= max(1, limit_per_field):
                break
    return result


def _extract_detail_items(profile: dict[str, Any], *, limit_per_field: int) -> dict[str, list[dict[str, str]]]:
    meta = profile.get("extraction_meta") if isinstance(profile.get("extraction_meta"), dict) else {}
    detail_items = _normalize_detail_items(
        (meta or {}).get("experience_detail_items") if isinstance(meta, dict) else None,
        limit_per_field=limit_per_field,
    )
    if any(detail_items.get(field) for field in EXPERIENCE_DETAIL_FIELDS):
        return detail_items

    detail_items = _normalize_detail_items(
        profile.get("experience_detail_items"),
        limit_per_field=limit_per_field,
    )
    if any(detail_items.get(field) for field in EXPERIENCE_DETAIL_FIELDS):
        return detail_items

    evidence_map = (
        (meta or {}).get("experience_evidence")
        if isinstance(meta, dict)
        else None
    )
    detail_items = _detail_items_from_evidence_map(evidence_map, limit_per_field=limit_per_field)
    if any(detail_items.get(field) for field in EXPERIENCE_DETAIL_FIELDS):
        return detail_items

    return _detail_items_from_evidence_map(profile.get("experience_details"), limit_per_field=limit_per_field)


def _resolve_salary(preferences: dict[str, Any]) -> tuple[int | None, int | None]:
    target_salary_min = _safe_int(preferences.get("target_salary_min"))
    target_salary_max = _safe_int(preferences.get("target_salary_max"))
    if target_salary_min is None:
        target_salary_min = _safe_int(preferences.get("salary_min"))
    if target_salary_max is None:
        target_salary_max = _safe_int(preferences.get("salary_max"))
    if target_salary_min is None and isinstance(preferences.get("salary_expectation"), dict):
        target_salary_min = _safe_int((preferences.get("salary_expectation") or {}).get("min"))
    if target_salary_max is None and isinstance(preferences.get("salary_expectation"), dict):
        target_salary_max = _safe_int((preferences.get("salary_expectation") or {}).get("max"))
    return target_salary_min, target_salary_max


def build_student_profile_snapshot(
    profile: dict[str, Any] | None,
    *,
    hard_limit: int = 30,
    soft_limit: int = 20,
    cert_limit: int = 12,
    detail_limit_per_field: int = 5,
    include_detail_items: bool = True,
    include_education: bool = True,
    notes_limit: int = 280,
    profile_notes_limit: int = 420,
) -> dict[str, Any]:
    source = profile if isinstance(profile, dict) else {}
    preferences = source.get("preferences") if isinstance(source.get("preferences"), dict) else {}
    detail_items = _extract_detail_items(source, limit_per_field=detail_limit_per_field)

    experience_raw = source.get("experience") if isinstance(source.get("experience"), dict) else {}
    experience_counts = {
        field: max(_safe_count(experience_raw.get(field)), len(detail_items.get(field) or []))
        for field in EXPERIENCE_DETAIL_FIELDS
    }
    evidence_counts = {field: len(detail_items.get(field) or []) for field in EXPERIENCE_DETAIL_FIELDS}

    pref_notes = _clean_text(preferences.get("notes"), limit=notes_limit)
    profile_notes = _clean_text(source.get("profile_notes"), limit=profile_notes_limit)
    if pref_notes and profile_notes and pref_notes == profile_notes:
        profile_notes = ""

    target_salary_min, target_salary_max = _resolve_salary(preferences)

    payload: dict[str, Any] = {
        "mbti_type": _clean_text(source.get("mbti_type")) or None,
        "hard_skills": _collect_skill_names(
            source.get("hard_skills"),
            keys=("mention", "name", "skill_id"),
            limit=max(1, hard_limit),
        ),
        "soft_skills": _collect_skill_names(
            source.get("soft_skills"),
            keys=("name", "mention", "soft_skill_id"),
            limit=max(1, soft_limit),
        ),
        "certificates": _collect_skill_names(
            source.get("certificates"),
            keys=("name", "mention", "certificate_id"),
            limit=max(1, cert_limit),
        ),
        "experience": experience_counts,
        "experience_evidence_counts": evidence_counts,
        "experience_summary": [
            f"实习{experience_counts['internships']}段",
            f"项目{experience_counts['projects']}项",
            f"获奖{experience_counts['awards']}项",
            f"开源{experience_counts['open_source']}项",
            f"负责人经历{experience_counts['leadership']}项",
        ],
        "preferences": {
            "preferred_locations": _dedupe_text_list(
                [_clean_text(x) for x in (preferences.get("preferred_locations") or [])],
                limit=8,
            ),
            "preferred_job_families": _dedupe_text_list(
                [_clean_text(x) for x in (preferences.get("preferred_job_families") or [])],
                limit=8,
            ),
            "target_salary_min": target_salary_min,
            "target_salary_max": target_salary_max,
            "notes": pref_notes,
        },
        "profile_notes": profile_notes,
    }

    if include_education:
        payload["education"] = source.get("education") if isinstance(source.get("education"), dict) else {}
    if include_detail_items:
        payload["experience_detail_items"] = detail_items
    return payload
