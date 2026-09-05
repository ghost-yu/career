from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.core.auth import (
    ROLE_STUDENT,
    clear_auth_cookie,
    create_access_token,
    get_current_user,
    get_current_user_optional,
    hash_password,
    normalize_role,
    set_auth_cookie,
    verify_password,
)
from app.db import sqlite as db
from app.services.registration_captcha import consume_captcha, issue_captcha
from app.utils.ids import gen_id, now_iso

router = APIRouter()


LOGIN_USERNAME_ALIASES: dict[str, str] = {}


def _safe_user_view(user: dict) -> dict:
    return {
        "user_id": user.get("user_id"),
        "username": user.get("username"),
        "display_name": user.get("display_name"),
        "role": normalize_role(user.get("role")),
        "is_active": bool(int(user.get("is_active") or 0)),
        "created_at": user.get("created_at"),
        "updated_at": user.get("updated_at"),
    }


@router.get("/captcha")
def captcha(response: Response) -> dict:
    response.headers["Cache-Control"] = "no-store"
    return issue_captcha()


@router.post("/register")
def register(body: dict, response: Response) -> dict:
    username = str(body.get("username") or "").strip().lower()
    password = str(body.get("password") or "")
    display_name = str(body.get("display_name") or "").strip() or None

    if len(username) < 3:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="username_too_short")
    if len(password) < 6:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="password_too_short")
    captcha_error = consume_captcha(str(body.get("captcha_id") or ""), str(body.get("captcha") or ""))
    if captcha_error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=captcha_error)
    if db.get_user_by_username(username):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="username_exists")

    ts = now_iso()
    user = {
        "user_id": gen_id("U", 12),
        "username": username,
        "password_hash": hash_password(password),
        "display_name": display_name,
        "role": ROLE_STUDENT,
        "is_active": 1,
        "created_at": ts,
        "updated_at": ts,
    }
    try:
        db.create_user(user)
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="username_exists") from None
    token = create_access_token(user_id=user["user_id"], username=username)
    set_auth_cookie(response, token)
    return {"ok": True, "user": _safe_user_view(user)}


@router.post("/login")
def login(body: dict, response: Response) -> dict:
    username_raw = str(body.get("username") or "").strip()
    username = username_raw.lower()
    password = str(body.get("password") or "")

    candidate_usernames = [username]
    alias_target = LOGIN_USERNAME_ALIASES.get(username_raw)
    if alias_target:
        alias_lower = alias_target.strip().lower()
        if alias_lower and alias_lower not in candidate_usernames:
            candidate_usernames.append(alias_lower)

    matched_user = None
    for candidate in candidate_usernames:
        user = db.get_user_by_username(candidate)
        if user and verify_password(password, str(user.get("password_hash") or "")):
            matched_user = user
            break

    if not matched_user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_credentials")

    if not int(matched_user.get("is_active") or 0):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="user_disabled")

    token = create_access_token(user_id=str(matched_user["user_id"]), username=str(matched_user.get("username") or username))
    set_auth_cookie(response, token)
    return {"ok": True, "user": _safe_user_view(matched_user)}


@router.post("/logout")
def logout(response: Response) -> dict:
    clear_auth_cookie(response)
    return {"ok": True}


@router.get("/me")
def me(user: dict | None = Depends(get_current_user_optional)) -> dict:
    if not user:
        return {"ok": True, "user": None}
    return {"ok": True, "user": _safe_user_view(user)}
