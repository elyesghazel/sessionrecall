"""The interface every session source implements.

A source knows where one agent keeps its transcripts and how to read them. The rest of
recall only sees `Session` and `Turn`, so adding an agent means adding one module here.

Indexing is incremental: `turns(path, offset)` returns the turns after `offset` plus a
new offset to resume from next time. For append-only files the offset is a byte position
and `Session.size` is the file size; a source with another storage format may use any
integer cursor that grows as the session grows.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, Literal

Role = Literal["user", "assistant"]


@dataclass(frozen=True)
class Turn:
    ts: str  # ISO 8601 timestamp, UTC or with an offset
    role: Role
    text: str


@dataclass(frozen=True)
class Session:
    source: str  # Source.name
    id: str
    path: Path
    mtime: float
    size: int  # the offset `turns` returns once everything is read


class Source(ABC):
    name: ClassVar[str]

    @classmethod
    def from_config(cls, options: dict[str, Any]) -> Source:
        """Build the source from its `[sources.<name>]` table."""
        return cls()

    def available(self) -> bool:
        """Whether the agent looks installed here; auto-detection enables it if so."""
        return True

    @abstractmethod
    def sessions(self) -> Iterator[Session]:
        """Every session on disk, in any order."""

    @abstractmethod
    def turns(self, path: Path, offset: int = 0) -> tuple[list[Turn], int]:
        """User and assistant turns after `offset`, and the offset to resume from."""

    def project(self, path: Path) -> str:
        """A short label for where the session ran, usually its working directory."""
        return path.parent.name

    def exists(self, path: Path) -> bool:
        """Whether the session's transcript is still there (it may live inside a database)."""
        return path.exists()

    def current_session_id(self) -> str | None:
        """The session recall is being run from, if any; it is left out of results."""
        return None


def tilde(path: str) -> str:
    """`path` with the home directory written as ~."""
    home = str(Path.home())
    if path == home or path.startswith(home + os.sep):
        return "~" + path[len(home):]
    return path


def read_new_lines(path: Path, offset: int) -> tuple[list[str], int]:
    """Complete lines after byte `offset`, and the offset after the last complete line.

    A line still being written (no trailing newline yet) is left for the next run.
    """
    with path.open("rb") as f:
        f.seek(offset)
        data = f.read()
    end = data.rfind(b"\n") + 1
    return data[:end].decode(errors="replace").splitlines(), offset + end


def short_id(sid: str) -> str:
    """The id as shown in results: 8 characters, after a type prefix like OpenCode's `ses_`."""
    return sid.split("_", 1)[-1][:8]


def id_matches(sid: str, prefix: str) -> bool:
    """Whether `prefix` starts the id, or the id after its type prefix."""
    return sid.startswith(prefix) or sid.split("_", 1)[-1].startswith(prefix)
