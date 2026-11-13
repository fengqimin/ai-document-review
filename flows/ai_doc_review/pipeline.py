"""Pure-Python review pipeline, replicating the PromptFlow DAG with identical
prompt assets (prompts/{grammar,definitive_language}/*.jinja2 are untouched):

  text chunk ([i]-prefixed paragraphs)
    -> 2 dimensions x N shots fanned out into one pool (temperature 1.0)
       -> AllSingleShotIssues
    -> per dimension: dedup by (type, source_sentence) + comment_id (aggregate)
    -> per dimension: 1 consolidator call -> AllConsolidatorIssues
       (the two dimensions run concurrently, not back to back)
    -> merge on comment_id, drop suggested_action == REMOVE  (merge step)
    -> add_bounding_box() per issue (best effort, failures are logged)
    -> yield AllCombinedIssues.model_dump_json() per chunk

Chunks themselves are pipelined with a bounded look-ahead (CHUNK_MAX_WORKERS)
and still emitted in document order.
"""

import logging
import random
import string
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
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


@lru_cache(maxsize=1)
def _system_prompts() -> dict:
    """(agent, consolidator) system prompts per dimension, rendered once."""
    return {
        issue_type: (
            render_prompt(paths["agent"], guidelines=render_prompt(paths["guidelines"])),
            render_prompt(paths["consolidator"], guidelines=render_prompt(paths["guidelines"])),
        )
        for issue_type, paths in AGENT_PROMPTS.items()
    }


def run_all_shots(llm: LLMClient, text: str, config: PipelineConfig) -> dict:
    """Fan every (dimension, shot) pair out into one pool; return issues per
    dimension. A failed shot is logged and dropped (one bad shot never kills
    the chunk).

    Both dimensions used to run back to back, each with its own pool sized by
    LLM_MAX_WORKERS: 5 shots at 2 workers meant 3 sequential waves per
    dimension, i.e. ~4 minutes for one 3-paragraph chunk. Submitting all shots
    at once keeps the provider busy while the real request cap stays the LLM
    client's semaphore (also LLM_MAX_WORKERS, but interpreted globally).
    """
    prompts = _system_prompts()
    shots_per_type = max(1, config.llm_shots)
    jobs = [(issue_type, i) for issue_type in AGENT_PROMPTS for i in range(shots_per_type)]
    results: dict = {issue_type: [] for issue_type in AGENT_PROMPTS}
    started = time.monotonic()

    with ThreadPoolExecutor(max_workers=len(jobs), thread_name_prefix="shot") as pool:
        futures = {
            pool.submit(
                llm.complete_json,
                system_prompt=prompts[issue_type][0],
                user_prompt=text,
                response_model=AllSingleShotIssues,
                temperature=1.0,
            ): issue_type
            for issue_type, _ in jobs
        }
        for future, issue_type in futures.items():
            try:
                for issue in future.result().issues:
                    issue.type = issue_type
                    results[issue_type].append(issue)
            except Exception as exc:
                logging.error(f"Agent shot failed for {issue_type.value}: {exc}")

    logging.info(
        f"Agent shots: {len(jobs)} calls in {time.monotonic() - started:.1f}s -> "
        + ", ".join(f"{t.value}={len(v)} issues" for t, v in results.items())
    )
    return results


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
    system_prompt = _system_prompts()[issue_type][1]
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


