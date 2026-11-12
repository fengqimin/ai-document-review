"""Pipeline DAG unit tests with fixed JSON: dedup, comment_id, REMOVE filter,
consolidator-failure fallback."""

from common.models import (
    AllSingleShotIssues,
    CombinedIssue,
    ConsolidatorIssue,
    IssueType,
    Location,
    SingleShotIssue,
)
from flows.ai_doc_review.pipeline import (
    aggregate_shots,
    merge_with_consolidator,
    render_prompt,
)


def make_issue(comment_id: str = "", source_sentence: str = "This product will win awards.",
               text: str = "will", issue_type: IssueType = IssueType.DefinitiveLanguage) -> SingleShotIssue:
    return SingleShotIssue(
        type=issue_type,
        location=Location(source_sentence=source_sentence, page_num=1,
                          bounding_box=[], para_index=0),
        text=text, explanation="definitive", suggested_fix="may",
        comment_id=comment_id,
    )


def test_aggregate_dedups_and_assigns_comment_ids():
    shots = [
        make_issue(),
        make_issue(),  # exact duplicate (same type + source_sentence)
        make_issue(source_sentence="A different sentence appears here once.",
                   text="different"),
    ]
    result = aggregate_shots(shots)
    assert len(result) == 2
    assert all(issue.comment_id and len(issue.comment_id) == 6 for issue in result)
    assert len({issue.comment_id for issue in result}) == 2  # ids unique


def test_merge_filters_remove():
    aggregated = aggregate_shots([make_issue(), make_issue(
        source_sentence="Another sentence with a grammar error inside it.", text="error",
        issue_type=IssueType.GrammarSpelling)])
    verdicts = [
        ConsolidatorIssue(comment_id=aggregated[0].comment_id, score=8,
                          suggested_action="KEEP", reason_for_suggested_action="valid"),
        ConsolidatorIssue(comment_id=aggregated[1].comment_id, score=1,
                          suggested_action="REMOVE", reason_for_suggested_action="wrong"),
    ]
    merged = merge_with_consolidator(aggregated, verdicts)
    assert len(merged) == 1
    assert merged[0].score == 8
    assert merged[0].suggested_action == "KEEP"
    assert merged[0].text == "will"


def test_merge_without_verdict_keeps_issue():
    """Consolidator failure fallback: no verdicts -> issues kept unfiltered."""
    aggregated = aggregate_shots([make_issue()])
    merged = merge_with_consolidator(aggregated, [])
    assert len(merged) == 1
    assert merged[0].suggested_action == "KEEP"


def test_render_agent_prompt_with_guidelines():
    from flows.ai_doc_review.pipeline import AGENT_PROMPTS
    prompt = render_prompt(AGENT_PROMPTS[IssueType.GrammarSpelling]["agent"],
                           guidelines="GUIDELINE-CONTENT-XYZ")
    assert "GUIDELINE-CONTENT-XYZ" in prompt
    assert "Grammar & Spelling" in prompt
    # Contract fields the structured output must contain
    assert "source_sentence" in prompt and "para_index" in prompt


def test_consolidator_prompt_mentions_action_values():
    from flows.ai_doc_review.pipeline import AGENT_PROMPTS
    prompt = render_prompt(AGENT_PROMPTS[IssueType.DefinitiveLanguage]["consolidator"],
                           guidelines="G")
    assert "KEEP" in prompt and "REMOVE" in prompt


def test_all_single_shot_issues_roundtrip():
    """The JSON the model must produce validates against common.models."""
    payload = {
        "issues": [{
            "type": "Definitive Language",
            "text": "will",
            "explanation": "definitive language",
            "suggested_fix": "may",
            "location": {"source_sentence": "This product will win awards.",
                         "page_num": 0, "bounding_box": [], "para_index": 0},
            "comment_id": "abc123",
        }]
    }
    parsed = AllSingleShotIssues.model_validate(payload)
    assert parsed.issues[0].type == IssueType.DefinitiveLanguage
