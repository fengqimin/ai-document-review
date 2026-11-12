"""OpenAI-compatible LLM client (replaces PromptFlow typed_llm +
AzureOpenAIConnection).

- Vendor-neutral: only base_url / api_key / model, so OpenAI, DeepSeek, Qwen
  (compatibility mode), Moonshot or an intranet vLLM/SGLang endpoint all work
  without code changes.
- Structured output: json_schema response_format preferred; automatic
  fallback to json_object + schema injection when the endpoint rejects it.
- Retries: transient errors (429/5xx/timeout/connection) use exponential
  backoff with jitter, counted separately from JSON-validation retries.
- Usage: token counts are logged per call (never prompt bodies or keys)."""

import json
import logging
import random
import time
from typing import Type, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

logging = logging.getLogger(__name__)

# HTTP statuses / errors considered transient and retried with backoff.
_TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}


class LLMError(Exception):
    """Raised when the model output cannot be validated after all retries."""


class LLMClient:
    def __init__(self, config) -> None:
        from openai import OpenAI

        self.config = config
        self.client = OpenAI(
            base_url=config.llm_base_url,
            api_key=config.llm_api_key,
            timeout=config.llm_timeout_seconds,
            max_retries=0,  # SDK retries disabled; we own the backoff policy
        )
        self._schema_fallback = False  # flips to True after a json_schema rejection
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0

    # --------------------------------------------------------------- helpers
    def _response_format(self, response_model: Type[T]) -> dict:
        """response_format payload for the current fallback state."""
        if self.config.llm_strict_json and not self._schema_fallback:
            return {
                "type": "json_schema",
                "json_schema": {
                    "name": response_model.__name__,
                    "schema": response_model.model_json_schema(),
                    "strict": False,
                },
            }
        return {"type": "json_object"}

    def _schema_hint(self, response_model: Type[T]) -> str:
        """Schema description injected into the system prompt for json_object
        mode (and plain mode), so the model knows the expected structure."""
        return (
            "Respond with a single JSON object that validates against this JSON "
            f"schema:\n{json.dumps(response_model.model_json_schema())}"
        )

    def _is_transient(self, exc: Exception) -> bool:
        status = getattr(exc, "status_code", None)
        if status in _TRANSIENT_STATUS_CODES:
            return True
        name = type(exc).__name__
        return name in ("APIConnectionError", "APITimeoutError", "Timeout", "ConnectionError")

    def _call_with_backoff(self, **kwargs):
        """Chat completion with exponential backoff + jitter on transient errors."""
        attempts = self.config.llm_transient_retries + 1
        delay = 1.0
        last_exc = None
        for attempt in range(attempts):
            try:
                return self.client.chat.completions.create(**kwargs)
            except Exception as exc:
                if not self._is_transient(exc) or attempt == attempts - 1:
                    raise
                last_exc = exc
                sleep_for = delay + random.uniform(0, 0.5)
                logging.warning(
                    f"Transient LLM error ({type(exc).__name__}), "
                    f"retry {attempt + 1}/{attempts - 1} in {sleep_for:.1f}s"
                )
                time.sleep(sleep_for)
                delay = min(delay * 2, 30)
        raise last_exc  # pragma: no cover

    def _extract_json(self, content: str) -> dict:
        """Parse JSON from model output, tolerating markdown fences."""
        text = content.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:]
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start, end = text.find("{"), text.rfind("}")
            if start >= 0 and end > start:
                return json.loads(text[start:end + 1])
            raise

    # ------------------------------------------------------------- public API
    def complete_json(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: Type[T],
        temperature: float = 1.0,
    ) -> T:
        """Request a structured response and validate it with Pydantic.

        JSON-validation failures are retried up to llm_max_retries times with a
        corrective message; unsupported response_format degrades json_schema ->
        json_object automatically.
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        for validation_attempt in range(self.config.llm_max_retries + 1):
            fmt = self._response_format(response_model)
            sys_content = messages[0]["content"]
            if fmt["type"] != "json_schema":
                # json_object / plain mode: make the schema explicit in-prompt.
                if self._schema_hint(response_model) not in sys_content:
                    messages[0] = {
                        "role": "system",
                        "content": f"{sys_content}\n\n{self._schema_hint(response_model)}",
                    }

            try:
                response = self._call_with_backoff(
                    model=self.config.llm_model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=self.config.llm_max_tokens,
                    response_format=fmt,
                )
            except Exception as exc:
                # Endpoint rejected the json_schema payload: degrade once and retry.
                message = str(exc).lower()
                if (
                    fmt["type"] == "json_schema"
                    and not self._schema_fallback
                    and ("response_format" in message or "json_schema" in message or "schema" in message
                         or getattr(exc, "status_code", None) == 400)
                ):
                    logging.warning(
                        "Endpoint rejected json_schema response_format; "
                        "degrading to json_object for the rest of this run."
                    )
                    self._schema_fallback = True
                    continue
                raise

            usage = getattr(response, "usage", None)
            if usage:
                self.total_prompt_tokens += usage.prompt_tokens or 0
                self.total_completion_tokens += usage.completion_tokens or 0
                logging.info(
                    f"LLM call ok ({response_model.__name__}): "
                    f"prompt={usage.prompt_tokens} completion={usage.completion_tokens} tokens"
                )

            content = response.choices[0].message.content or ""
            try:
                return response_model.model_validate(self._extract_json(content))
            except Exception as exc:
                if validation_attempt == self.config.llm_max_retries:
                    raise LLMError(
                        f"Model output failed {response_model.__name__} validation "
                        f"after {self.config.llm_max_retries + 1} attempts: {exc}"
                    ) from exc
                logging.warning(
                    f"Invalid JSON for {response_model.__name__} "
                    f"(validation retry {validation_attempt + 1}/{self.config.llm_max_retries})"
                )
                messages.append({"role": "assistant", "content": content})
                messages.append({
                    "role": "user",
                    "content": "Your previous response was not valid JSON for the required "
                               "schema. Respond again with ONLY a valid JSON object.",
                })

        raise LLMError(f"Unreachable: {response_model.__name__}")  # pragma: no cover
