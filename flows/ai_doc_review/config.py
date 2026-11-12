"""Pipeline configuration, read from environment (same names as the API
settings, so a single .env drives both). Kept independent from the API package
so the pipeline can also run standalone."""

import os


def _get_bool(name: str, default: bool) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes")


def _get_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


class PipelineConfig:
    """Runtime configuration for the review pipeline (OpenAI-compatible LLM)."""

    def __init__(self) -> None:
        self.llm_base_url: str = os.environ.get("LLM_BASE_URL", "")
        self.llm_api_key: str = os.environ.get("LLM_API_KEY", "")
        self.llm_model: str = os.environ.get("LLM_MODEL", "")
        self.llm_strict_json: bool = _get_bool("LLM_STRICT_JSON", True)
        self.llm_shots: int = _get_int("LLM_SHOTS", 5)
        self.llm_max_workers: int = _get_int("LLM_MAX_WORKERS", 2)
        self.llm_max_retries: int = _get_int("LLM_MAX_RETRIES", 2)
        self.llm_timeout_seconds: int = _get_int("LLM_TIMEOUT_SECONDS", 300)
        self.llm_max_tokens: int = _get_int("LLM_MAX_TOKENS", 4096)
        self.paragraphs_per_chunk: int = _get_int("PARAGRAPHS_PER_CHUNK", 16)

        # Transient (429/5xx/timeout) retries: exponential backoff, kept
        # separate from JSON-validation retries (llm_max_retries).
        self.llm_transient_retries: int = _get_int("LLM_TRANSIENT_RETRIES", 5)

        self.ocr_enabled: bool = _get_bool("OCR_ENABLED", False)
        self.ocr_languages: str = os.environ.get("OCR_LANGUAGES", "eng")

    @property
    def llm_configured(self) -> bool:
        return bool(self.llm_base_url and self.llm_api_key and self.llm_model)
