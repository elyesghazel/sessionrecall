"""Claude Code: one JSONL transcript per session under ~/.claude/projects/<project>/<id>.jsonl."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from agentrecall.sources.base import Session, Source, Turn, read_new_lines, tilde

# Context the harness injects into user turns; not something anyone said.
NOISE = re.compile(
    r"<(system-reminder|local-command-caveat|command-message|command-args)>.*?</\1>", re.S
)


def default_projects_dir() -> Path:
    base = os.environ.get("CLAUDE_CONFIG_DIR")
    return (Path(base) if base else Path.home() / ".claude") / "projects"


def text_of(message: dict[str, Any]) -> str:
    """The plain text of a message: string content or its text blocks (tool calls skipped)."""
    content = message.get("content")
    if isinstance(content, str):
        parts = [content]
    elif isinstance(content, list):
        parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
    else:
        parts = []
    return NOISE.sub("", "\n".join(parts)).strip()


def parse_line(line: str) -> Turn | None:
    """A Turn for a real user/assistant line; None for tool results, meta lines and the rest."""
    try:
        entry = json.loads(line)
    except ValueError:
        return None
    if not isinstance(entry, dict):
        return None
    role = entry.get("type")
    if role not in ("user", "assistant") or entry.get("isMeta"):
        return None
    text = text_of(entry.get("message") or {})
    return Turn(entry.get("timestamp", ""), role, text) if text else None


class ClaudeCodeSource(Source):
    name = "claude"

    def __init__(self, paths: list[Path] | None = None) -> None:
        self.paths = paths or [default_projects_dir()]

    @classmethod
    def from_config(cls, options: dict[str, Any]) -> ClaudeCodeSource:
        paths = options.get("paths")
        if isinstance(paths, str):
            paths = [paths]
        return cls([Path(os.path.expanduser(p)) for p in paths] if paths else None)

    def available(self) -> bool:
        return any(p.is_dir() for p in self.paths)

    def sessions(self) -> Iterator[Session]:
        for root in self.paths:
            for f in root.glob("*/*.jsonl"):
                st = f.stat()
                yield Session(self.name, f.stem, f, st.st_mtime, st.st_size)

    def turns(self, path: Path, offset: int = 0) -> tuple[list[Turn], int]:
        lines, end = read_new_lines(path, offset)
        return [t for line in lines if (t := parse_line(line))], end

    def project(self, path: Path) -> str:
        """The session's cwd; the folder name is only a lossy encoding of it."""
        with path.open(errors="replace") as f:
            for i, line in enumerate(f):
                if i > 50:
                    break
                if '"cwd"' not in line:
                    continue
                try:
                    cwd = json.loads(line).get("cwd")
                except ValueError:
                    continue
                if cwd:
                    return tilde(cwd)
        return path.parent.name

    def current_session_id(self) -> str | None:
        return os.environ.get("CLAUDE_CODE_SESSION_ID")