def run_consolidators(llm: LLMClient, aggregated: dict, config: PipelineConfig) -> dict:
    """One consolidator call per non-empty dimension, run concurrently.

    Input is also batched: a verdict costs ~400 completion tokens, so a large
    chunk can push one consolidator call past LLM_MAX_TOKENS and truncate the
    JSON mid-object (observed with 5 issues at a 4096 budget). Batching is
    sound because `aggregate_shots` keeps exactly one issue per source
    sentence, so no verdict depends on issues in another batch.
    """
    batch_size = max(1, config.consolidator_batch_size)
    jobs = [
        (issue_type, issues[start:start + batch_size])
        for issue_type, issues in aggregated.items()
        for start in range(0, len(issues), batch_size)
    ]
    verdicts: dict = {issue_type: [] for issue_type in aggregated}
    if not jobs:
        return verdicts

    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=len(jobs), thread_name_prefix="consolidator") as pool:
        futures = {
            pool.submit(run_consolidator, llm, issue_type, batch, config): issue_type
            for issue_type, batch in jobs
        }
        for future, issue_type in futures.items():
            verdicts[issue_type].extend(future.result())
    logging.info(
        f"Consolidators: {len(jobs)} calls for {len(aggregated)} dimensions "
        f"in {time.monotonic() - started:.1f}s"
    )
    return verdicts


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
    started = time.monotonic()
    shots = run_all_shots(llm, text, config)
    aggregated = {issue_type: aggregate_shots(issues) for issue_type, issues in shots.items()}
    verdicts = run_consolidators(llm, aggregated, config)

    all_issues: List[CombinedIssue] = []
    # Iterate over AGENT_PROMPTS (not the dicts above) so the output order of
    # issues stays deterministic regardless of which calls finish first.
    for issue_type in AGENT_PROMPTS:
        all_issues.extend(
            merge_with_consolidator(aggregated[issue_type], verdicts.get(issue_type, []))
        )

    # Best-effort bounding boxes: a failed highlight never aborts the review.
    for issue in all_issues:
        try:
            add_bounding_box(di_result, issue)
        except Exception as exc:
            logging.error(f"Unable to add bounding box to issue '{issue.text}': {exc}")

    logging.info(
        f"Chunk review finished in {time.monotonic() - started:.1f}s "
        f"with {len(all_issues)} issues"
    )
    return AllCombinedIssues(issues=all_issues).model_dump_json()


def _stream_chunks_pipelined(
    llm: LLMClient,
    config: PipelineConfig,
    di_result: ExtractedDocument,
    chunks: Generator,
    workers: int,
) -> Generator[str, None, None]:
    """Keep up to `workers` chunks in flight, but yield them in document order.

    A long contract is many chunks; running them strictly one after another
    multiplies the per-chunk latency by the chunk count. The look-ahead is
    bounded so memory and provider load stay predictable; LLM_MAX_WORKERS is
    still the hard cap on concurrent requests.
    """
    pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="chunk")
    pending = deque()
    source = iter(chunks)

    def fill() -> None:
        while len(pending) < workers:
            try:
                text = next(source)
            except StopIteration:
                return
            pending.append(pool.submit(review_chunk, llm, config, di_result, text))

    fill()
    drained = False
    try:
        while pending:
            # .result() re-raises a chunk failure at the point it is consumed,
            # so the caller sees the same error contract as the serial path.
            payload = pending.popleft().result()
            fill()
            yield payload
        drained = True
    finally:
        # An abandoned review must not block on chunks nobody will consume.
        pool.shutdown(wait=drained, cancel_futures=True)


def stream_review(
    di_result: ExtractedDocument,
    chunks: Generator,
    config: PipelineConfig,
    llm: LLMClient | None = None,
) -> Generator[str, None, None]:
    """Yield one AllCombinedIssues JSON string per text chunk (the streaming
    contract consumed by the API's IssuesService).

    `llm` is injectable for tests; production always builds one client per run
    so the concurrency budget is shared across chunks."""
    llm = llm or LLMClient(config)
    workers = max(1, config.chunk_max_workers)
    started = time.monotonic()

    if workers == 1:
        for text_chunk in chunks:
            yield review_chunk(llm, config, di_result, text_chunk)
    else:
        yield from _stream_chunks_pipelined(llm, config, di_result, chunks, workers)

    logging.info(
        f"Review finished in {time.monotonic() - started:.1f}s; token usage: "
        f"prompt={llm.total_prompt_tokens} completion={llm.total_completion_tokens}"
    )
