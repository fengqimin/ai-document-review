"""DI-compatible document structures.

Replaces azure.ai.formrecognizer AnalyzeResult with plain dataclasses shaped
exactly like the Document Intelligence response, so bounding_box.py logic is
reused verbatim:

- paragraph.spans[0].offset  -> global char offset of the paragraph's first word
- page.words[i].polygon      -> 4-point polygon in inches
- page.words[i].span.offset  -> global char offset of the word
- page.height                -> page height in inches
"""

from dataclasses import dataclass, field
from typing import List


@dataclass
class Point:
    x: float
    y: float


@dataclass
class Span:
    offset: int
    length: int


@dataclass
class BoundingRegion:
    page_number: int


@dataclass
class Word:
    content: str
    polygon: List[Point]
    span: Span


@dataclass
class Paragraph:
    content: str
    spans: List[Span] = field(default_factory=list)
    bounding_regions: List[BoundingRegion] = field(default_factory=list)


@dataclass
class Page:
    words: List[Word] = field(default_factory=list)
    height: float = 0.0  # inches


@dataclass
class ExtractedDocument:
    paragraphs: List[Paragraph] = field(default_factory=list)
    pages: List[Page] = field(default_factory=list)
