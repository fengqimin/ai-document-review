"""PDF text extraction with PyMuPDF, producing a Document-Intelligence-shaped
result so bounding_box.py is reused unchanged (compatibility bridge, see
docs/local-deployment-plan.md §4.1).

Rules:
- words are the atomic units; global char offsets accumulate in reading order
  (len(word) + 1 per word, the +1 being the joining space);
- paragraphs are PyMuPDF blocks; paragraph content is words joined by single
  spaces, so chunk text "[i]{content}" maps 1:1 to paragraph indices;
- polygons are in inches (pt / 72) and page.height in inches, matching the
  72-dpi conversions in create_bounding_box();
- pages without a text layer fall back to OCR when enabled, else raise.
"""

import logging
from typing import List

import fitz
from more_itertools import batched

from flows.ai_doc_review.document import (
    BoundingRegion,
    ExtractedDocument,
    Page,
    Paragraph,
    Point,
    Span,
    Word,
)

logging = logging.getLogger(__name__)

PARAGRAPHS_PER_CHUNK = 16


def _page_has_text(page) -> bool:
    return bool(page.get_text("words"))


def extract_document(pdf_path: str, ocr_enabled: bool = False, ocr_languages: str = "eng") -> ExtractedDocument:
    """Extract paragraphs/pages/words from a PDF in DI-compatible shape."""
    result = ExtractedDocument()
    global_offset = 0

    with fitz.open(pdf_path) as pdf:
        for page_no, page in enumerate(pdf, start=1):
            raw_words = page.get_text("words")  # (x0, y0, x1, y1, text, block, line, word)

            if not raw_words and ocr_enabled:
                from flows.ai_doc_review.ocr import ocr_page_words

                logging.info(f"Page {page_no} has no text layer; running OCR ({ocr_languages}).")
                raw_words = ocr_page_words(page, ocr_languages)
            elif not raw_words:
                logging.warning(
                    f"Page {page_no} has no extractable text (likely scanned). "
                    "Set OCR_ENABLED=true to process scanned pages; skipping page."
                )
                result.pages.append(Page(words=[], height=page.rect.height / 72))
                continue

            # Group words by block, preserving in-block reading order.
            blocks: dict = {}
            for x0, y0, x1, y1, text, block_no, line_no, word_no in raw_words:
                text = text.strip()
                if not text:
                    continue
                blocks.setdefault(block_no, []).append((line_no, word_no, x0, y0, x1, y1, text))

            page_words: List[Word] = []
            for block_no in sorted(blocks):
                block_items = sorted(blocks[block_no], key=lambda w: (w[0], w[1]))
                para_words: List[Word] = []
                para_first_offset = None

                for line_no, word_no, x0, y0, x1, y1, text in block_items:
                    word = Word(
                        content=text,
                        polygon=[
                            Point(x0 / 72, y0 / 72),
                            Point(x1 / 72, y0 / 72),
                            Point(x1 / 72, y1 / 72),
                            Point(x0 / 72, y1 / 72),
                        ],
                        span=Span(offset=global_offset, length=len(text)),
                    )
                    if para_first_offset is None:
                        para_first_offset = global_offset
                    para_words.append(word)
                    page_words.append(word)
                    global_offset += len(text) + 1  # +1 for the joining space

                content = " ".join(w.content for w in para_words)
                result.paragraphs.append(
                    Paragraph(
                        content=content,
                        spans=[Span(offset=para_first_offset, length=len(content))],
                        bounding_regions=[BoundingRegion(page_number=page_no)],
                    )
                )

            result.pages.append(Page(words=page_words, height=page.rect.height / 72))

    logging.info(
        f"Extracted {len(result.paragraphs)} paragraphs "
        f"across {len(result.pages)} pages from {pdf_path}"
    )
    return result


def get_text_chunks(
    di_result: ExtractedDocument, paragraphs_per_chunk: int = PARAGRAPHS_PER_CHUNK
):
    """Yield text chunks with [i] paragraph-index prefixes (contract preserved
    from the Document Intelligence version)."""
    indexed = [f"[{i}]{paragraph.content}" for i, paragraph in enumerate(di_result.paragraphs)]
    if paragraphs_per_chunk == -1:
        yield "\n".join([p.content for p in di_result.paragraphs])
        return
    for batch in batched(indexed, paragraphs_per_chunk):
        yield "\n".join(batch)
