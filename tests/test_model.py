"""End-to-end with the real default model. Downloads it once (~220 MB); opt in with
AGENTRECALL_TEST_MODEL=1 (and AGENTRECALL_TEST_MODEL_CACHE to reuse a download)."""

import os
from pathlib import Path

import pytest

from agentrecall import cli
from agentrecall.config import MODELS
from agentrecall.index import FastEmbedder

from conftest import BACKUP, MONITORING

pytestmark = [
    pytest.mark.model,
    pytest.mark.skipif(not os.environ.get("AGENTRECALL_TEST_MODEL"), reason="set AGENTRECALL_TEST_MODEL=1"),
]


@pytest.fixture(scope="module")
def real_embedder(tmp_path_factory):
    cache = os.environ.get("AGENTRECALL_TEST_MODEL_CACHE")
    path = Path(cache) if cache else tmp_path_factory.mktemp("models")
    return FastEmbedder(MODELS["multilingual-mini"].id, path, threads=2)


def first_session(out: str) -> str:
    return next(line.split()[1] for line in out.splitlines() if line.startswith("== "))


@pytest.mark.parametrize(
    "query, expected",
    [
        ("we replaced the broken status page with monitoring dashboards", MONITORING),
        ("Datensicherung jede Nacht", BACKUP),  # German, no shared words with the session
        ("nightly database backup", BACKUP),  # English query, German session
    ],
)
def test_finds_by_meaning(config_file, real_embedder, capsys, query, expected):
    cli.main([query], embedder=real_embedder)
    assert first_session(capsys.readouterr().out) == expected[:8]
