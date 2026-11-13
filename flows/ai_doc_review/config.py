"""Pipeline configuration.

Reads the same environment variables and the same .env files as the API
settings, so a single .env drives both. Importable standalone: this module does
not depend on the API package, so the pipeline can also run from a script.

A plain `os.environ` lookup is not enough here: pydantic-settings loads .env
into the Settings model without exporting it to the process environment, so a
review triggered by the API would see an empty configuration and refuse to run
even though /api/health reported `llm_configured: true`.
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Repository root: flows/ai_doc_review/config.py -> flows -> repo
REPO_ROOT = Path(__file__).resolve().parents[2]


class PipelineConfig(BaseSettings):
    """Runtime configuration for the review pipeline (OpenAI-compatible LLM)."""

    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM endpoint (vendor neutral)
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    llm_strict_json: bool = True
    llm_shots: int = 5
    # Global cap on concurrent LLM HTTP requests for one review run. Shots of
    # both dimensions and all in-flight chunks share this budget.
    llm_max_workers: int = 8
    # Chunks kept in flight (bounded look-ahead); output order is unchanged.
    chunk_max_workers: int = 2
    llm_max_retries: int = 2
    llm_timeout_seconds: int = 300
    # A verdict is verbose (reason + score + action): ~400 completion tokens
    # per issue. 4096 truncated a 5-issue consolidator call mid-JSON on a real
    # endpoint, so the budget is doubled and consolidator input is batched.
    llm_max_tokens: int = 8192
    consolidator_batch_size: int = 10

    # Transient (429/5xx/timeout) retries: exponential backoff, kept separate
    # from JSON-validation retries (llm_max_retries).
    llm_transient_retries: int = 5

    # Chunking / extraction
    paragraphs_per_chunk: int = 16
    ocr_enabled: bool = False
    ocr_languages: str = "eng"

    @property
    def llm_configured(self) -> bool:
        return bool(self.llm_base_url and self.llm_api_key and self.llm_model)
