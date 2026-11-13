"""Guard the .env contract that broke container startup.

`docker run --env-file` (and compose's env_file) pass values verbatim: an
inline comment is *part of the value*, so `LLM_MAX_WORKERS=8  # cap` becomes the
string "8  # cap" and Pydantic refuses to parse it. Comments must be on their
own line.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
ENV_EXAMPLE = REPO_ROOT / ".env.example"
INLINE_COMMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=\S.*\s{2,}#")


def test_env_example_has_no_inline_comments():
    offenders = [
        line for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
        if INLINE_COMMENT.match(line)
    ]
    assert not offenders, f"move these comments to their own line: {offenders}"


def test_pipeline_config_reads_env_example_defaults():
    """Every documented key must be a real Settings field, so a typo in
    .env.example cannot silently do nothing."""
    from config.config import Settings
    from flows.ai_doc_review.config import PipelineConfig

    known = set(PipelineConfig.model_fields) | set(Settings.model_fields)
    keys = {
        line.split("=", 1)[0].strip().lower()
        for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
        if "=" in line and not line.strip().startswith("#")
    }
    unknown = {key for key in keys if key not in known}
    assert not unknown, f".env.example documents unknown keys: {sorted(unknown)}"


@pytest.mark.parametrize("key,expected", [
    ("llm_max_workers", 8),
    ("chunk_max_workers", 2),
    ("consolidator_batch_size", 10),
])
def test_defaults_match_documented_tuning(key, expected):
    """Defaults are the documented ones even without a .env file."""
    from flows.ai_doc_review.config import PipelineConfig

    assert getattr(PipelineConfig(_env_file=None), key) == expected
