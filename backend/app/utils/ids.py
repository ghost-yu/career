from __future__ import annotations

import secrets
import string
from datetime import datetime, timezone


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def gen_id(prefix: str, n: int = 12) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return f"{prefix}_" + "".join(secrets.choice(alphabet) for _ in range(n))
