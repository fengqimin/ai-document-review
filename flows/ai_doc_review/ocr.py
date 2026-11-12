"""Optional OCR for scanned PDFs (no text layer).

Uses PyMuPDF to render pages and pytesseract to recover word boxes. Off by
default; requires the tesseract binary plus the language packs named in
OCR_LANGUAGES (e.g. "eng", "eng+chi_sim")."""

import logging
from typing import List, Tuple

from flows.ai_doc_review.document import Point, Span, Word

logging.getLogger(__name__).addHandler(logging.NullHandler())

# Render pages at this zoom for OCR, then scale boxes back to PDF points.
OCR_DPI = 300
_PDF_BASE_DPI = 72


def ocr_page_words(page, languages: str) -> List[Tuple]:
    """Return word tuples in the same shape as fitz page.get_text("words"):
    (x0, y0, x1, y1, text, block_no, line_no, word_no)."""
    try:
        import pytesseract
        from PIL import Image
        import io
    except ImportError as e:
        raise RuntimeError(
            "OCR is enabled but pytesseract/Pillow are not installed. "
            "Install them and the tesseract binary with the required language packs."
        ) from e

    zoom = OCR_DPI / _PDF_BASE_DPI
    pix = page.get_pixmap(matrix=__import__("fitz").Matrix(zoom, zoom))
    img = Image.open(io.BytesIO(pix.tobytes("png")))
    data = pytesseract.image_to_data(img, lang=languages, output_type=pytesseract.Output.DICT)

    words: List[Tuple] = []
    scale = _PDF_BASE_DPI / OCR_DPI
    n_words = len(data["text"])
    block_lines: dict = {}
    for i in range(n_words):
        text = (data["text"][i] or "").strip()
        if not text or int(data["conf"][i]) < 0:
            continue
        key = (data["block_num"][i], data["line_num"][i])
        seq = block_lines.setdefault(data["block_num"][i], {})
        seq.setdefault(key, []).append(
            (
                data["left"][i] * scale,
                data["top"][i] * scale,
                (data["left"][i] + data["width"][i]) * scale,
                (data["top"][i] + data["height"][i]) * scale,
                text,
            )
        )

    for block_no, lines in sorted(block_lines.items()):
        for line_no, line_words in enumerate(sorted(lines.values())):
            for word_no, (x0, y0, x1, y1, text) in enumerate(line_words):
                words.append((x0, y0, x1, y1, text, block_no, line_no, word_no))
    return words


def make_word(text: str, x0: float, y0: float, x1: float, y1: float, offset: int) -> Word:
    """Build a DI-compatible Word from PDF-point coordinates and a char offset."""
    polygon = [Point(x0 / 72, y0 / 72), Point(x1 / 72, y0 / 72),
               Point(x1 / 72, y1 / 72), Point(x0 / 72, y1 / 72)]
    return Word(content=text, polygon=polygon, span=Span(offset=offset, length=len(text)))
