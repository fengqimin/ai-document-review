"""Concurrency contract of the review pipeline.

A 3-paragraph chunk used to take ~4 minutes because both dimensions ran back to
back and each dimension's shots were throttled to 2 workers. These tests pin the
properties that fix it:

- dimensions (and their shots) overlap instead of running in sequence,
- LLM_MAX_WORKERS is a hard global cap on concurrent HTTP requests,
- pipelined chunks are still emitted in document order,
- a failing chunk still surfaces to the caller.
"""

import json
import threading
import time
from types import SimpleNamespace

import pytest

from common.models import (
    AllCombinedIssues,
    AllConsolidatorIssues,
    AllSingleShotIssues,
    IssueType,
    Location,
    SingleShotIssue,
)
from flows.ai_doc_review.config import PipelineConfig
from flows.ai_doc_review.llm import LLMClient
from flows.ai_doc_review.pipeline import review_chunk, stream_review


class StubLLM:
    """Duck-typed LLMClient: records overlap, never calls a provider."""

    def __init__(self, delay=0.0, delays=None, tag_by_chunk=False):
        self.delay = delay
        self.delays = delays or {}
        self.tag_by_chunk = tag_by_chunk
        self.lock = threading.Lock()
        self.active = 0
        self.peak = 0
        self.started = []
        self.completed = []
        # Same accounting surface as LLMClient (logged by stream_review).
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0

    def complete_json(self, system_prompt, user_prompt, response_model, temperature=1.0):
        with self.lock:
            self.started.append(user_prompt)
            self.active += 1
            self.peak = max(self.peak, self.active)
        try:
            time.sleep(self.delays.get(user_prompt, self.delay))
            if response_model is AllSingleShotIssues:
                issues = []
                if self.tag_by_chunk:
                    issues.append(SingleShotIssue(
                        type=IssueType.GrammarSpelling, text=user_prompt,
                        explanation="stub", suggested_fix="stub",
                        location=Location(source_sentence=user_prompt, page_num=1,
                                          bounding_box=[], para_index=0),
                    ))
                return AllSingleShotIssues(issues=issues)
            return AllConsolidatorIssues(issues=[])
        finally:
            with self.lock:
                self.active -= 1
                self.completed.append(user_prompt)


def make_config(**overrides):
    defaults = dict(
        llm_shots=2, llm_max_workers=8, chunk_max_workers=2,
        llm_max_retries=0, llm_transient_retries=0,
    )
    defaults.update(overrides)
    return PipelineConfig(_env_file=None, **defaults)


def test_shots_of_both_dimensions_overlap():
    """6 calls at 0.2s each: serial would be 1.2s, one fan-out is ~0.2s."""
    stub = StubLLM(delay=0.2)
    config = make_config(llm_shots=3, chunk_max_workers=1)

    started = time.monotonic()
    review_chunk(stub, config, None, "chunk text")
    elapsed = time.monotonic() - started

    assert stub.peak == 6, "expected all shots of both dimensions in flight"
    assert elapsed < 0.75, f"shots still serialized: {elapsed:.2f}s"


def test_llm_client_caps_concurrent_requests():
    """The semaphore, not the pool size, is what protects the provider."""

    class FakeCompletions:
        def __init__(self):
            self.lock = threading.Lock()
            self.active = 0
            self.peak = 0

        def create(self, **kwargs):
            with self.lock:
                self.active += 1
                self.peak = max(self.peak, self.active)
            time.sleep(0.05)
            with self.lock:
                self.active -= 1
            return SimpleNamespace(
                choices=[SimpleNamespace(
                    message=SimpleNamespace(content='{"issues": []}'))],
                usage=None,
            )

    completions = FakeCompletions()
    client = LLMClient(make_config(llm_max_workers=2, llm_api_key="test-key",
                                   llm_base_url="http://127.0.0.1:1/v1"))
    client.client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    errors = []

    def call():
        try:
            client.complete_json("s", "u", AllSingleShotIssues)
        except Exception as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=call) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert not errors
    assert completions.peak == 2, f"cap violated: {completions.peak} concurrent requests"


