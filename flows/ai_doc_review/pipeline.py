"""Pure-Python review pipeline, replicating the PromptFlow DAG with identical
prompt assets (prompts/{grammar,definitive_language}/*.jinja2 are untouched):

  text chunk ([i]-prefixed paragraphs)
    -> N concurrent agent shots per issue type (temperature 1.0) -> AllSingleShotIssues
    -> dedup by (type, source_sentence) + comment_id        (aggregate step)
    -> 1 consolidator call -> AllConsolidatorIssues (score / KEEP|REMOVE)
    -> merge on comment_id, drop suggested_action == REMOVE  (merge step)
    -> add_bounding_box() per issue (best effort, failures are logged)
    -> yield AllCombinedIssues.model_dump_json() per chunk
"""

import logging
import random
import string
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Generator, List

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from common.models import (
    AllCombinedIssues,
    AllConsolidatorIssues,
    AllSingleShotIssues,
    CombinedIssue,
    ConsolidatorIssue,
    IssueType,
    SingleShotIssue,
)

from flows.ai_doc_review.bounding_box import add_bounding_box
from flows.ai_doc_review.config import PipelineConfig
from flows.ai_doc_review.document import ExtractedDocument
from flows.ai_doc_review.llm import LLMClient

logging = logging.getLogger(__name__)

PROMPTS_PATH = Path(__file__).parent / "prompts"

AGENT_PROMPTS = {
    IssueType.GrammarSpelling: {
        "agent": PROMPTS_PATH / "grammar" / "agent.jinja2",
        "consolidator": PROMPTS_PATH / "grammar" / "consolidator.jinja2",
        "guidelines": PROMPTS_PATH / "grammar" / "guidelines.jinja2",
    },
    IssueType.DefinitiveLanguage: {
        "agent": PROMPTS_PATH / "definitive_language" / "agent.jinja2",
        "consolidator": PROMPTS_PATH / "definitive_language" / "consolidator.jinja2",
        "guidelines": PROMPTS_PATH / "definitive_language" / "guidelines.jinja2",
    },
}

_jinja_env = Environment(
    loader=FileSystemLoader(PROMPTS_PATH),
    undefined=StrictUndefined,
    keep_trailing_newline=True,
)


def render_prompt(template_path: Path, **context) -> str:
    """Render a prompt template by path relative to the prompts directory."""
    template = _jinja_env.get_template(str(template_path.relative_to(PROMPTS_PATH)).replace("\\", "/"))
    return template.render(**context)


def generate_random_string(length: int = 6) -> str:
    letters = string.ascii_letters
    return "".join(random.choice(letters) for _ in range(length))


def run_agent_shots(
    llm: LLMClient, issue_type: IssueType, text: str, config: PipelineConfig
) -> List[SingleShotIssue]:
    """Run N concurrent agent shots for one issue type; failed shots are
    logged and dropped (single-shot isolation, one bad shot never kills the
    chunk)."""
    paths = AGENT_PROMPTS[issue_type]
    guidelines = render_prompt(paths["guidelines"])
    system_prompt = render_prompt(paths["agent"], guidelines=guidelines)

    def one_shot(_: int) -> AllSingleShotIssues:
        return llm.complete_json(
            system_prompt=system_prompt,
            user_prompt=text,
            response_model=AllSingleShotIssues,
            temperature=1.0,
        )

    shots: List[SingleShotIssue] = []
    with ThreadPoolExecutor(max_workers=max(1, config.llm_max_workers)) as pool:
        futures = [pool.submit(one_shot, i) for i in range(max(1, config.llm_shots))]
        for future in futures:
            try:
                shots.extend(future.result().issues)
            except Exception as exc:
                logging.error(f"Agent shot failed for {issue_type.value}: {exc}")

    for issue in shots:
        issue.type = issue_type
    return shots


