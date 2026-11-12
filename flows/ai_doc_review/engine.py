"""Top-level review engine: PDF path in, per-chunk JSON chunks out.

The API's ReviewClient consumes this as a synchronous generator in a worker
thread (asyncio.to_thread), keeping the event loop free."""

import logging
from pathlib import Path
from typing import Generator

from flows.ai_doc_review.config import PipelineConfig
from flows.ai_doc_review.text import extract_document, get_text_chunks

logging = logging.getLogger(__name__)


def stream_review(pdf_path: str, paragraphs_per_chunk: int | None = None) -> Generator[str, None, None]:
    """Stream review results for a local PDF file.

    Yields one AllCombinedIssues JSON string per paragraph chunk, matching the
    chunk contract previously produced by process_streaming.py.
    """
    config = PipelineConfig()
    if not config.llm_configured:
        raise RuntimeError(
            "LLM endpoint is not configured. Set LLM_BASE_URL, LLM_API_KEY and "
            "LLM_MODEL before running a review."
        )

    pdf = Path(pdf_path)
    if not pdf.is_file():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    di_result = extract_document(
        str(pdf), ocr_enabled=config.ocr_enabled, ocr_languages=config.ocr_languages
    )
    if not di_result.paragraphs:
        raise ValueError(
            f"No text could be extracted from '{pdf.name}'. If it is a scanned "
            "document, enable OCR (OCR_ENABLED=true, requires tesseract)."
        )

    ppc = paragraphs_per_chunk or config.paragraphs_per_chunk
    chunks = get_text_chunks(di_result, paragraphs_per_chunk=ppc)

    # Imported lazily so dependency errors surface with a clear message.
    from flows.ai_doc_review.pipeline import stream_review as _stream

    yield from _stream(di_result, chunks, config)
