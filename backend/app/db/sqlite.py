from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from app.core.config import settings

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None
_thread_local = threading.local()


def _ensure_dirs() -> None:
    Path(settings.data_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.sqlite_path).parent.mkdir(parents=True, exist_ok=True)


def get_conn() -> sqlite3.Connection:
    # Keep one connection per worker thread to avoid concurrent use of a
    # single sqlite connection object in FastAPI threadpool handlers.
    conn = getattr(_thread_local, "conn", None)
    if conn is None:
        _ensure_dirs()
        conn = sqlite3.connect(settings.sqlite_path, check_same_thread=False, timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
        except Exception:
            pass
        _thread_local.conn = conn
    return conn


def _ensure_column(table: str, column: str, ddl: str) -> None:
    conn = get_conn()
    cols = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
        conn.commit()


def _safe_json_dict(raw: Any) -> dict[str, Any]:
    """Best-effort JSON decode for stored dict payloads."""
    if raw is None:
        return {}
    if isinstance(raw, (bytes, bytearray)):
        try:
            raw = raw.decode("utf-8", errors="ignore")
        except Exception:
            return {}
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return {}
    text = raw.strip()
    if not text:
        return {}
    try:
        obj = json.loads(text)
    except Exception:
        return {}
    return obj if isinstance(obj, dict) else {}


def init_db() -> None:
    """Initialize SQLite schema.

    Notes
    -----
    - This project keeps storage minimal (SQLite) for demo/competition.
    - In production, replace with PostgreSQL/MySQL and run proper migrations.
    """

    conn = get_conn()
    with _lock:
        cur = conn.cursor()

        # -----------------------------
        # Dictionaries (skills/certs)
        # -----------------------------
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS dictionary_items (
                item_id TEXT PRIMARY KEY,
                item_type TEXT NOT NULL, -- hard_skill|soft_skill|certificate
                name_zh TEXT NOT NULL,
                name_en TEXT,
                category_lv1 TEXT,
                aliases_json TEXT NOT NULL DEFAULT '[]',
                description TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                merge_to TEXT
            );
            """
        )

        # -----------------------------
        # Raw jobs + structured profiles
        # -----------------------------
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                location TEXT,
                salary_min INTEGER,
                salary_max INTEGER,
                company_name TEXT,
                industry TEXT,
                company_size TEXT,
                company_type TEXT,
                job_code TEXT,
                description TEXT,
                company_intro TEXT,
                raw_json TEXT
            );
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS job_profiles (
                job_id TEXT PRIMARY KEY,
                profile_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )

        # -----------------------------
        # Role catalog (canonical roles)
        # -----------------------------
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS job_roles (
                role_id TEXT PRIMARY KEY,
                role_key TEXT NOT NULL UNIQUE,
                job_family TEXT,
                base_role TEXT,
                level_label TEXT,
                title_rep TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS job_role_members (
                role_id TEXT NOT NULL,
                job_id TEXT NOT NULL,
                PRIMARY KEY (role_id, job_id)
            );
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS role_profiles (
                role_id TEXT PRIMARY KEY,
                profile_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )

        # -----------------------------
        # Students + files + profiles
        # -----------------------------
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS students (
                student_id TEXT PRIMARY KEY,
                name TEXT,
                created_at TEXT NOT NULL
            );
            """
        )

        cur.execute("""
            CREATE TABLE IF NOT EXISTS student_owners (
                student_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL
            );
        """)

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS student_files (
                file_id TEXT PRIMARY KEY,
                student_id TEXT NOT NULL,
                filename TEXT NOT NULL,
                path TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS student_profiles (
                student_id TEXT PRIMARY KEY,
                profile_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )

        # -----------------------------
        # Student behavior events
        # -----------------------------
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS student_job_events (
                event_id TEXT PRIMARY KEY,
                student_id TEXT NOT NULL,
                event_type TEXT NOT NULL, -- VIEW|FAVORITE|APPLY|...
                job_id TEXT,
                role_id TEXT,
                event_value REAL NOT NULL DEFAULT 1.0,
                source TEXT,
                meta_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS student_job_preferences (
                student_id TEXT NOT NULL,
                job_id TEXT NOT NULL,
                preference TEXT NOT NULL, -- FAVORITE|DISMISS
                source TEXT,
                meta_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (student_id, job_id)
            );
            """
        )

        # -----------------------------
        # Matching cache + weights
        # -----------------------------
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS match_cache (
                student_id TEXT NOT NULL,
                job_id TEXT NOT NULL,
                result_json TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (student_id, job_id)
            );
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS weights (
                weights_key TEXT PRIMARY KEY, -- default or job_family or job_id
                weights_json TEXT NOT NULL,
                version TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )

        # -----------------------------
        # Reports
        # -----------------------------
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS reports (
                report_id TEXT PRIMARY KEY,
                student_id TEXT NOT NULL,
                content_json TEXT NOT NULL,
                content_md TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )

        # -----------------------------
        # Background tasks (batch pipelines)
        # -----------------------------
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                task_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                status TEXT NOT NULL, -- PENDING|RUNNING|SUCCESS|FAILED
                progress REAL NOT NULL DEFAULT 0,
                result_json TEXT,
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS system_settings (
                setting_key TEXT PRIMARY KEY,
                setting_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )

        # -----------------------------
        # Auth + chat sessions/messages
        # -----------------------------
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                display_name TEXT,
                role TEXT NOT NULL DEFAULT 'viewer',
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS registration_captchas (
                captcha_id TEXT PRIMARY KEY,
                answer_hash TEXT NOT NULL,
                expires_at INTEGER NOT NULL
            );
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_sessions (
                session_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                student_id TEXT,
                title TEXT,
                last_job_id TEXT,
                state_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_messages (
                message_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                role TEXT NOT NULL, -- user|assistant
                content TEXT NOT NULL,
                meta_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );
            """
        )

        _ensure_column("jobs", "salary_period", "TEXT")
        _ensure_column("jobs", "updated_date", "TEXT")
        _ensure_column("jobs", "source_url", "TEXT")
        _ensure_column("users", "role", "TEXT NOT NULL DEFAULT 'viewer'")

        cur.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status_created ON tasks(status, created_at);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_jobs_location ON jobs(location);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_roles_family ON job_roles(job_family);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_events_student_time ON student_job_events(student_id, created_at);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_events_job ON student_job_events(job_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_events_role ON student_job_events(role_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_preferences_student ON student_job_preferences(student_id, updated_at);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_preferences_job ON student_job_preferences(job_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_chat_sessions_user_time ON chat_sessions(user_id, updated_at);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_chat_messages_session_time ON chat_messages(session_id, created_at);")

        conn.commit()


# ---------------------------------------------------------------------------
# Dictionary
# ---------------------------------------------------------------------------

def upsert_dictionary_item(item: dict[str, Any]) -> None:
    conn = get_conn()
    with _lock:
        conn.execute(
            """
            INSERT INTO dictionary_items (item_id, item_type, name_zh, name_en, category_lv1, aliases_json, description, status, merge_to)
            VALUES (:item_id, :item_type, :name_zh, :name_en, :category_lv1, :aliases_json, :description, :status, :merge_to)
            ON CONFLICT(item_id) DO UPDATE SET
                item_type=excluded.item_type,
                name_zh=excluded.name_zh,
                name_en=excluded.name_en,
                category_lv1=excluded.category_lv1,
                aliases_json=excluded.aliases_json,
                description=excluded.description,
                status=excluded.status,
                merge_to=excluded.merge_to
            """,
            item,
        )
        conn.commit()


def fetch_dictionary_items(item_type: str | None = None, q: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    conn = get_conn()
    sql = "SELECT * FROM dictionary_items WHERE 1=1"
    params: dict[str, Any] = {}
    if item_type:
        sql += " AND item_type=:item_type"
        params["item_type"] = item_type
    if q:
        sql += " AND (name_zh LIKE :q OR name_en LIKE :q OR aliases_json LIKE :q)"
        params["q"] = f"%{q}%"
    sql += " ORDER BY name_zh ASC LIMIT :limit"
    params["limit"] = limit
    rows = conn.execute(sql, params).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["aliases"] = json.loads(d.get("aliases_json") or "[]")
        out.append(d)
    return out


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

def insert_job(job: dict[str, Any]) -> None:
    conn = get_conn()
    with _lock:
        conn.execute(
            """
            INSERT INTO jobs (job_id, title, location, salary_min, salary_max, salary_period, company_name, industry, company_size, company_type, job_code, description, company_intro, updated_date, source_url, raw_json)
            VALUES (:job_id, :title, :location, :salary_min, :salary_max, :salary_period, :company_name, :industry, :company_size, :company_type, :job_code, :description, :company_intro, :updated_date, :source_url, :raw_json)
            ON CONFLICT(job_id) DO UPDATE SET
                title=excluded.title,
                location=excluded.location,
                salary_min=excluded.salary_min,
                salary_max=excluded.salary_max,
                salary_period=excluded.salary_period,
                company_name=excluded.company_name,
                industry=excluded.industry,
                company_size=excluded.company_size,
                company_type=excluded.company_type,
                job_code=excluded.job_code,
                description=excluded.description,
                company_intro=excluded.company_intro,
                updated_date=excluded.updated_date,
                source_url=excluded.source_url,
                raw_json=excluded.raw_json
            """,
            job,
        )
        conn.commit()


def count_jobs() -> int:
    conn = get_conn()
    r = conn.execute("SELECT COUNT(1) AS c FROM jobs").fetchone()
    return int(r["c"]) if r else 0


def list_jobs(q: str | None = None, location: str | None = None, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    conn = get_conn()
    sql = "SELECT job_id, title, location, salary_min, salary_max, salary_period, company_name, industry, company_size, company_type, job_code, description, company_intro, updated_date, source_url FROM jobs WHERE 1=1"
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if q:
        sql += " AND (job_id LIKE :q OR job_code LIKE :q OR title LIKE :q OR description LIKE :q OR company_name LIKE :q OR location LIKE :q OR industry LIKE :q)"
        params["q"] = f"%{q}%"
    if location:
        sql += " AND (location LIKE :location)"
        params["location"] = f"%{location}%"
    sql += " ORDER BY job_id LIMIT :limit OFFSET :offset"
    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def get_job(job_id: str) -> dict[str, Any] | None:
    conn = get_conn()
    r = conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
    return dict(r) if r else None


def delete_job(job_id: str) -> None:
    conn = get_conn()
    with _lock:
        conn.execute("DELETE FROM student_job_events WHERE job_id=?", (job_id,))
        conn.execute("DELETE FROM student_job_preferences WHERE job_id=?", (job_id,))
        conn.execute("DELETE FROM match_cache WHERE job_id=?", (job_id,))
        conn.execute("DELETE FROM job_profiles WHERE job_id=?", (job_id,))
        conn.execute("DELETE FROM job_role_members WHERE job_id=?", (job_id,))
        conn.execute("DELETE FROM jobs WHERE job_id=?", (job_id,))
        conn.commit()


def iter_jobs(batch_size: int = 500) -> Any:
    """Iterate jobs in batches (for batch processing)."""
    conn = get_conn()
    offset = 0
    while True:
        rows = conn.execute(
            "SELECT job_id, title, location, salary_min, salary_max, salary_period, company_name, industry, company_size, company_type, job_code, description, company_intro, updated_date, source_url FROM jobs ORDER BY job_id LIMIT ? OFFSET ?",
            (batch_size, offset),
        ).fetchall()
        if not rows:
            break
        for r in rows:
            yield dict(r)
        offset += batch_size


def upsert_job_profile(job_id: str, profile_json: str, updated_at: str) -> None:
    conn = get_conn()
    with _lock:
        conn.execute(
            """
            INSERT INTO job_profiles (job_id, profile_json, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(job_id) DO UPDATE SET profile_json=excluded.profile_json, updated_at=excluded.updated_at
            """,
            (job_id, profile_json, updated_at),
        )
        conn.commit()


def get_job_profile(job_id: str) -> dict[str, Any] | None:
    conn = get_conn()
    jid = str(job_id or "").strip()
    if not jid:
        return None
    r = conn.execute("SELECT profile_json, updated_at FROM job_profiles WHERE job_id=?", (jid,)).fetchone()
    if not r:
        return None
    return {"job_id": jid, "profile": _safe_json_dict(r["profile_json"]), "updated_at": r["updated_at"]}


def count_job_profiles() -> int:
    conn = get_conn()
    r = conn.execute("SELECT COUNT(1) AS c FROM job_profiles").fetchone()
    return int(r["c"]) if r else 0


def list_job_profiles(limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT job_id, profile_json, updated_at FROM job_profiles ORDER BY updated_at DESC LIMIT ? OFFSET ?",
        (limit, offset),
    ).fetchall()
    return [
        {"job_id": r["job_id"], "profile": _safe_json_dict(r["profile_json"]), "updated_at": r["updated_at"]}
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------

def clear_roles() -> None:
    conn = get_conn()
    with _lock:
        conn.execute("DELETE FROM job_role_members")
        conn.execute("DELETE FROM role_profiles")
        conn.execute("DELETE FROM job_roles")
        conn.commit()


def upsert_role(role: dict[str, Any]) -> None:
    conn = get_conn()
    with _lock:
        conn.execute(
            """
            INSERT INTO job_roles (role_id, role_key, job_family, base_role, level_label, title_rep, created_at, updated_at)
            VALUES (:role_id, :role_key, :job_family, :base_role, :level_label, :title_rep, :created_at, :updated_at)
            ON CONFLICT(role_id) DO UPDATE SET
                role_key=excluded.role_key,
                job_family=excluded.job_family,
                base_role=excluded.base_role,
                level_label=excluded.level_label,
                title_rep=excluded.title_rep,
                updated_at=excluded.updated_at
            """,
            role,
        )
        conn.commit()


def get_role(role_id: str) -> dict[str, Any] | None:
    conn = get_conn()
    r = conn.execute("SELECT * FROM job_roles WHERE role_id=?", (role_id,)).fetchone()
    return dict(r) if r else None


def get_role_by_key(role_key: str) -> dict[str, Any] | None:
    conn = get_conn()
    r = conn.execute("SELECT * FROM job_roles WHERE role_key=?", (role_key,)).fetchone()
    return dict(r) if r else None


def count_roles() -> int:
    conn = get_conn()
    r = conn.execute("SELECT COUNT(1) AS c FROM job_roles").fetchone()
    return int(r["c"]) if r else 0


def count_role_members() -> int:
    conn = get_conn()
    r = conn.execute("SELECT COUNT(1) AS c FROM job_role_members").fetchone()
    return int(r["c"]) if r else 0


def list_roles(job_family: str | None = None, q: str | None = None, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    conn = get_conn()
    sql = "SELECT * FROM job_roles WHERE 1=1"
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if job_family:
        sql += " AND job_family=:job_family"
        params["job_family"] = job_family
    if q:
        sql += " AND (title_rep LIKE :q OR base_role LIKE :q OR role_key LIKE :q)"
        params["q"] = f"%{q}%"
    sql += " ORDER BY job_family, base_role, level_label LIMIT :limit OFFSET :offset"
    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def add_role_member(role_id: str, job_id: str) -> None:
    conn = get_conn()
    with _lock:
        conn.execute(
            """
            INSERT OR IGNORE INTO job_role_members (role_id, job_id)
            VALUES (?, ?)
            """,
            (role_id, job_id),
        )
        conn.commit()


def list_role_members(role_id: str) -> list[str]:
    conn = get_conn()
    rows = conn.execute("SELECT job_id FROM job_role_members WHERE role_id=?", (role_id,)).fetchall()
    return [r["job_id"] for r in rows]


def upsert_role_profile(role_id: str, profile_json: str, updated_at: str) -> None:
    conn = get_conn()
    with _lock:
        conn.execute(
            """
            INSERT INTO role_profiles (role_id, profile_json, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(role_id) DO UPDATE SET profile_json=excluded.profile_json, updated_at=excluded.updated_at
            """,
            (role_id, profile_json, updated_at),
        )
        conn.commit()


def get_role_profile(role_id: str) -> dict[str, Any] | None:
    conn = get_conn()
    rid = str(role_id or "").strip()
    if not rid:
        return None
    r = conn.execute("SELECT profile_json, updated_at FROM role_profiles WHERE role_id=?", (rid,)).fetchone()
    if not r:
        return None
    return {"role_id": rid, "profile": _safe_json_dict(r["profile_json"]), "updated_at": r["updated_at"]}


# ---------------------------------------------------------------------------
# Students
# ---------------------------------------------------------------------------

def count_students() -> int:
    conn = get_conn()
    r = conn.execute("SELECT COUNT(1) AS c FROM students").fetchone()
    return int(r["c"]) if r else 0


def count_student_profiles() -> int:
    conn = get_conn()
    r = conn.execute("SELECT COUNT(1) AS c FROM student_profiles").fetchone()
    return int(r["c"]) if r else 0


def count_student_events(student_id: str | None = None) -> int:
    conn = get_conn()
    if student_id:
        r = conn.execute("SELECT COUNT(1) AS c FROM student_job_events WHERE student_id=?", (student_id,)).fetchone()
    else:
        r = conn.execute("SELECT COUNT(1) AS c FROM student_job_events").fetchone()
    return int(r["c"]) if r else 0


def upsert_student(student_id: str, name: str | None, created_at: str) -> None:
    conn = get_conn()
    with _lock:
        conn.execute(
            """
            INSERT INTO students (student_id, name, created_at)
            VALUES (?, ?, ?)
            ON CONFLICT(student_id) DO UPDATE SET name=excluded.name
            """,
            (student_id, name, created_at),
        )
        conn.commit()


def get_student(student_id: str) -> dict[str, Any] | None:
    conn = get_conn()
    r = conn.execute("SELECT * FROM students WHERE student_id=?", (student_id,)).fetchone()
    return dict(r) if r else None


def insert_student_file(file_id: str, student_id: str, filename: str, path: str, created_at: str) -> None:
    conn = get_conn()
    with _lock:
        conn.execute(
            """
            INSERT INTO student_files (file_id, student_id, filename, path, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (file_id, student_id, filename, path, created_at),
        )
        conn.commit()


def list_student_files(student_id: str) -> list[dict[str, Any]]:
    conn = get_conn()
    rows = conn.execute("SELECT * FROM student_files WHERE student_id=? ORDER BY created_at DESC", (student_id,)).fetchall()
    return [dict(r) for r in rows]


def upsert_student_profile(student_id: str, profile_json: str, updated_at: str) -> None:
    conn = get_conn()
    with _lock:
        conn.execute(
            """
            INSERT INTO student_profiles (student_id, profile_json, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(student_id) DO UPDATE SET profile_json=excluded.profile_json, updated_at=excluded.updated_at
            """,
            (student_id, profile_json, updated_at),
        )
        conn.commit()


def get_student_profile(student_id: str) -> dict[str, Any] | None:
    conn = get_conn()
    sid = str(student_id or "").strip()
    if not sid:
        return None
    r = conn.execute("SELECT profile_json, updated_at FROM student_profiles WHERE student_id=?", (sid,)).fetchone()
    if not r:
        return None
    return {"student_id": sid, "profile": _safe_json_dict(r["profile_json"]), "updated_at": r["updated_at"]}


def count_student_profiles() -> int:
    conn = get_conn()
    r = conn.execute("SELECT COUNT(1) AS c FROM student_profiles").fetchone()
    return int(r["c"]) if r else 0


def insert_student_event(event: dict[str, Any]) -> None:
    conn = get_conn()
    with _lock:
        conn.execute(
            """
            INSERT INTO student_job_events (event_id, student_id, event_type, job_id, role_id, event_value, source, meta_json, created_at)
            VALUES (:event_id, :student_id, :event_type, :job_id, :role_id, :event_value, :source, :meta_json, :created_at)
            """,
            event,
        )
        conn.commit()


def list_student_events(
    student_id: str,
    event_type: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> list[dict[str, Any]]:
    conn = get_conn()
    sql = "SELECT * FROM student_job_events WHERE student_id=:student_id"
    params: dict[str, Any] = {"student_id": student_id, "limit": limit, "offset": offset}
    if event_type:
        sql += " AND event_type=:event_type"
        params["event_type"] = event_type
    sql += " ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
    rows = conn.execute(sql, params).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["meta"] = json.loads(d.get("meta_json") or "{}")
        except Exception:
            d["meta"] = {}
        out.append(d)
    return out


def upsert_student_job_preference(
    *,
    student_id: str,
    job_id: str,
    preference: str,
    source: str | None = None,
    meta_json: str = "{}",
    created_at: str,
    updated_at: str,
) -> None:
    conn = get_conn()
    with _lock:
        conn.execute(
            """
            INSERT INTO student_job_preferences (student_id, job_id, preference, source, meta_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(student_id, job_id) DO UPDATE SET
                preference=excluded.preference,
                source=excluded.source,
                meta_json=excluded.meta_json,
                updated_at=excluded.updated_at
            """,
            (student_id, job_id, preference, source, meta_json, created_at, updated_at),
        )
        conn.commit()


def delete_student_job_preference(student_id: str, job_id: str) -> None:
    conn = get_conn()
    with _lock:
        conn.execute(
            "DELETE FROM student_job_preferences WHERE student_id=? AND job_id=?",
            (student_id, job_id),
        )
        conn.commit()


def get_student_job_preference(student_id: str, job_id: str) -> dict[str, Any] | None:
    conn = get_conn()
    row = conn.execute(
        """
        SELECT student_id, job_id, preference, source, meta_json, created_at, updated_at
        FROM student_job_preferences
        WHERE student_id=? AND job_id=?
        """,
        (student_id, job_id),
    ).fetchone()
    if not row:
        return None
    data = dict(row)
    data["meta"] = _safe_json_dict(data.get("meta_json"))
    return data


def list_student_job_preferences(student_id: str, limit: int = 500, offset: int = 0) -> list[dict[str, Any]]:
    conn = get_conn()
    rows = conn.execute(
        """
        SELECT student_id, job_id, preference, source, meta_json, created_at, updated_at
        FROM student_job_preferences
        WHERE student_id=?
        ORDER BY updated_at DESC
        LIMIT ? OFFSET ?
        """,
        (student_id, limit, offset),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        data = dict(row)
        data["meta"] = _safe_json_dict(data.get("meta_json"))
        out.append(data)
    return out


# ---------------------------------------------------------------------------
# Match cache + weights
# ---------------------------------------------------------------------------

def upsert_match_cache(student_id: str, job_id: str, result_json: str, updated_at: str) -> None:
    conn = get_conn()
    with _lock:
        conn.execute(
            """
            INSERT INTO match_cache (student_id, job_id, result_json, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(student_id, job_id) DO UPDATE SET result_json=excluded.result_json, updated_at=excluded.updated_at
            """,
            (student_id, job_id, result_json, updated_at),
        )
        conn.commit()


def get_match_cache(student_id: str, job_id: str) -> dict[str, Any] | None:
    conn = get_conn()
    r = conn.execute(
        "SELECT result_json, updated_at FROM match_cache WHERE student_id=? AND job_id=?",
        (student_id, job_id),
    ).fetchone()
    if not r:
        return None
    return {"student_id": student_id, "job_id": job_id, "result": json.loads(r["result_json"]), "updated_at": r["updated_at"]}


def upsert_weights(weights_key: str, weights_json: str, version: str, updated_at: str) -> None:
    conn = get_conn()
    with _lock:
        conn.execute(
            """
            INSERT INTO weights (weights_key, weights_json, version, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(weights_key) DO UPDATE SET weights_json=excluded.weights_json, version=excluded.version, updated_at=excluded.updated_at
            """,
            (weights_key, weights_json, version, updated_at),
        )
        conn.commit()


def get_weights(weights_key: str) -> dict[str, Any] | None:
    conn = get_conn()
    r = conn.execute("SELECT weights_json, version, updated_at FROM weights WHERE weights_key=?", (weights_key,)).fetchone()
    if not r:
        return None
    return {"weights_key": weights_key, "weights": json.loads(r["weights_json"]), "version": r["version"], "updated_at": r["updated_at"]}



def list_weights(limit: int = 200, offset: int = 0) -> list[dict[str, Any]]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT weights_key, weights_json, version, updated_at FROM weights ORDER BY updated_at DESC LIMIT ? OFFSET ?",
        (limit, offset),
    ).fetchall()
    out = []
    for r in rows:
        out.append(
            {
                "weights_key": r["weights_key"],
                "weights": json.loads(r["weights_json"]),
                "version": r["version"],
                "updated_at": r["updated_at"],
            }
        )
    return out


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

def count_reports() -> int:
    conn = get_conn()
    r = conn.execute("SELECT COUNT(1) AS c FROM reports").fetchone()
    return int(r["c"]) if r else 0


def insert_report(report: dict[str, Any]) -> None:
    conn = get_conn()
    with _lock:
        conn.execute(
            """
            INSERT INTO reports (report_id, student_id, content_json, content_md, version, created_at, updated_at)
            VALUES (:report_id, :student_id, :content_json, :content_md, :version, :created_at, :updated_at)
            """,
            report,
        )
        conn.commit()


def update_report(report_id: str, content_json: str, content_md: str, updated_at: str) -> None:
    conn = get_conn()
    with _lock:
        conn.execute(
            """
            UPDATE reports SET content_json=?, content_md=?, version=version+1, updated_at=?
            WHERE report_id=?
            """,
            (content_json, content_md, updated_at, report_id),
        )
        conn.commit()


def get_report(report_id: str) -> dict[str, Any] | None:
    conn = get_conn()
    r = conn.execute("SELECT * FROM reports WHERE report_id=?", (report_id,)).fetchone()
    return dict(r) if r else None


def list_reports(student_id: str, limit: int = 20) -> list[dict[str, Any]]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT report_id, student_id, version, created_at, updated_at FROM reports WHERE student_id=? ORDER BY updated_at DESC LIMIT ?",
        (student_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Task queue
# ---------------------------------------------------------------------------

def create_task(task: dict[str, Any]) -> None:
    conn = get_conn()
    with _lock:
        conn.execute(
            """
            INSERT INTO tasks (task_id, task_type, payload_json, status, progress, result_json, error, created_at, updated_at)
            VALUES (:task_id, :task_type, :payload_json, :status, :progress, :result_json, :error, :created_at, :updated_at)
            """,
            task,
        )
        conn.commit()


def update_task(task_id: str, status: str | None = None, progress: float | None = None, result_json: str | None = None, error: str | None = None, updated_at: str | None = None) -> None:
    conn = get_conn()
    fields = []
    params: list[Any] = []
    if status is not None:
        fields.append("status=?")
        params.append(status)
    if progress is not None:
        fields.append("progress=?")
        params.append(progress)
    if result_json is not None:
        fields.append("result_json=?")
        params.append(result_json)
    if error is not None:
        fields.append("error=?")
        params.append(error)
    if updated_at is not None:
        fields.append("updated_at=?")
        params.append(updated_at)
    if not fields:
        return
    params.append(task_id)
    sql = f"UPDATE tasks SET {', '.join(fields)} WHERE task_id=?"
    with _lock:
        conn.execute(sql, tuple(params))
        conn.commit()


def get_task(task_id: str) -> dict[str, Any] | None:
    conn = get_conn()
    r = conn.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
    return dict(r) if r else None


def list_tasks(status: str | None = None, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    conn = get_conn()
    sql = "SELECT * FROM tasks WHERE 1=1"
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if status:
        sql += " AND status=:status"
        params["status"] = status
    sql += " ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
    rows = conn.execute(sql, params).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["payload"] = json.loads(d.get("payload_json") or "{}")
        except Exception:
            d["payload"] = {}
        try:
            d["result"] = json.loads(d.get("result_json") or "{}") if d.get("result_json") else None
        except Exception:
            d["result"] = None
        out.append(d)
    return out


def task_status_counts() -> dict[str, int]:
    conn = get_conn()
    rows = conn.execute("SELECT status, COUNT(1) AS c FROM tasks GROUP BY status").fetchall()
    return {str(r["status"]): int(r["c"]) for r in rows}


def claim_next_task(only_types: list[str] | None = None) -> dict[str, Any] | None:
    """Atomically claim next pending task.

    A simple, SQLite-friendly queue: SELECT then UPDATE within a lock.
    """

    conn = get_conn()
    with _lock:
        sql = "SELECT * FROM tasks WHERE status='PENDING'"
        params: list[Any] = []
        if only_types:
            placeholders = ",".join(["?"] * len(only_types))
            sql += f" AND task_type IN ({placeholders})"
            params.extend(only_types)
        sql += " ORDER BY created_at ASC LIMIT 1"
        r = conn.execute(sql, tuple(params)).fetchone()
        if not r:
            return None
        task_id = r["task_id"]
        # best-effort claim
        conn.execute("UPDATE tasks SET status='RUNNING' WHERE task_id=? AND status='PENDING'", (task_id,))
        conn.commit()
        return dict(r)


def requeue_running_tasks(updated_at: str) -> int:
    """Move orphan RUNNING tasks back to PENDING.

    This is mainly used for dev reload scenarios where process restarts can
    interrupt in-flight tasks and leave them in RUNNING forever.
    """

    conn = get_conn()
    with _lock:
        cur = conn.execute(
            "UPDATE tasks SET status='PENDING', updated_at=? WHERE status='RUNNING'",
            (updated_at,),
        )
        conn.commit()
        return int(cur.rowcount or 0)


def list_roles_for_job(job_id: str) -> list[str]:
    """Return role_ids that contain this job_id (usually 1)."""
    conn = get_conn()
    rows = conn.execute("SELECT role_id FROM job_role_members WHERE job_id=?", (job_id,)).fetchall()
    return [r["role_id"] for r in rows]


def clear_jobs_related() -> None:
    """Delete jobs and dependent derived data.

    Useful for re-importing official datasets during local experiments.
    """
    conn = get_conn()
    with _lock:
        conn.execute("DELETE FROM student_job_events")
        conn.execute("DELETE FROM student_job_preferences")
        conn.execute("DELETE FROM match_cache")
        conn.execute("DELETE FROM job_profiles")
        conn.execute("DELETE FROM job_role_members")
        conn.execute("DELETE FROM role_profiles")
        conn.execute("DELETE FROM job_roles")
        conn.execute("DELETE FROM jobs")
        conn.commit()




# ---------------------------------------------------------------------------
# Auth users
# ---------------------------------------------------------------------------

def create_user(user: dict[str, Any]) -> None:
    conn = get_conn()
    with _lock:
        conn.execute(
            """
            INSERT INTO users (user_id, username, password_hash, display_name, role, is_active, created_at, updated_at)
            VALUES (:user_id, :username, :password_hash, :display_name, :role, :is_active, :created_at, :updated_at)
            """,
            user,
        )
        conn.commit()


def get_user_by_username(username: str) -> dict[str, Any] | None:
    conn = get_conn()
    row = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    return dict(row) if row else None


def get_user_by_id(user_id: str) -> dict[str, Any] | None:
    conn = get_conn()
    row = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
    return dict(row) if row else None


def update_user_role(user_id: str, role: str, updated_at: str) -> None:
    conn = get_conn()
    with _lock:
        conn.execute("UPDATE users SET role=?, updated_at=? WHERE user_id=?", (role, updated_at, user_id))
        conn.commit()


def list_users(limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT user_id, username, display_name, role, is_active, created_at, updated_at FROM users ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (limit, offset),
    ).fetchall()
    return [dict(r) for r in rows]


def upsert_user(user: dict[str, Any]) -> None:
    conn = get_conn()
    with _lock:
        conn.execute(
            """
            INSERT INTO users (user_id, username, password_hash, display_name, role, is_active, created_at, updated_at)
            VALUES (:user_id, :username, :password_hash, :display_name, :role, :is_active, :created_at, :updated_at)
            ON CONFLICT(user_id) DO UPDATE SET
                username=excluded.username,
                password_hash=excluded.password_hash,
                display_name=excluded.display_name,
                role=excluded.role,
                is_active=excluded.is_active,
                updated_at=excluded.updated_at
            """,
            user,
        )
        conn.commit()


def delete_users_by_usernames(usernames: list[str]) -> int:
    names = [str(username or "").strip() for username in usernames if str(username or "").strip()]
    if not names:
        return 0
    conn = get_conn()
    placeholders = ",".join(["?"] * len(names))
    with _lock:
        cur = conn.execute(f"DELETE FROM users WHERE username IN ({placeholders})", tuple(names))
        conn.commit()
        return int(cur.rowcount or 0)


def set_user_active(user_id: str, is_active: int, updated_at: str) -> None:
    conn = get_conn()
    with _lock:
        conn.execute("UPDATE users SET is_active=?, updated_at=? WHERE user_id=?", (int(is_active), updated_at, user_id))
        conn.commit()


# ---------------------------------------------------------------------------
# Chat sessions/messages
# ---------------------------------------------------------------------------

def create_chat_session(session: dict[str, Any]) -> None:
    conn = get_conn()
    with _lock:
        conn.execute(
            """
            INSERT INTO chat_sessions (session_id, user_id, student_id, title, last_job_id, state_json, created_at, updated_at)
            VALUES (:session_id, :user_id, :student_id, :title, :last_job_id, :state_json, :created_at, :updated_at)
            """,
            session,
        )
        conn.commit()


def get_chat_session(session_id: str) -> dict[str, Any] | None:
    conn = get_conn()
    row = conn.execute("SELECT * FROM chat_sessions WHERE session_id=?", (session_id,)).fetchone()
    return dict(row) if row else None


def list_chat_sessions(
    user_id: str,
    limit: int = 50,
    offset: int = 0,
    student_id: str | None = None,
) -> list[dict[str, Any]]:
    conn = get_conn()
    sid = str(student_id or "").strip()
    if sid:
        rows = conn.execute(
            """
            SELECT session_id, user_id, student_id, title, last_job_id, created_at, updated_at
            FROM chat_sessions
            WHERE user_id=? AND student_id=?
            ORDER BY updated_at DESC
            LIMIT ? OFFSET ?
            """,
            (user_id, sid, limit, offset),
        ).fetchall()
        return [dict(r) for r in rows]

    rows = conn.execute(
        """
        SELECT session_id, user_id, student_id, title, last_job_id, created_at, updated_at
        FROM chat_sessions
        WHERE user_id=?
        ORDER BY updated_at DESC
        LIMIT ? OFFSET ?
        """,
        (user_id, limit, offset),
    ).fetchall()
    return [dict(r) for r in rows]


def update_chat_session(session_id: str, updated_at: str, title: str | None = None, last_job_id: str | None = None, state_json: str | None = None) -> None:
    conn = get_conn()
    fields = ["updated_at=?"]
    params: list[Any] = [updated_at]
    if title is not None:
        fields.append("title=?")
        params.append(title)
    if last_job_id is not None:
        fields.append("last_job_id=?")
        params.append(last_job_id)
    if state_json is not None:
        fields.append("state_json=?")
        params.append(state_json)
    params.append(session_id)
    sql = f"UPDATE chat_sessions SET {', '.join(fields)} WHERE session_id=?"
    with _lock:
        conn.execute(sql, tuple(params))
        conn.commit()


def insert_chat_message(message: dict[str, Any]) -> None:
    conn = get_conn()
    with _lock:
        conn.execute(
            """
            INSERT INTO chat_messages (message_id, session_id, user_id, role, content, meta_json, created_at)
            VALUES (:message_id, :session_id, :user_id, :role, :content, :meta_json, :created_at)
            """,
            message,
        )
        conn.commit()


def list_chat_messages(session_id: str, limit: int = 200, offset: int = 0) -> list[dict[str, Any]]:
    conn = get_conn()
    rows = conn.execute(
        """
        SELECT message_id, session_id, user_id, role, content, meta_json, created_at
        FROM chat_messages
        WHERE session_id=?
        ORDER BY created_at ASC
        LIMIT ? OFFSET ?
        """,
        (session_id, limit, offset),
    ).fetchall()
    out = []
    for r in rows:
        item = dict(r)
        try:
            item["meta"] = json.loads(item.get("meta_json") or "{}")
        except Exception:
            item["meta"] = {}
        out.append(item)
    return out


def delete_chat_messages(session_id: str) -> int:
    conn = get_conn()
    with _lock:
        cur = conn.execute("DELETE FROM chat_messages WHERE session_id=?", (session_id,))
        conn.commit()
        return int(cur.rowcount or 0)


def delete_chat_session(session_id: str) -> int:
    conn = get_conn()
    with _lock:
        conn.execute("DELETE FROM chat_messages WHERE session_id=?", (session_id,))
        cur = conn.execute("DELETE FROM chat_sessions WHERE session_id=?", (session_id,))
        conn.commit()
        return int(cur.rowcount or 0)


# ---------------------------------------------------------------------------
# System settings
# ---------------------------------------------------------------------------

def upsert_system_setting(setting_key: str, setting_json: str, updated_at: str) -> None:
    conn = get_conn()
    with _lock:
        conn.execute(
            """
            INSERT INTO system_settings (setting_key, setting_json, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(setting_key) DO UPDATE SET setting_json=excluded.setting_json, updated_at=excluded.updated_at
            """,
            (setting_key, setting_json, updated_at),
        )
        conn.commit()


def get_system_setting(setting_key: str) -> dict[str, Any] | None:
    conn = get_conn()
    r = conn.execute("SELECT setting_json, updated_at FROM system_settings WHERE setting_key=?", (setting_key,)).fetchone()
    if not r:
        return None
    try:
        value = json.loads(r["setting_json"])
    except Exception:
        value = r["setting_json"]
    return {"setting_key": setting_key, "value": value, "updated_at": r["updated_at"]}


def list_system_settings(limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT setting_key, setting_json, updated_at FROM system_settings ORDER BY updated_at DESC LIMIT ? OFFSET ?",
        (limit, offset),
    ).fetchall()
    out = []
    for r in rows:
        try:
            value = json.loads(r["setting_json"])
        except Exception:
            value = r["setting_json"]
        out.append({"setting_key": r["setting_key"], "value": value, "updated_at": r["updated_at"]})
    return out