def test_pipelined_chunks_are_yielded_in_document_order():
    """Chunk 2 finishes first, but chunk 1 is still emitted first."""
    chunks = ["chunk-one", "chunk-two", "chunk-three"]
    stub = StubLLM(delays={"chunk-one": 0.3, "chunk-two": 0.02, "chunk-three": 0.02},
                   tag_by_chunk=True)
    config = make_config(llm_shots=1, chunk_max_workers=2)

    payloads = list(stream_review(None, iter(chunks), config, stub))
    order = [AllCombinedIssues.model_validate_json(p).issues[0].location.source_sentence
             for p in payloads]

    assert order == chunks
    # Pipelining actually happened: the second chunk completed before the first.
    assert stub.completed.index("chunk-two") < stub.completed.index("chunk-one")


def test_chunk_failure_propagates_and_closes_the_stream(monkeypatch):
    """A chunk-level failure is re-raised at the point the caller consumes that
    chunk, and the stream closes instead of hanging on queued work.

    Shot failures are isolated on purpose (see run_all_shots), so the failure is
    injected at chunk level."""
    from flows.ai_doc_review import pipeline

    started = []

    def fake_review_chunk(llm, config, di_result, text):
        started.append(text)
        time.sleep(0.05)
        if text == "chunk-bad":
            raise RuntimeError("boom chunk-bad")
        return '{"issues": []}'

    monkeypatch.setattr(pipeline, "review_chunk", fake_review_chunk)
    config = make_config(llm_shots=1, chunk_max_workers=2)
    stream = stream_review(None, iter(["chunk-bad", "chunk-good", "chunk-later"]), config,
                           StubLLM())

    with pytest.raises(RuntimeError, match="boom chunk-bad"):
        next(stream)
    with pytest.raises(StopIteration):
        next(stream)
    # Bounded look-ahead: the third chunk is never picked up.
    assert "chunk-later" not in started


def test_serial_mode_still_emits_every_chunk():
    """chunk_max_workers=1 keeps the pre-pipelining behaviour."""
    stub = StubLLM(tag_by_chunk=True)
    config = make_config(llm_shots=1, chunk_max_workers=1)

    payloads = list(stream_review(None, iter(["a", "b"]), config, stub))
    texts = [json.loads(p)["issues"][0]["text"] for p in payloads]
    assert texts == ["a", "b"]


def test_consolidator_input_is_batched():
    """Verdicts are verbose: one call for 25 issues overflowed LLM_MAX_TOKENS
    and truncated the JSON. Batches keep every call small, and every issue still
    gets its verdict merged back."""
    from common.models import ConsolidatorIssue
    from flows.ai_doc_review.pipeline import run_consolidators

    class BatchStub:
        def __init__(self):
            self.batch_sizes = []
            self.lock = threading.Lock()

        def complete_json(self, system_prompt, user_prompt, response_model, temperature=1.0):
            issues = json.loads(user_prompt)["issues"]
            with self.lock:
                self.batch_sizes.append(len(issues))
            return AllConsolidatorIssues(issues=[
                ConsolidatorIssue(comment_id=issue["comment_id"], score=7,
                                  suggested_action="KEEP",
                                  reason_for_suggested_action="ok")
                for issue in issues
            ])

    issues = [
        SingleShotIssue(
            type=IssueType.GrammarSpelling, text=f"word{i}", explanation="e",
            suggested_fix="f", comment_id=f"id{i:02d}",
            location=Location(source_sentence=f"Sentence number {i} appears here.",
                              page_num=1, bounding_box=[], para_index=0),
        )
        for i in range(25)
    ]
    stub = BatchStub()
    verdicts = run_consolidators(
        stub, {IssueType.GrammarSpelling: issues},
        make_config(consolidator_batch_size=10),
    )

    assert sorted(stub.batch_sizes) == [5, 10, 10]
    assert len(verdicts[IssueType.GrammarSpelling]) == 25
    assert {v.comment_id for v in verdicts[IssueType.GrammarSpelling]} == {i.comment_id for i in issues}
