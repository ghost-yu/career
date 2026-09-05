"""Account ownership checks run before any personal-data route handler."""
from __future__ import annotations

import re
import sqlite3
from typing import Any

from fastapi import HTTPException, Request

from app.db import sqlite as db
from app.utils.ids import now_iso


def owned_student_id(user: dict[str, Any]) -> str | None:
    row = db.get_conn().execute(
        "SELECT student_id FROM student_owners WHERE user_id=?", (user['user_id'],)
    ).fetchone()
    return str(row['student_id']) if row else None


def require_owned_student(user: dict[str, Any], student_id: Any) -> None:
    if not student_id or str(student_id) != owned_student_id(user):
        # Do not disclose whether a guessed identifier exists.
        raise HTTPException(status_code=403, detail='profile_forbidden')


def create_personal_student(user: dict[str, Any], student_id: str, name: str | None) -> None:
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,96}', student_id):
        raise HTTPException(status_code=400, detail='invalid_student_id')
    conn = db.get_conn()
    try:
        # The transaction and UNIQUE(user_id) also enforce the limit under concurrent requests.
        conn.execute('BEGIN IMMEDIATE')
        if conn.execute('SELECT 1 FROM student_owners WHERE user_id=?', (user['user_id'],)).fetchone():
            raise HTTPException(status_code=409, detail='personal_profile_limit')
        if conn.execute('SELECT 1 FROM students WHERE student_id=?', (student_id,)).fetchone():
            raise HTTPException(status_code=409, detail='student_id_already_exists')
        ts = now_iso()
        conn.execute('INSERT INTO students(student_id,name,created_at) VALUES(?,?,?)', (student_id, name, ts))
        conn.execute('INSERT INTO student_owners(student_id,user_id,created_at) VALUES(?,?,?)', (student_id, user['user_id'], ts))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()
        raise HTTPException(status_code=409, detail='personal_profile_limit') from None
    except Exception:
        conn.rollback()
        raise


def _check_references(user: dict[str, Any], value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key == 'student_id' and item not in (None, ''):
                require_owned_student(user, item)
            elif key == 'student_ids' and isinstance(item, list):
                for sid in item:
                    require_owned_student(user, sid)
            elif key == 'report_id' and item not in (None, ''):
                report = db.get_report(str(item))
                require_owned_student(user, (report or {}).get('student_id'))
            _check_references(user, item)
    elif isinstance(value, list):
        for item in value:
            _check_references(user, item)


async def enforce_personal_access(request: Request, user: dict[str, Any]) -> None:
    path, method = request.url.path.rstrip('/'), request.method.upper()
    body: dict[str, Any] = {}
    if 'application/json' in request.headers.get('content-type', '').lower():
        try:
            parsed = await request.json()
            if isinstance(parsed, dict):
                body = parsed
        except ValueError:
            raise HTTPException(status_code=400, detail='invalid_json') from None

    # Creation claims only a new identifier, in a transaction in the handler.
    if path == '/students' and method == 'POST':
        return

    _check_references(user, dict(request.path_params))
    _check_references(user, dict(request.query_params))
    _check_references(user, body)

    if path.startswith('/chat'):
        session_id = request.path_params.get('session_id') or body.get('session_id')
        if session_id:
            session = db.get_chat_session(str(session_id))
            if session:
                if session.get('user_id') != user['user_id']:
                    raise HTTPException(status_code=403, detail='session_forbidden')
                require_owned_student(user, session.get('student_id'))
                if body.get('student_id') and body['student_id'] != session.get('student_id'):
                    raise HTTPException(status_code=403, detail='session_forbidden')
            elif 'session_id' in request.path_params:
                raise HTTPException(status_code=404, detail='session_not_found')

    if path.startswith('/interview/face/'):
        supplied = body.get('userId') or body.get('user_id')
        if supplied != user['user_id']:
            raise HTTPException(status_code=403, detail='face_owner_required')

    if method == 'GET':
        if path.startswith(('/jobs', '/roles', '/graph', '/insights', '/kb', '/students', '/reports', '/chat', '/match')):
            return
    elif method in {'POST', 'PUT', 'DELETE', 'PATCH'}:
        sid = request.path_params.get('student_id') or body.get('student_id')
        if path.startswith('/students/') and '/batch/' not in path and sid:
            require_owned_student(user, sid)
            return
        if path.startswith(('/match/', '/chat')) and sid:
            require_owned_student(user, sid)
            return
        if path.startswith('/chat/sessions/') and request.path_params.get('session_id'):
            return  # Session ownership was checked above.
        if path.startswith('/reports/') and (sid or request.path_params.get('report_id')):
            if sid:
                require_owned_student(user, sid)
            return
        if path.startswith('/interview/'):
            if path.startswith(('/interview/face/', '/interview/speech/')):
                return
            if sid:
                require_owned_student(user, sid)
                return
    raise HTTPException(status_code=403, detail='personal_route_forbidden')
