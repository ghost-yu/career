from __future__ import annotations

import base64
import hashlib
import hmac
import io
from pathlib import Path
import secrets
import time

from PIL import Image, ImageDraw, ImageFont

from app.core.config import settings
from app.db import sqlite as db

CAPTCHA_TTL = 300
LETTERS = "ABCDEFGHJKLMNPQRSTUVWXYZ"


def _digest(captcha_id: str, answer: str) -> str:
    return hmac.new(
        settings.auth_jwt_secret.encode(),
        f"registration:{captcha_id}:{answer}".encode(),
        hashlib.sha256,
    ).hexdigest()


def _font() -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
    ):
        if Path(path).is_file():
            return ImageFont.truetype(path, 30)
    return ImageFont.load_default(size=30)


def issue_captcha() -> dict:
    code = "".join(secrets.choice(LETTERS) for _ in range(4))
    captcha_id = secrets.token_urlsafe(24)
    image = Image.new("RGB", (144, 48), "#f3f6fa")
    draw = ImageDraw.Draw(image)
    for _ in range(5):
        draw.line([(secrets.randbelow(144), secrets.randbelow(48)),
                   (secrets.randbelow(144), secrets.randbelow(48))], fill="#b8c8dd", width=1)
    font = _font()
    for i, letter in enumerate(code):
        draw.text((12 + i * 31, 4 + secrets.randbelow(5)), letter, font=font, fill="#243e60")
    for _ in range(65):
        draw.point((secrets.randbelow(144), secrets.randbelow(48)), fill="#849bb8")
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    now = int(time.time())
    conn = db.get_conn()
    with conn:
        conn.execute("DELETE FROM registration_captchas WHERE expires_at <= ?", (now,))
        conn.execute(
            "INSERT INTO registration_captchas (captcha_id, answer_hash, expires_at) VALUES (?, ?, ?)",
            (captcha_id, _digest(captcha_id, code), now + CAPTCHA_TTL),
        )
    return {"captcha_id": captcha_id, "image": "data:image/png;base64," + base64.b64encode(stream.getvalue()).decode(),
            "expires_in": CAPTCHA_TTL}


def consume_captcha(captcha_id: str, answer: str) -> str | None:
    """Consume every attempt atomically; a challenge can never be replayed."""
    if not captcha_id or len(captcha_id) > 64:
        return "captcha_required"
    conn = db.get_conn()
    with conn:
        row = conn.execute(
            "SELECT answer_hash, expires_at FROM registration_captchas WHERE captcha_id=?", (captcha_id,),
        ).fetchone()
        deleted = conn.execute("DELETE FROM registration_captchas WHERE captcha_id=?", (captcha_id,)).rowcount
    if not row or deleted != 1:
        return "captcha_invalid"
    if row["expires_at"] <= int(time.time()):
        return "captcha_expired"
    normalized = answer.strip().upper()
    if len(normalized) != 4 or not hmac.compare_digest(row["answer_hash"], _digest(captcha_id, normalized)):
        return "captcha_invalid"
    return None
