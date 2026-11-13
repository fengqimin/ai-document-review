from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Repository root (app/api/config/config.py -> app/api -> app -> repo)
REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Local deployment settings (replaces the Azure App Service configuration).

    All state lives under DATA_DIR: review.db (SQLite) + documents/ (PDFs).
    LLM access is via any OpenAI-compatible endpoint: base URL + API key + model.
    """

    debug: bool = False

    # Local data layout
    data_dir: str = "data"

    # Table names (kept for interface compatibility with the old Cosmos config)
    issues_container: str = "issues"

    # Static UI hosting
    serve_static: bool = True
    static_dir: str = "www"

    # CORS: explicit whitelist (never "*" together with credentials)
    cors_origins: str = (
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:8000,http://127.0.0.1:8000"
    )

    # Authentication: local accounts + JWT
    auth_disabled: bool = False
    jwt_secret: str = "change-me-before-exposing-this-service"
    jwt_expire_minutes: int = 480
    admin_username: str = "admin"
    admin_password: str = "admin123"

    # OpenAI-compatible LLM endpoint (required for review; empty -> degraded health)
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    llm_strict_json: bool = True
    llm_shots: int = 5
    # Mirrors PipelineConfig: global cap on concurrent LLM requests per review,
    # and how many chunks are kept in flight (output order is unchanged).
    llm_max_workers: int = 8
    chunk_max_workers: int = 2
    llm_max_retries: int = 2
    llm_timeout_seconds: int = 300
    llm_max_tokens: int = 8192
    consolidator_batch_size: int = 10
    paragraphs_per_chunk: int = 16

    # OCR for scanned PDFs (default off)
    ocr_enabled: bool = False
    ocr_languages: str = "eng"

    # Upload limits
    max_upload_mb: int = 50

    # Logging
    log_level: str = "INFO"

    model_config = SettingsConfigDict(
        # Resolve .env from the repo root so the app behaves the same whether
        # uvicorn is started from the repo root, from app/api (task dev) or
        # from /app/app/api inside the container. A .env in the CWD still wins.
        env_file=(REPO_ROOT / ".env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ------------------------------------------------------------------ paths
    @property
    def data_root(self) -> Path:
        """Absolute data directory.

        A relative DATA_DIR resolves against the repo root rather than the
        process CWD: otherwise the same config would write to app/api/data or
        /app/app/api/data depending on how the process was started.
        """
        path = Path(self.data_dir).expanduser()
        return path if path.is_absolute() else REPO_ROOT / path

    @property
    def database_path(self) -> Path:
        return self.data_root / "review.db"

    @property
    def documents_dir(self) -> Path:
        return self.data_root / "documents"

    @property
    def log_file(self) -> Path:
        return self.data_root / "logs" / "app.log"

    # ------------------------------------------------------------------ misc
    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def llm_configured(self) -> bool:
        return bool(self.llm_base_url and self.llm_api_key and self.llm_model)

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


settings = Settings()
