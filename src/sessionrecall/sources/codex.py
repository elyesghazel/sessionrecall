"""Codex CLI: one JSONL "rollout" per session under ~/.codex/sessions/YYYY/MM/DD/.

Each line is `{"timestamp", "type", "payload"}`. The first is `session_meta` (id, cwd);
what was said is in `response_item` lines whose payload is a `message` from the user or
the assistant. Tool calls, reasoning, developer messages and token counts are skipped,
and so is the context Codex injects into user messages (AGENTS.md, environment).
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from sessionrecall.sources.base import Session, Source, Turn, read_new_lines, tilde

# rollout-2026-01-05T09-00-00-<session uuid>[_<window uuid>].jsonl
FILENAME = re.compile(r"rollout-\d{4}-\d\d-\d\dT\d\d-\d\d-\d\d-([0-9a-fA-F-]{36})")
NOISE = re.compile(
    r"<(environment_context|user_instructions|turn_aborted|user_shell_command)>.*?</\1>"
    r"|# AGENTS\.md instructions for [^\n]*\n.*?</INSTRUCTIONS>",
    re.S,
)
TEXT_BLOCKS = {"input_text", "output_text", "text"}


def default_home() -> Path:
    base = os.environ.get("CODEX_HOME")
    return Path(base) if base else Path.home() / ".codex"


def text_of(content: Any) -> str:
    if isinstance(content, str):
        parts = [content]
    elif isinstance(content, list):
        parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") in TEXT_BLOCKS]
    else:
        parts = []
    return NOISE.sub("", "\n".join(parts)).strip()


def parse_line(line: str) -> Turn | None:
    """A Turn for a user/assistant message line; None for everything else."""
    try:
        entry = json.loads(line)
    except ValueError:
        return None
    if not isinstance(entry, dict):
        return None
    # Current rollouts wrap items in a payload; early ones wrote the item itself.
    item = entry.get("payload") if entry.get("type") == "response_item" else entry
    if not isinstance(item, dict) or item.get("type") != "message":
        return None
    role = item.get("role")
    if role not in ("user", "assistant"):
        return None
    text = text_of(item.get("content"))
    return Turn(entry.get("timestamp", ""), role, text) if text else None


def read_meta(path: Path) -> dict[str, Any]:
    """The session_meta payload from the first line, or {}."""
    try:
        with path.open(errors="replace") as f:
            entry = json.loads(f.readline())
    except (OSError, ValueError):
        return {}
    if not isinstance(entry, dict):
        return {}
    meta = entry.get("payload") if entry.get("type") == "session_meta" else entry
    return meta if isinstance(meta, dict) else {}


class CodexSource(Source):
    name = "codex"

    def __init__(self, home: Path | None = None) -> None:
        self.home = home or default_home()

    @classmethod
    def from_config(cls, options: dict[str, Any]) -> CodexSource:
        home = options.get("home")
        return cls(Path(os.path.expanduser(home)) if home else None)

    def available(self) -> bool:
        return (self.home / "sessions").is_dir()

    def files(self) -> Iterator[Path]:
        yield from (self.home / "sessions").glob("*/*/*/rollout-*.jsonl")
        yield from (self.home / "archived_sessions").glob("rollout-*.jsonl")

    def sessions(self) -> Iterator[Session]:
        for f in self.files():
            m = FILENAME.match(f.name)
            sid = m.group(1) if m else str(read_meta(f).get("id") or f.stem)
            st = f.stat()
            yield Session(self.name, sid, f, st.st_mtime, st.st_size)

    def turns(self, path: Path, offset: int = 0) -> tuple[list[Turn], int]:
        lines, end = read_new_lines(path, offset)
        return [t for line in lines if (t := parse_line(line))], end

    def project(self, path: Path) -> str:
        cwd = read_meta(path).get("cwd")
        return tilde(cwd) if isinstance(cwd, str) and cwd else "codex"

    def current_session_id(self) -> str | None:
        return os.environ.get("CODEX_THREAD_ID")
