"""Extraction compatibility-bridge tests: a synthetic one-page PDF must
produce DI-shaped structures whose paragraph offsets hit word spans, and
add_bounding_box must produce quadpoints."""

import fitz
import pytest
from pathlib import Path

from common.models import CombinedIssue, IssueType, Location
from flows.ai_doc_review.document import ExtractedDocument
from flows.ai_doc_review.text import extract_document, get_text_chunks
from flows.ai_doc_review.bounding_box import add_bounding_box

SENTENCE_1 = "The quick brown fox jumps over the lazy dog near the river bank today."
SENTENCE_2 = "Contoso guarantees that this product will certainly satisfy every customer."
TEXT = f"{SENTENCE_1} {SENTENCE_2}"


@pytest.fixture(scope="module")
def pdf_path(tmp_path_factory) -> str:
    doc = fitz.open()
    page = doc.new_page()  # default A4: 595 x 842 pt
    # Two separate lines: insert_text does not wrap, and words beyond the page
    # edge would be clipped by get_text("words").
    page.insert_text(fitz.Point(72, 100), SENTENCE_1, fontsize=11)
    page.insert_text(fitz.Point(72, 130), SENTENCE_2, fontsize=11)
    path = tmp_path_factory.mktemp("pdfs") / "sample.pdf"
    doc.save(str(path))
    doc.close()
    return str(path)


@pytest.fixture(scope="module")
def di_result(pdf_path) -> ExtractedDocument:
    return extract_document(pdf_path)


def test_extracts_paragraph(di_result):
    assert len(di_result.paragraphs) >= 1
    # fitz may split by line; the full text must be present across paragraphs
    joined = " ".join(p.content for p in di_result.paragraphs)
    assert SENTENCE_1 in joined and SENTENCE_2 in joined


def test_paragraph_offsets_hit_word_spans(di_result):
    """Core bridge invariant: paragraphs[i].spans[0].offset matches a word
    span offset on that paragraph's page (used by add_bounding_box)."""
    for paragraph in di_result.paragraphs:
        page = di_result.pages[paragraph.bounding_regions[0].page_number - 1]
        offsets = {w.span.offset for w in page.words}
        assert paragraph.spans[0].offset in offsets


def test_word_offsets_accumulate(di_result):
    words = [w for page in di_result.pages for w in page.words]
    assert words[0].span.offset == 0
    for a, b in zip(words, words[1:]):
        assert b.span.offset == a.span.offset + len(a.content) + 1


def test_word_polygons_in_inches(di_result):
    word = di_result.pages[0].words[0]
    assert all(0 <= p.x <= 12 and 0 <= p.y <= 12 for p in word.polygon)  # inches on A4
    assert di_result.pages[0].height == pytest.approx(842 / 72)  # A4 height in inches


def test_chunks_carry_index_prefix(di_result):
    chunks = list(get_text_chunks(di_result, paragraphs_per_chunk=1))
    assert len(chunks) == len(di_result.paragraphs)
    for i, chunk in enumerate(chunks):
        assert chunk.startswith(f"[{i}]")


def test_single_chunk_contains_all_paragraphs(di_result):
    chunks = list(get_text_chunks(di_result, paragraphs_per_chunk=16))
    assert len(chunks) == 1
    assert "[0]" in chunks[0]


def test_add_bounding_box(di_result):
    """source_sentence = paragraph content, text inside it -> quadpoints."""
    para_index = next(
        i for i, p in enumerate(di_result.paragraphs) if "guarantees" in p.content
    )
    paragraph = di_result.paragraphs[para_index]
    issue = CombinedIssue(
        type=IssueType.DefinitiveLanguage,
        location=Location(
            source_sentence=paragraph.content,
            page_num=0,
            bounding_box=[],
            para_index=para_index,
        ),
        text="guarantees",
        explanation="absolute claim",
        suggested_fix="may",
        comment_id="abcdef",
        score=8,
        suggested_action="KEEP",
        reason_for_suggested_action="ok",
    )
    result = add_bounding_box(di_result, issue)
    assert result.location.page_num == 1
    assert len(result.location.bounding_box) == 8
    assert all(coord == coord for coord in result.location.bounding_box)  # no NaN


def test_add_bounding_box_missing_text_keeps_issue(di_result):
    """Issue text not in source sentence -> returned unchanged (no crash)."""
    para_index = next(
        i for i, p in enumerate(di_result.paragraphs) if "guarantees" in p.content
    )
    paragraph = di_result.paragraphs[para_index]
    issue = CombinedIssue(
        type=IssueType.GrammarSpelling,
        location=Location(source_sentence=paragraph.content, page_num=0,
                          bounding_box=[], para_index=para_index),
        text="zzz-not-present-zzz",
        explanation="x", suggested_fix="x", comment_id="abc123",
        score=5, suggested_action="KEEP", reason_for_suggested_action="r",
    )
    result = add_bounding_box(di_result, issue)
    assert result.location.bounding_box == []