def aggregate_shots(shots: List[SingleShotIssue]) -> List[SingleShotIssue]:
    """Dedup by (type, source_sentence) and assign a comment_id (aggregate step)."""
    combined: List[SingleShotIssue] = []
    seen = set()
    total_before = len(shots)
    for issue in shots:
        key = (issue.type, issue.location.source_sentence)
        if key not in seen:
            seen.add(key)
            issue.comment_id = generate_random_string()
            combined.append(issue)
    logging.info(
        f"Aggregation: {total_before} shots -> {len(combined)} unique issues after dedup"
    )
    return combined


def run_consolidator(
    llm: LLMClient, issue_type: IssueType, aggregated: List[SingleShotIssue],
    config: PipelineConfig,
) -> List[ConsolidatorIssue]:
    """One consolidator call; on failure returns empty list (chunk degrades to
    unfiltered agent issues rather than being lost)."""
    if not aggregated:
        return []
    paths = AGENT_PROMPTS[issue_type]
    guidelines = render_prompt(paths["guidelines"])
    system_prompt = render_prompt(paths["consolidator"], guidelines=guidelines)
    try:
        result = llm.complete_json(
            system_prompt=system_prompt,
            user_prompt=AllSingleShotIssues(issues=aggregated).model_dump_json(),
            response_model=AllConsolidatorIssues,
            temperature=1.0,
        )
        return result.issues
    except Exception as exc:
        logging.error(f"Consolidator failed for {issue_type.value}: {exc}; keeping unfiltered issues")
        return []


def merge_with_consolidator(
    aggregated: List[SingleShotIssue], consolidator_issues: List[ConsolidatorIssue]
) -> List[CombinedIssue]:
    """Merge on comment_id and drop suggested_action == REMOVE (merge step)."""
    actions = {c.comment_id: c for c in consolidator_issues}
    combined: List[CombinedIssue] = []
    for issue in aggregated:
        verdict = actions.get(issue.comment_id)
        if verdict is None:
            # No consolidator verdict (e.g. consolidator failure): keep the issue.
            combined.append(CombinedIssue(**issue.model_dump(), score=0,
                                         suggested_action="KEEP",
                                         reason_for_suggested_action="No consolidator verdict"))
            continue
        if verdict.suggested_action != "REMOVE":
            combined.append(
                CombinedIssue(**issue.model_dump(exclude={"comment_id"}), **verdict.model_dump())
            )
    logging.info(
        f"Merge: {len(aggregated)} issues + {len(consolidator_issues)} verdicts "
        f"-> {len(combined)} kept after REMOVE filter"
    )
    return combined


def review_chunk(llm: LLMClient, config: PipelineConfig, di_result: ExtractedDocument, text: str) -> str:
    """Run the full DAG for one text chunk and return AllCombinedIssues JSON."""
    all_issues: List[CombinedIssue] = []
    for issue_type in AGENT_PROMPTS:
        shots = run_agent_shots(llm, issue_type, text, config)
        aggregated = aggregate_shots(shots)
        verdicts = run_consolidator(llm, issue_type, aggregated, config)
        all_issues.extend(merge_with_consolidator(aggregated, verdicts))

    # Best-effort bounding boxes: a failed highlight never aborts the review.
    for issue in all_issues:
        try:
            add_bounding_box(di_result, issue)
        except Exception as exc:
            logging.error(f"Unable to add bounding box to issue '{issue.text}': {exc}")

    return AllCombinedIssues(issues=all_issues).model_dump_json()


def stream_review(
    di_result: ExtractedDocument,
    chunks: Generator,
    config: PipelineConfig,
) -> Generator[str, None, None]:
    """Yield one AllCombinedIssues JSON string per text chunk (the streaming
    contract consumed by the API's IssuesService)."""
    llm = LLMClient(config)
    for text_chunk in chunks:
        yield review_chunk(llm, config, di_result, text_chunk)
    logging.info(
        f"Review finished; token usage: prompt={llm.total_prompt_tokens} "
        f"completion={llm.total_completion_tokens}"
    )
