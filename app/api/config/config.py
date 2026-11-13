from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


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
    llm_max_workers: int = 2
    llm_max_retries: int = 2
    llm_timeout_seconds: int = 300
    llm_max_tokens: int = 4096
    paragraphs_per_chunk: int = 16

    # OCR for scanned PDFs (default off)
    ocr_enabled: bool = False
    ocr_languages: str = "eng"

    # Upload limits
    max_upload_mb: int = 50

    # Logging
    log_level: str = "INFO"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ------------------------------------------------------------------ paths
    @property
    def database_path(self) -> Path:
        return Path(self.data_dir) / "review.db"

    @property
    def documents_dir(self) -> Path:
        return Path(self.data_dir) / "documents"

    @property
    def log_file(self) -> Path:
        return Path(self.data_dir) / "logs" / "app.log"

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
