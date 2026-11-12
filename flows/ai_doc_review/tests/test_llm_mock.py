"""LLM client tests against a mock OpenAI-compatible HTTP service.

Verifies (plan §10): request body shape, json_schema -> json_object fallback,
429 exponential-backoff retries, JSON-validation retry, usage accounting —
all without consuming real tokens."""

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from common.models import AllSingleShotIssues

VALID_ISSUES = {
    "issues": [{
        "type": "Grammar & Spelling",
        "text": "recieve",
        "explanation": "misspelled",
        "suggested_fix": "receive",
        "location": {"source_sentence": "You will recieve a confirmation.",
                     "page_num": 0, "bounding_box": [], "para_index": 0},
        "comment_id": "",
    }]
}


class MockOpenAIHandler(BaseHTTPRequestHandler):
    """State-driven stub: state dict controls behaviour per test."""

    state = {
        "mode": "ok",                # ok | reject_schema | flaky_429 | bad_json_once | echo_request
        "requests": [],
        "last_body": None,
        "reject_schema_seen": False,
        "429_count": 0,
        "bad_json_done": False,
    }

    def log_message(self, *args):  # silence test noise
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        self.state["requests"].append(body)
        self.state["last_body"] = body

        response_format = body.get("response_format", {})

        if self.state["mode"] == "reject_schema" and response_format.get("type") == "json_schema":
            self.state["reject_schema_seen"] = True
            self._send(400, {"error": {"message": "response_format type json_schema is not supported"}})
            return

        if self.state["mode"] == "flaky_429" and self.state["429_count"] < 2:
            self.state["429_count"] += 1
            self._send(429, {"error": {"message": "rate limited"}})
            return

        content = json.dumps(VALID_ISSUES)
        if self.state["mode"] == "bad_json_once" and not self.state["bad_json_done"]:
            self.state["bad_json_done"] = True
            content = "this is definitely not json at all"
        if self.state["mode"] == "echo_request":
            content = json.dumps({"echo": body})

        self._send(200, {
            "id": "chatcmpl-mock", "object": "chat.completion", "model": body.get("model"),
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": 120, "completion_tokens": 45, "total_tokens": 165},
        })

    def _send(self, status: int, payload: dict):
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture(scope="module")
def mock_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), MockOpenAIHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}/v1"
    yield base_url
    server.shutdown()


def make_config(base_url: str, **overrides):
    from flows.ai_doc_review.config import PipelineConfig

    defaults = dict(
        LLM_BASE_URL=base_url, LLM_API_KEY="test-key", LLM_MODEL="mock-large-model",
        LLM_SHOTS="1", LLM_MAX_WORKERS="1", LLM_TRANSIENT_RETRIES="4",
    )
    defaults.update({k: str(v) for k, v in overrides.items()})
    old = {k: os.environ.get(k) for k in defaults}
    os.environ.update(defaults)
    yield PipelineConfig()
    for k, v in old.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


@pytest.fixture()
def reset_state():
    MockOpenAIHandler.state.update(
        mode="ok", requests=[], last_body=None,
        reject_schema_seen=False, **{"429_count": 0}, bad_json_done=False,
    )
    yield
    MockOpenAIHandler.state["mode"] = "ok"


def test_ok_request_body_and_usage(mock_server, reset_state):
    from flows.ai_doc_review.llm import LLMClient

    config = next(make_config(mock_server))
    client = LLMClient(config)
    result = client.complete_json("system prompt", "user text", AllSingleShotIssues)

    assert len(result.issues) == 1
    assert result.issues[0].text == "recieve"
    body = MockOpenAIHandler.state["last_body"]
    assert body["model"] == "mock-large-model"
    assert body["messages"][0] == {"role": "system", "content": "system prompt"}
    assert body["messages"][1] == {"role": "user", "content": "user text"}
    assert body["response_format"]["type"] == "json_schema"
    schema = body["response_format"]["json_schema"]["schema"]
    assert "issues" in schema.get("properties", {}) and "issues" in schema.get("required", [])
    assert client.total_prompt_tokens == 120 and client.total_completion_tokens == 45


def test_json_schema_rejected_falls_back(mock_server, reset_state):
    from flows.ai_doc_review.llm import LLMClient

    MockOpenAIHandler.state["mode"] = "reject_schema"
    config = next(make_config(mock_server))
    client = LLMClient(config)
    result = client.complete_json("s", "u", AllSingleShotIssues)

    assert len(result.issues) == 1
    assert MockOpenAIHandler.state["reject_schema_seen"]
    # Second call must not attempt json_schema again
    client.complete_json("s", "u", AllSingleShotIssues)
    types = [b["response_format"]["type"] for b in MockOpenAIHandler.state["requests"]]
    assert "json_schema" in types and types[-1] == "json_object"
    # Schema hint injected for json_object mode
    sys_content = MockOpenAIHandler.state["last_body"]["messages"][0]["content"]
    assert "JSON schema" in sys_content


def test_429_backoff_retries_then_succeeds(mock_server, reset_state):
    from flows.ai_doc_review.llm import LLMClient

    MockOpenAIHandler.state["mode"] = "flaky_429"
    config = next(make_config(mock_server))
    client = LLMClient(config)
    result = client.complete_json("s", "u", AllSingleShotIssues)
    assert len(result.issues) == 1
    statuses_429 = sum(
        1 for _ in range(MockOpenAIHandler.state["429_count"]))
    assert statuses_429 == 2  # two 429s before the 200


def test_invalid_json_retried_with_correction(mock_server, reset_state):
    from flows.ai_doc_review.llm import LLMClient

    MockOpenAIHandler.state["mode"] = "bad_json_once"
    config = next(make_config(mock_server, LLM_MAX_RETRIES=2))
    client = LLMClient(config)
    result = client.complete_json("s", "u", AllSingleShotIssues)
    assert len(result.issues) == 1
    roles = [m["role"] for m in MockOpenAIHandler.state["last_body"]["messages"]]
    assert roles == ["system", "user", "assistant", "user"]  # correction appended
    assert "not valid JSON" in MockOpenAIHandler.state["last_body"]["messages"][-1]["content"]


def test_hard_json_failure_raises_llm_error(mock_server, reset_state):
    from flows.ai_doc_review.llm import LLMClient, LLMError

    class AlwaysBadHandler(MockOpenAIHandler):
        pass

    # Reuse the same server but force persistent bad JSON via echo mode is not
    # applicable; instead simulate by pointing at a mode that stays broken.
    MockOpenAIHandler.state["mode"] = "echo_request"  # returns {"echo": ...} -> fails validation
    config = next(make_config(mock_server, LLM_MAX_RETRIES=0))
    client = LLMClient(config)
    with pytest.raises(LLMError):
        client.complete_json("s", "u", AllSingleShotIssues)
