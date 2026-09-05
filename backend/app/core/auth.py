from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any

from fastapi import Depends, HTTPException, Request, Response, status

from app.core.config import settings
from app.db import sqlite as db
from app.utils.ids import gen_id, now_iso

ROLE_ADMIN = "admin"
ROLE_OPERATOR = "operator"
ROLE_VIEWER = "viewer"
ROLE_STUDENT = "student"
VALID_ROLES = {ROLE_ADMIN, ROLE_OPERATOR, ROLE_VIEWER, ROLE_STUDENT}

WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
ADMIN_ONLY_RULES: list[tuple[str, str]] = [
    ("POST", "/jobs/ingest"),
    ("POST", "/jobs/ingest_file"),
    ("POST", "/jobs/profiles/bulk_generate"),
    ("POST", "/jobs/index/build"),
    ("POST", "/jobs/pipeline/full_rebuild"),
    ("POST", "/roles/rebuild"),
    ("POST", "/roles/index/build"),
    ("POST", "/graph/rebuild"),
    ("POST", "/graph/role/rebuild"),
    ("POST", "/kb/rebuild"),
    ("POST", "/kb/rebuild_task"),
    ("POST", "/kb/materialize"),
    ("POST", "/kb/materialize_task"),
    ("POST", "/students/seed_synthetic"),
    ("POST", "/students/batch/import_competition_resumes"),
    ("POST", "/jobs/profiles/import_ai"),
]

PRESET_USERS: list[dict[str, str]] = [
    {"username": "awe", "display_name": "管理员 awe", "role": ROLE_ADMIN, "password": "123"},
    {"username": "qwr", "display_name": "管理员 qwr", "role": ROLE_ADMIN, "password": "145"},
    {"username": "weu", "display_name": "管理员 weu", "role": ROLE_ADMIN, "password": "283"},
]

LEGACY_PRESET_USERNAMES = {
    "admin",
    "operator01",
    "viewer01",
    "管理员",
    "就业老师",
    "展示账号",
}


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")


def _b64url_decode(raw: str) -> bytes:
    pad = "=" * (-len(raw) % 4)
    return base64.urlsafe_b64decode((raw + pad).encode("utf-8"))


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120_000)
    return f"pbkdf2_sha256${_b64url_encode(salt)}${_b64url_encode(digest)}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algo, salt_b64, digest_b64 = password_hash.split("$", 2)
        if algo != "pbkdf2_sha256":
            return False
        salt = _b64url_decode(salt_b64)
        expected = _b64url_decode(digest_b64)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120_000)
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def create_access_token(user_id: str, username: str) -> str:
    now = int(time.time())
    exp = now + int(settings.auth_jwt_expire_minutes * 60)
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {"sub": user_id, "username": username, "iat": now, "exp": exp}
    head = _b64url_encode(json.dumps(header, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    body = _b64url_encode(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    signing_input = f"{head}.{body}".encode("utf-8")
    signature = hmac.new(settings.auth_jwt_secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    sign = _b64url_encode(signature)
    return f"{head}.{body}.{sign}"


def decode_access_token(token: str) -> dict[str, Any] | None:
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        head, body, sign = parts
        signing_input = f"{head}.{body}".encode("utf-8")
        expected = hmac.new(settings.auth_jwt_secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
        if not hmac.compare_digest(_b64url_encode(expected), sign):
            return None
        payload = json.loads(_b64url_decode(body).decode("utf-8"))
        if int(payload.get("exp") or 0) < int(time.time()):
            return None
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def set_auth_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=token,
        httponly=True,
        secure=bool(settings.auth_cookie_secure),
        samesite=str(settings.auth_cookie_samesite or "lax"),
        max_age=int(settings.auth_jwt_expire_minutes * 60),
        path="/",
    )


def clear_auth_cookie(response: Response) -> None:
    response.delete_cookie(key=settings.auth_cookie_name, path="/")


def normalize_role(raw: Any) -> str:
    role = str(raw or "").strip().lower()
    if role in VALID_ROLES:
        return role
    return ROLE_VIEWER


def ensure_preset_users() -> dict[str, int]:
    created = 0
    role_updated = 0
    removed = db.delete_users_by_usernames(sorted(LEGACY_PRESET_USERNAMES))

    for item in PRESET_USERS:
        username = item["username"]
        role = item["role"]
        exists = db.get_user_by_username(username)
        if exists:
            current_role = normalize_role(exists.get("role"))
            password_matches = verify_password(item["password"], str(exists.get("password_hash") or ""))
            if current_role != role:
                db.update_user_role(str(exists["user_id"]), role=role, updated_at=now_iso())
                role_updated += 1
            if (
                not password_matches
                or str(exists.get("display_name") or "") != item["display_name"]
                or int(exists.get("is_active") or 0) != 1
            ):
                ts = now_iso()
                db.upsert_user(
                    {
                        "user_id": exists["user_id"],
                        "username": username,
                        "password_hash": hash_password(item["password"]),
                        "display_name": item["display_name"],
                        "role": role,
                        "is_active": 1,
                        "created_at": exists.get("created_at") or ts,
                        "updated_at": ts,
                    }
                )
            continue
        ts = now_iso()
        db.create_user(
            {
                "user_id": gen_id("U", 12),
                "username": username,
                "password_hash": hash_password(item["password"]),
                "display_name": item["display_name"],
                "role": role,
                "is_active": 1,
                "created_at": ts,
                "updated_at": ts,
            }
        )
        created += 1
    return {"created": created, "role_updated": role_updated, "removed": removed}


def get_current_user_optional(request: Request) -> dict[str, Any] | None:
    token = request.cookies.get(settings.auth_cookie_name)
    if not token:
        auth_header = str(request.headers.get("authorization") or "").strip()
        if auth_header.lower().startswith("bearer "):
            token = auth_header[7:].strip()
    if not token:
        return None
    payload = decode_access_token(token)
    if not payload:
        return None
    user_id = str(payload.get("sub") or "").strip()
    if not user_id:
        return None
    user = db.get_user_by_id(user_id)
    if not user or not int(user.get("is_active") or 0):
        return None
    user["role"] = normalize_role(user.get("role"))
    return user


def get_current_user(request: Request) -> dict[str, Any]:
    user = get_current_user_optional(request)
    if user:
        return user
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized")


def _is_admin_only_path(method: str, path: str) -> bool:
    if path.startswith("/admin"):
        return True
    if method == "POST" and path.startswith("/jobs/") and path.endswith("/profile/generate"):
        return True
    return any(m == method and p == path for m, p in ADMIN_ONLY_RULES)


def _ensure_can_write(user: dict[str, Any]) -> None:
    role = normalize_role(user.get("role"))
    if role not in {ROLE_ADMIN, ROLE_OPERATOR}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="write_forbidden")


def require_admin_user(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    if normalize_role(user.get("role")) != ROLE_ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin_required")
    return user


def require_operator_user(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    _ensure_can_write(user)
    return user


async def require_route_access(request: Request, user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    method = str(request.method or "").upper()
    path = request.url.path

    if _is_admin_only_path(method, path):
        if normalize_role(user.get("role")) != ROLE_ADMIN:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin_required")
        return user

    if normalize_role(user.get("role")) == ROLE_STUDENT:
        from app.core.personal_access import enforce_personal_access
        await enforce_personal_access(request, user)
        return user

    if method in WRITE_METHODS:
        _ensure_can_write(user)
    return user
