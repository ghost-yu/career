from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


_BASE_DIR = Path(__file__).resolve().parents[2]
_REPO_ROOT = _BASE_DIR.parent
_DEFAULT_DATA_DIR = _BASE_DIR / "data"
_DEFAULT_KB_DIR = _REPO_ROOT / "knowledge_base"
_DEFAULT_LOG_DIR = _DEFAULT_DATA_DIR / "logs"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(_REPO_ROOT / ".env"), str(_BASE_DIR / ".env"), ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "明杉科技精准就业平台"
    env: str = "dev"
    host: str = "0.0.0.0"
    port: int = 8000

    data_dir: str = str(_DEFAULT_DATA_DIR)
    sqlite_path: str = str(_DEFAULT_DATA_DIR / "app.db")
    upload_dir: str = str(_DEFAULT_DATA_DIR / "uploads")
    log_dir: str = str(_DEFAULT_LOG_DIR)
    app_log_path: str = str(_DEFAULT_LOG_DIR / "app.log")
    llm_audit_log_path: str = str(_DEFAULT_LOG_DIR / "llm_audit.log")

    kb_dir: str = str(_DEFAULT_KB_DIR)
    kb_vector_index_path: str = str(_DEFAULT_DATA_DIR / "kb_vectors.pkl")

    llm_provider: str = "zhipu"
    openai_api_key: str | None = None
    openai_base_url: str | None = "https://open.bigmodel.cn/api/paas/v4"
    openai_model: str = "glm-4.5-air"
    zhipu_api_key: str | None = None
    zai_api_key: str | None = None
    deepseek_api_key: str | None = None
    qwen_api_key: str | None = None
    ark_api_key: str | None = None

    auth_jwt_secret: str = "change-me-in-production"
    auth_jwt_expire_minutes: int = 60 * 24 * 7
    auth_cookie_name: str = "career_access_token"
    auth_cookie_secure: bool = False
    auth_cookie_samesite: str = "lax"

    graph_backend: str = "memory"
    neo4j_uri: str = "bolt://neo4j:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "neo4j"

    vector_backend: str = "tfidf"
    job_vector_index_path: str = str(_DEFAULT_DATA_DIR / "job_vectors.pkl")
    role_vector_index_path: str = str(_DEFAULT_DATA_DIR / "role_vectors.pkl")

    worker_poll_seconds: float = 1.0
    inline_worker_enabled: bool = True
    inline_worker_join_timeout_seconds: float = 5.0
    job_profile_bulk_workers: int = 4
    job_profile_bulk_workers_max: int = 16
    match_model_prewarm_enabled: bool = True
    match_model_prewarm_build_index: bool = True
    match_model_prewarm_max_jobs: int = 20000

    cors_allow_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    frontend_app_url: str = "http://localhost:5173"


settings = Settings()
