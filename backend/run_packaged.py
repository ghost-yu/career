from __future__ import annotations

import os
import shutil
import sys
import threading
import time
import webbrowser
from pathlib import Path


def _runtime_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def _set_default_runtime_env() -> tuple[str, int, str]:
    base_dir = _runtime_base_dir()
    runtime_root = Path(os.getenv("APP_WORKDIR", str(base_dir / "runtime"))).resolve()
    data_dir = runtime_root / "data"
    log_dir = data_dir / "logs"
    upload_dir = data_dir / "uploads"

    log_dir.mkdir(parents=True, exist_ok=True)
    upload_dir.mkdir(parents=True, exist_ok=True)

    os.environ.setdefault("ENV", "prod")
    os.environ.setdefault("DATA_DIR", str(data_dir))
    os.environ.setdefault("SQLITE_PATH", str(data_dir / "app.db"))
    os.environ.setdefault("UPLOAD_DIR", str(upload_dir))
    os.environ.setdefault("LOG_DIR", str(log_dir))
    os.environ.setdefault("APP_LOG_PATH", str(log_dir / "app.log"))
    os.environ.setdefault("LLM_AUDIT_LOG_PATH", str(log_dir / "llm_audit.log"))
    os.environ.setdefault("KB_VECTOR_INDEX_PATH", str(data_dir / "kb_vectors.pkl"))
    os.environ.setdefault("JOB_VECTOR_INDEX_PATH", str(data_dir / "job_vectors.pkl"))
    os.environ.setdefault("ROLE_VECTOR_INDEX_PATH", str(data_dir / "role_vectors.pkl"))

    # Default to same-origin API access for packaged mode.
    os.environ.setdefault("CORS_ALLOW_ORIGINS", "http://127.0.0.1:8000,http://localhost:8000")
    os.environ.setdefault("FRONTEND_APP_URL", "http://127.0.0.1:8000")

    host = str(os.getenv("APP_HOST", "127.0.0.1")).strip() or "127.0.0.1"
    port = int(str(os.getenv("APP_PORT", "8000")).strip() or "8000")
    browser_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    return host, port, browser_host


def _seed_runtime_data_if_needed() -> None:
    data_dir = Path(os.environ["DATA_DIR"]).resolve()
    base_dir = _runtime_base_dir()

    def _copy_missing_tree(src: Path, dst: Path) -> None:
        for path in src.rglob("*"):
            relative = path.relative_to(src)
            target = dst / relative
            if path.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)

    candidates: list[Path] = []

    # Prefer legacy on-disk data near exe if present.
    candidates.append(base_dir / "data")
    candidates.append(base_dir / "backend" / "data")

    # Fallback to bundled seed data in onefile extraction dir.
    if getattr(sys, "frozen", False):
        meipass = Path(getattr(sys, "_MEIPASS", ""))
        if str(meipass):
            candidates.append(meipass / "seed_data")

    data_dir.mkdir(parents=True, exist_ok=True)
    for src_dir in candidates:
        if not src_dir.exists() or not src_dir.is_dir():
            continue
        if src_dir.resolve() == data_dir:
            continue
        _copy_missing_tree(src_dir, data_dir)


def _should_open_browser() -> bool:
    value = str(os.getenv("AUTO_OPEN_BROWSER", "1")).strip().lower()
    return value not in {"0", "false", "no", "off"}


def main() -> None:
    host, port, browser_host = _set_default_runtime_env()
    _seed_runtime_data_if_needed()

    # Import after environment defaults are set.
    import uvicorn
    from app.main import app

    if _should_open_browser():
        def _open() -> None:
            time.sleep(1.2)
            webbrowser.open(f"http://{browser_host}:{port}")

        threading.Thread(target=_open, daemon=True).start()

    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
