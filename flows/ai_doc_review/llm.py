"""OpenAI-compatible LLM client (replaces PromptFlow typed_llm +
AzureOpenAIConnection).

- Vendor-neutral: only base_url / api_key / model, so OpenAI, DeepSeek, Qwen
  (compatibility mode), Moonshot or an intranet vLLM/SGLang endpoint all work
  without code changes.
- Structured output: json_schema response_format preferred; automatic
  fallback to json_object + schema injection when the endpoint rejects it.
- Retries: transient errors (429/5xx/timeout/connection) use exponential
  backoff with jitter, counted separately from JSON-validation retries.
- Concurrency: one client per review run owns a semaphore capping in-flight
  requests at LLM_MAX_WORKERS, shared by every dimension and chunk.
- Usage: token counts and latency are logged per call (never prompt bodies or
  keys)."""

import json
import logging
import random
import threading
import time
from typing import Type, TypeVar, get_args, get_origin

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


def _is_list_annotation(annotation) -> bool:
    """True for list[...] (possibly wrapped in Optional/Union)."""
    if get_origin(annotation) is list:
        return True
    return any(_is_list_annotation(arg) for arg in get_args(annotation))

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
        # One client per review run: this semaphore is the hard cap on
        # concurrent requests, shared by every dimension and in-flight chunk.
        self._request_slots = threading.BoundedSemaphore(max(1, int(config.llm_max_workers or 1)))
        self.last_call_seconds = 0.0
        self._usage_lock = threading.Lock()
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

    @staticmethod
    def _envelope_hint(response_model: Type[T]) -> str:
        """Concrete top-level shape, e.g. '{"issues": [...]}'."""
        list_fields = [
            name for name, field in response_model.model_fields.items()
            if _is_list_annotation(field.annotation)
        ]
        if len(list_fields) == 1:
            return '{"%s": [...]}' % list_fields[0]
        return '{"<field>": ...}'

    def _is_transient(self, exc: Exception) -> bool:
        status = getattr(exc, "status_code", None)
        if status in _TRANSIENT_STATUS_CODES:
            return True
        name = type(exc).__name__
        return name in ("APIConnectionError", "APITimeoutError", "Timeout", "ConnectionError")

    def _call_with_backoff(self, **kwargs):
        """Chat completion with exponential backoff + jitter on transient errors.

        The request slot is held only for the HTTP call itself, never across a
        backoff sleep, so a rate-limited run does not stall the whole pool."""
        attempts = self.config.llm_transient_retries + 1
        delay = 1.0
        last_exc = None
        for attempt in range(attempts):
            try:
                with self._request_slots:
                    started = time.monotonic()
                    response = self.client.chat.completions.create(**kwargs)
                self.last_call_seconds = time.monotonic() - started
                return response
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

    def _extract_json(self, content: str):
        """Parse JSON from model output, tolerating markdown fences.

        Returns whatever JSON value the model produced (object or array): some
        OpenAI-compatible endpoints ignore the requested envelope and answer
        with a bare array, which `_coerce_to_model` then wraps.
        """
        text = content.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        # Fall back to the first balanced object/array embedded in prose.
        starts = [(text.find("{" ), "{", "}"), (text.find("["), "[", "]")]
        candidates = [c for c in starts if c[0] >= 0]
        if not candidates:
            raise ValueError(f"No JSON found in model output: {text[:200]!r}")
        pos, opener, closer = min(candidates, key=lambda c: c[0])
        end = text.rfind(closer)
        if end <= pos:
            raise ValueError(f"Unbalanced JSON in model output: {text[:200]!r}")
        return json.loads(text[pos:end + 1])

    @staticmethod
    def _coerce_to_model(response_model: Type[T], raw):
        """Wrap a bare array into the single-list-field envelope when needed.

        Many "OpenAI-compatible" endpoints return `[{...}]` even when asked for
        `{"issues": [{...}]}`. Without this, every shot fails validation, and a
        whole review dimension silently degrades.
        """
        if isinstance(raw, dict):
            # Occasionally the envelope key is renamed ("items", "data", ...).
            list_fields = [
                name for name, field in response_model.model_fields.items()
                if _is_list_annotation(field.annotation)
            ]
            if len(list_fields) == 1 and list_fields[0] not in raw:
                for key, value in raw.items():
                    if isinstance(value, list):
                        return {list_fields[0]: value}
            return raw
        if isinstance(raw, list):
            list_fields = [
                name for name, field in response_model.model_fields.items()
                if _is_list_annotation(field.annotation)
            ]
            if len(list_fields) == 1:
                return {list_fields[0]: raw}
        return raw

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
                with self._usage_lock:
                    self.total_prompt_tokens += usage.prompt_tokens or 0
                    self.total_completion_tokens += usage.completion_tokens or 0
                logging.info(
                    f"LLM call ok ({response_model.__name__}) in "
                    f"{self.last_call_seconds:.1f}s: "
                    f"prompt={usage.prompt_tokens} completion={usage.completion_tokens} tokens"
                )
            else:
                logging.info(
                    f"LLM call ok ({response_model.__name__}) in "
                    f"{self.last_call_seconds:.1f}s (no usage reported)"
                )

            content = response.choices[0].message.content or ""
            finish_reason = getattr(response.choices[0], "finish_reason", None)
            try:
                return response_model.model_validate(
                    self._coerce_to_model(response_model, self._extract_json(content))
                )
            except Exception as exc:
                if validation_attempt == self.config.llm_max_retries:
                    raise LLMError(
                        f"Model output failed {response_model.__name__} validation "
                        f"after {self.config.llm_max_retries + 1} attempts "
                        f"(finish_reason={finish_reason}): {exc}"
                    ) from exc
                # finish_reason=length means the JSON was cut off by
                # LLM_MAX_TOKENS, not that the model is ignoring the schema.
                hint = " (output truncated: raise LLM_MAX_TOKENS or lower the batch size)" \
                    if finish_reason == "length" else ""
                logging.warning(
                    f"Invalid JSON for {response_model.__name__}{hint} "
                    f"(finish_reason={finish_reason}, validation retry "
                    f"{validation_attempt + 1}/{self.config.llm_max_retries})"
                )
                messages.append({"role": "assistant", "content": content})
                messages.append({
                    "role": "user",
                    "content": "Your previous response was not valid JSON for the required "
                               f"schema. Respond again with ONLY a JSON object shaped like "
                               f"{self._envelope_hint(response_model)} — the top level must "
                               "be an object, not an array, and without markdown fences.",
                })

        raise LLMError(f"Unreachable: {response_model.__name__}")  # pragma: no cover
