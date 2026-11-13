"""Phase A regression tests: local backend skeleton.

Covers: degraded health without LLM config, local JWT auth, document CRUD
with path-traversal protection, review SSE error isolation.

Run:  pytest app/api/tests/test_phase_a_smoke.py   (from repo root)
"""

import os
import sys
import tempfile
from pathlib import Path

# Isolated data dir must be set before config is imported. LLM_* is blanked on
# purpose: a developer's real .env must never leak into these assertions.
_tmp = tempfile.mkdtemp(prefix="adr-test-")
os.environ.update(
    DATA_DIR=_tmp,
    AUTH_DISABLED="false",
    ADMIN_USERNAME="admin",
    ADMIN_PASSWORD="admin123",
    JWT_SECRET="test-secret-not-for-production",
    LLM_BASE_URL="",
    LLM_API_KEY="",
    LLM_MODEL="",
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT))  # `common` package
sys.path.insert(0, str(_REPO_ROOT / "app" / "api"))  # flat app/api imports

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from main import app  # noqa: E402

PDF_BYTES = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"


@pytest.fixture(scope="module")
def client():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture(scope="module")
def auth(client):
    resp = client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_health_degraded_without_llm(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["llm_configured"] is False


def test_auth_config(client):
    resp = client.get("/api/v1/auth/config")
    assert resp.status_code == 200
    assert resp.json() == {"auth_disabled": False}


def test_documents_require_auth(client):
    assert client.get("/api/v1/documents").status_code == 401


def test_login_rejects_bad_password(client):
    resp = client.post("/api/v1/auth/login", json={"username": "admin", "password": "wrong"})
    assert resp.status_code == 401


def test_me_returns_oid(client, auth):
    resp = client.get("/api/v1/auth/me", headers=auth)
    assert resp.status_code == 200
    assert resp.json()["oid"]


def test_upload_rejects_non_pdf(client, auth):
    resp = client.post(
        "/api/v1/documents", headers=auth,
        files={"file": ("evil.pdf", b"not a pdf", "application/pdf")},
    )
    assert resp.status_code == 400


def test_upload_rejects_path_traversal(client, auth):
    resp = client.post(
        "/api/v1/documents", headers=auth,
        files={"file": ("../evil.pdf", PDF_BYTES, "application/pdf")},
    )
    assert resp.status_code == 400


def test_document_lifecycle(client, auth):
    resp = client.post(
        "/api/v1/documents", headers=auth,
        files={"file": ("sample.pdf", PDF_BYTES, "application/pdf")},
    )
    assert resp.status_code == 201 and resp.json()["name"] == "sample.pdf"

    resp = client.get("/api/v1/documents", headers=auth)
    assert resp.status_code == 200 and len(resp.json()) == 1

    resp = client.get("/api/v1/documents/sample.pdf/file", headers=auth)
    assert resp.status_code == 200 and resp.content.startswith(b"%PDF")

    # Overwrite same name is allowed (Blob overwrite semantics)
    resp = client.post(
        "/api/v1/documents", headers=auth,
        files={"file": ("sample.pdf", PDF_BYTES, "application/pdf")},
    )
    assert resp.status_code == 201

    resp = client.delete("/api/v1/documents/sample.pdf", headers=auth)
    assert resp.status_code == 204
    assert client.get("/api/v1/documents", headers=auth).json() == []


def test_download_rejects_traversal(client, auth):
    resp = client.get("/api/v1/documents/../config.py/file", headers=auth)
    assert resp.status_code in (400, 404)


def test_review_streams_error_without_llm(client, auth):
    client.post(
        "/api/v1/documents", headers=auth,
        files={"file": ("sample.pdf", PDF_BYTES, "application/pdf")},
    )
    resp = client.get("/api/v1/review/sample.pdf/issues", headers=auth)
    assert resp.status_code == 200
    assert "event: error" in resp.text
    assert "LLM endpoint is not configured" in resp.text
    client.delete("/api/v1/documents/sample.pdf", headers=auth)


def test_logout(client, auth):
    assert client.post("/api/v1/auth/logout", headers=auth).status_code == 204


def test_no_internal_echo_on_error(client):
    resp = client.post("/api/v1/auth/login", json={"username": None})
    assert "Traceback" not in resp.text
