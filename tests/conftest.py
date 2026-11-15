"""Shared fixtures. Every test runs against a temp HOME, so nothing real is ever read."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import time
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

from sessionrecall import cli

FIXTURES = Path(__file__).parent / "fixtures"

WEBSHOP = "3f9a1c2e-5b7d-4e1f-9a2b-6c8d0e1f2a3b"
MONITORING = "7b2d4e6f-8a1c-4d3e-b5f7-0a2c4e6f8b1d"
BACKUP = "c41e8a90-2d6b-4f3a-8c5e-7f9b1d3a5c7e"
RATE_LIMIT = "0b7e5d21-6c3a-4f8e-9d1b-2a4c6e8f0a13"  # codex
MIGRATION = "5e2f8a40-1d3b-4c6a-8e9f-7b0c2d4e6a81"  # codex, early format, archived
WEBP = "ses_4c1a9e2b7ffeAbCdEfGhIjKlMn"  # opencode database
RSS = "ses_4b77c0e15ffeNoPqRsTuVwXyZa"  # opencode database, last reply still streaming
DARK_MODE = "ses_4d02a7c93ffeQrStUvWxYzAbCd"  # opencode json storage

# The columns of OpenCode's tables that the source reads.
OPENCODE_SCHEMA = """
create table session (id text primary key, project_id text not null, directory text not null,
  title text not null, time_created integer not null, time_updated integer not null);
create table message (id text primary key, session_id text not null, time_created integer not null,
  time_updated integer not null, data text not null);
create table part (id text primary key, message_id text not null, session_id text not null,
  time_created integer not null, time_updated integer not null, data text not null);
"""


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
    monkeypatch.delenv("SESSIONRECALL_CONFIG", raising=False)
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    monkeypatch.delenv("CODEX_HOME", raising=False)
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    return home


@pytest.fixture
def projects(tmp_path: Path) -> Path:
    """A writable copy of the fake Claude Code projects dir, each file's mtime at its last turn."""
    dest = tmp_path / "claude-projects"
    shutil.copytree(FIXTURES / "claude" / "projects", dest)
    for f in dest.glob("*/*.jsonl"):
        _mtime_at_last_turn(f)
    return dest


def _mtime_at_last_turn(f: Path) -> None:
    last = json.loads(f.read_text().splitlines()[-1])["timestamp"]
    mtime = datetime.fromisoformat(last.replace("Z", "+00:00")).timestamp()
    os.utime(f, (mtime, mtime))


@pytest.fixture
def codex_home(tmp_path: Path) -> Path:
    """A writable copy of the fake ~/.codex."""
    dest = tmp_path / "codex-home"
    shutil.copytree(FIXTURES / "codex", dest)
    for f in dest.rglob("*.jsonl"):
        _mtime_at_last_turn(f)
    return dest


def write_opencode_db(path: Path, rows: dict[str, list[dict]]) -> None:
    db = sqlite3.connect(path)
    db.executescript(OPENCODE_SCHEMA)
    for table, items in rows.items():
        for r in items:
            r = {k: json.dumps(v) if isinstance(v, dict) else v for k, v in r.items()}
            db.execute(f"insert into {table} ({','.join(r)}) values ({','.join('?' * len(r))})", list(r.values()))
    db.commit()
    db.close()


@pytest.fixture
def opencode_dir(tmp_path: Path) -> Path:
    """A fake ~/.local/share/opencode: opencode.db built from db.json, plus older JSON storage."""
    dest = tmp_path / "opencode-data"
    shutil.copytree(FIXTURES / "opencode" / "storage", dest / "storage")
    write_opencode_db(dest / "opencode.db", json.loads((FIXTURES / "opencode" / "db.json").read_text()))
    return dest


@pytest.fixture
def config_file(isolated_env: Path, projects: Path) -> Path:
    path = isolated_env / ".config" / "sessionrecall" / "config.toml"
    path.parent.mkdir(parents=True)
    path.write_text(f'[sources.claude]\npaths = ["{projects}"]\n')
    return path


@pytest.fixture
def all_agents(config_file: Path, codex_home: Path, opencode_dir: Path) -> Path:
    """Point the config at the fake Codex and OpenCode data too."""
    config_file.write_text(
        config_file.read_text()
        + f'[sources.codex]\nhome = "{codex_home}"\n[sources.opencode]\ndata_dir = "{opencode_dir}"\n'
    )
    return config_file


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
