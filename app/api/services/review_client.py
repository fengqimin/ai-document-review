"""Wraps the (Phase B) synchronous review pipeline generator into an async
stream, replacing AMLClient's SSE forwarding. Keeps the event loop free while
the pipeline runs blocking work in a worker thread.
"""

import asyncio
from typing import AsyncGenerator, Generator

from common.logger import get_logger
from config.config import settings

logging = get_logger(__name__)

_SENTINEL = object()


class ReviewClient:
    """In-process review engine client (replaces AMLClient)."""

    def _sync_stream(self, pdf_path: str) -> Generator[str, None, None]:
        import sys
        from pathlib import Path

        # The API runs with cwd=app/api; the flow package and `common` live at
        # the repository root, which must be importable.
        repo_root = str(Path(__file__).resolve().parents[3])
        if repo_root not in sys.path:
            sys.path.insert(0, repo_root)
        try:
            from flows.ai_doc_review.engine import stream_review
        except ImportError as e:
            raise RuntimeError(
                f"Review pipeline is not importable (missing dependencies or path): {e}"
            ) from e
        yield from stream_review(pdf_path)

    async def stream_chunks(self, pdf_name: str) -> AsyncGenerator[str, None]:
        """Yield FlowOutputChunk JSON strings produced by the review pipeline."""
        if not settings.llm_configured:
            raise RuntimeError(
                "LLM endpoint is not configured. Set LLM_BASE_URL, LLM_API_KEY and "
                "LLM_MODEL in the environment (see docs/local-deployment-plan.md §7)."
            )

        pdf_path = settings.documents_dir / pdf_name
        if not pdf_path.is_file():
            raise FileNotFoundError(f"Document '{pdf_name}' not found in local storage.")

        logging.info(f"Starting in-process review stream for document {pdf_name}.")
        gen = self._sync_stream(str(pdf_path))
        while True:
            chunk = await asyncio.to_thread(next, gen, _SENTINEL)
            if chunk is _SENTINEL:
                break
            yield chunk
        logging.info(f"Review stream for document {pdf_name} finished.")
