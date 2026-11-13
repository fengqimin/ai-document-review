"""Model tolerance tests: fields the pipeline computes itself.

Real endpoints (verified against a DeepSeek-compatible gateway) omit
page_num / bounding_box / comment_id even when the prompt asks for them.
Rejecting the finding for a missing placeholder loses a valid issue and burns
the retry budget, so the model fills them instead.
"""

import pytest

from common.models import SingleShotIssue


def test_missing_mechanical_fields_are_filled():
    issue = SingleShotIssue.model_validate({
        "type": "Definitive Language",
        "location": {"source_sentence": "The Supplier shall always deliver.", "para_index": 2},
        "text": "shall always",
        "explanation": "absolute obligation",
        "suggested_fix": "shall",
    })
    assert issue.location.page_num == 0
    assert issue.location.bounding_box == []
    assert issue.comment_id == ""
    assert issue.location.para_index == 2


def test_null_mechanical_fields_are_filled():
    issue = SingleShotIssue.model_validate({
        "type": "Grammar & Spelling",
        "location": {"source_sentence": "x", "para_index": 0,
                     "page_num": None, "bounding_box": None},
        "text": "teh",
        "explanation": "typo",
        "suggested_fix": "the",
        "comment_id": None,
    })
    assert issue.location.page_num == 0
    assert issue.location.bounding_box == []
    assert issue.comment_id == ""


def test_semantic_fields_are_still_required():
    """Tolerance must not turn into silently dropping real content."""
    with pytest.raises(Exception):
        SingleShotIssue.model_validate({
            "type": "Grammar & Spelling",
            "location": {"source_sentence": "x", "para_index": 0},
            "explanation": "typo",
            "suggested_fix": "the",
        })
