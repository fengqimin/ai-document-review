"""End-to-end engine test: mock OpenAI-compatible service + synthetic PDF ->
stream_review yields one AllCombinedIssues JSON per chunk with merged issues."""

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pymupdf as fitz
import pytest

from common.models import AllCombinedIssues


AGENT_RESPONSE = {
    "issues": [
        {
            "type": "Grammar & Spelling",
            "text": "recieve",
            "explanation": "misspelled",
            "suggested_fix": "receive",
            "location": {"source_sentence": "You will recieve a confirmation email shortly.",
                         "page_num": 0, "bounding_box": [], "para_index": 0},
            "comment_id": "",
        },
        {
            "type": "Grammar & Spelling",
            "text": "teh",
            "explanation": "typo",
            "suggested_fix": "the",
            "location": {"source_sentence": "Please check teh document before signing.",
                         "page_num": 0, "bounding_box": [], "para_index": 1},
            "comment_id": "",
        },
    ]
}

CONSOLIDATOR_RESPONSE = {"issues": []}  # filled per request by verdicts below


class Handler(BaseHTTPRequestHandler):
    state = {"calls": 0}

    def log_message(self, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        Handler.state["calls"] += 1
        # Consolidator prompt (rendered template) contains "consolidat"
        is_consolidator = "consolidat" in body["messages"][0]["content"].lower()
        if is_consolidator:
            # One verdict per comment: KEEP all aggregated issues
            aggregated = json.loads(body["messages"][1]["content"])
            verdicts = {
                "issues": [
                    {"comment_id": i["comment_id"], "score": 7,
                     "suggested_action": "KEEP", "reason_for_suggested_action": "valid"}
                    for i in aggregated.get("issues", [])
                ]
            }
            content = json.dumps(verdicts)
        else:
            content = json.dumps(AGENT_RESPONSE)
        data = json.dumps({
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    # PDF with 3 single-paragraph blocks -> 3 chunks at paragraphs_per_chunk=1
    pdf = tmp_path_factory.mktemp("e2e") / "doc.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text(fitz.Point(72, 80), "You will recieve a confirmation email shortly.", fontsize=11)
    page.insert_text(fitz.Point(72, 110), "Please check teh document before signing.", fontsize=11)
    page.insert_text(fitz.Point(72, 140), "All parties agree to the terms described herein.", fontsize=11)
    doc.save(str(pdf))
    doc.close()

    envs = {
        "LLM_BASE_URL": f"http://127.0.0.1:{server.server_address[1]}/v1",
        "LLM_API_KEY": "test-key",
        "LLM_MODEL": "mock-large-model",
        "LLM_SHOTS": "2",           # 2 agent shots per type
        "LLM_MAX_WORKERS": "2",
        "PARAGRAPHS_PER_CHUNK": "1",
        "LLM_TRANSIENT_RETRIES": "2",
    }
    old = {k: os.environ.get(k) for k in envs}
    os.environ.update(envs)
    yield str(pdf)
    for k, v in old.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    server.shutdown()


def test_stream_review_end_to_end(env):
    from flows.ai_doc_review.engine import stream_review

    chunks = list(stream_review(env, paragraphs_per_chunk=1))
    # 3 paragraph chunks
    assert len(chunks) == 3

    all_issues = []
    for chunk in chunks:
        parsed = AllCombinedIssues.model_validate_json(chunk)
        all_issues.extend(parsed.issues)

    # The mock returns both issues for every agent call: per chunk the two
    # identical shots dedup to 2 unique issues, for each of the 2 issue types
    # -> 4 issues per chunk, 12 over 3 chunks.
    assert len(chunks) == 3
    texts = {issue.text for issue in all_issues}
    assert texts == {"recieve", "teh"}
    types = {issue.type for issue in all_issues}
    assert len(types) == 2  # Grammar & Spelling + Definitive Language (mock echoes both)
    assert len(all_issues) == 12
    # Consolidator verdicts merged in (score from mock)
    assert all(issue.suggested_action == "KEEP" and issue.score == 7 for issue in all_issues)
    # comment_ids assigned and unique per issue
    assert len({issue.comment_id for issue in all_issues}) == 12


def test_stream_review_requires_llm_config(tmp_path):
    from flows.ai_doc_review.config import PipelineConfig
    from flows.ai_doc_review.engine import stream_review

    pdf = tmp_path / "empty.pdf"
    doc = fitz.open()
    doc.new_page()
    doc.save(str(pdf))
    doc.close()

    # _env_file=None keeps a developer's real repo .env out of the assertion.
    cfg = PipelineConfig(_env_file=None, llm_base_url="", llm_api_key="", llm_model="")
    with pytest.raises(RuntimeError, match="LLM endpoint is not configured"):
        list(stream_review(str(pdf), config=cfg))
