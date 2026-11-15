"""Shared fixtures. Every test runs against a temp HOME, so nothing real is ever read."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

from agentrecall import cli

FIXTURES = Path(__file__).parent / "fixtures"

WEBSHOP = "3f9a1c2e-5b7d-4e1f-9a2b-6c8d0e1f2a3b"
MONITORING = "7b2d4e6f-8a1c-4d3e-b5f7-0a2c4e6f8b1d"
BACKUP = "c41e8a90-2d6b-4f3a-8c5e-7f9b1d3a5c7e"


class HashEmbedder:
    """Bag of words hashed into a fixed vector: deterministic, instant, no download.

    It only knows shared words, not meaning, which is enough to test the pipeline.
    """

    dim = 4096

    def __init__(self) -> None:
        self.calls = 0

    def _vec(self, text: str) -> np.ndarray:
        v = np.zeros(self.dim, dtype=np.float32)
        for word in re.findall(r"\w+", text.lower()):
            v[int(hashlib.sha1(word.encode()).hexdigest(), 16) % self.dim] += 1
        n = np.linalg.norm(v)
        return v / n if n else v

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        self.calls += len(texts)
        return np.stack([self._vec(t) for t in texts]) if texts else np.zeros((0, self.dim), np.float32)

    def embed_query(self, text: str) -> np.ndarray:
        return self._vec(text)


@pytest.fixture(autouse=True)
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(home / ".cache"))
    monkeypatch.setenv("XDG_STATE_HOME", str(home / ".local/state"))
    monkeypatch.delenv("AGENTRECALL_CONFIG", raising=False)
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    return home


@pytest.fixture
def projects(tmp_path: Path) -> Path:
    """A writable copy of the fake Claude Code projects dir, each file's mtime at its last turn."""
    dest = tmp_path / "claude-projects"
    shutil.copytree(FIXTURES / "claude" / "projects", dest)
    for f in dest.glob("*/*.jsonl"):
        last = json.loads(f.read_text().splitlines()[-1])["timestamp"]
        mtime = datetime.fromisoformat(last.replace("Z", "+00:00")).timestamp()
        os.utime(f, (mtime, mtime))
    return dest


@pytest.fixture
def config_file(isolated_env: Path, projects: Path) -> Path:
    path = isolated_env / ".config" / "agentrecall" / "config.toml"
    path.parent.mkdir(parents=True)
    path.write_text(f'[sources.claude]\npaths = ["{projects}"]\n')
    return path


@pytest.fixture
def embedder() -> HashEmbedder:
    return HashEmbedder()


@pytest.fixture
def recall(config_file: Path, embedder: HashEmbedder, capsys: pytest.CaptureFixture[str]) -> Callable[..., str]:
    """Run the CLI against the fixture corpus and return its stdout."""

    def run(*argv: str) -> str:
        cli.main(list(argv), embedder=embedder)
        return capsys.readouterr().out

    return run
