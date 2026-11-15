"""On-disk state: the SQLite index of embedded chunks, and the list of forgotten sessions.

The index keeps its own copy of the text, so search still finds sessions whose
transcript was deleted since (`--show` cannot print those any more).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

SCHEMA = """
create table if not exists meta (key text primary key, value text);
create table if not exists files (path text primary key, source text, sid text, offset integer);
create table if not exists chunks (path text, source text, sid text, ts text, role text, text text, vec blob);
create index if not exists chunks_path on chunks(path);
create index if not exists chunks_sid on chunks(sid);
"""


@dataclass(frozen=True)
class Chunk:
    path: str
    source: str
    sid: str
    ts: str
    role: str
    text: str
    vec: bytes = b""


class Store:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.db = sqlite3.connect(path, timeout=30)
        self.db.execute("pragma journal_mode=wal")
        self.db.executescript(SCHEMA)

    def close(self) -> None:
        self.db.close()

    def ensure_signature(self, signature: str) -> bool:
        """Drop all vectors if they were made by another model or chunking. True if it did."""
        row = self.db.execute("select value from meta where key='signature'").fetchone()
        if row and row[0] == signature:
            return False
        had_data = row is not None
        self.db.execute("delete from chunks")
        self.db.execute("delete from files")
        self.db.execute("insert or replace into meta values ('signature', ?)", (signature,))
        self.db.commit()
        return had_data

    def offsets(self) -> dict[str, int]:
        return dict(self.db.execute("select path, offset from files"))

    def add(self, chunks: Iterable[Chunk]) -> None:
        self.db.executemany(
            "insert into chunks values (?,?,?,?,?,?,?)",
            [(c.path, c.source, c.sid, c.ts, c.role, c.text, c.vec) for c in chunks],
        )

    def set_offset(self, path: str, source: str, sid: str, offset: int) -> None:
        self.db.execute("insert or replace into files values (?,?,?,?)", (path, source, sid, offset))

    def reset_file(self, path: str) -> None:
        self.db.execute("delete from chunks where path=?", (path,))
        self.db.execute("delete from files where path=?", (path,))

    def commit(self) -> None:
        self.db.commit()

    def chunks(self) -> list[Chunk]:
        return [Chunk(*row) for row in self.db.execute("select * from chunks")]

    def drop_session(self, sid: str) -> None:
        """Remove a session's chunks; its file stays marked as read, so nothing comes back."""
        self.db.execute("delete from chunks where sid=?", (sid,))
        self.db.commit()

    def unread_session(self, sid: str) -> None:
        """Forget how far a session was read, so the next index run embeds it again."""
        self.db.execute("delete from chunks where sid=?", (sid,))
        self.db.execute("delete from files where sid=?", (sid,))
        self.db.commit()

    @contextmanager
    def writer_lock(self) -> Iterator[bool]:
        """Yield True if this process may index now, False if another one already is."""
        with (self.path.parent / "index.lock").open("w") as f:
            yield _try_lock(f)


def _try_lock(f) -> bool:
    try:
        import fcntl
    except ImportError:  # Windows
        import msvcrt

        try:
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except BlockingIOError:
        return False


class Forgotten:
    """Session ids hidden from every recall mode, one per line in a plain text file."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def ids(self) -> set[str]:
        try:
            return set(self.path.read_text().split())
        except FileNotFoundError:
            return set()

    def save(self, ids: set[str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("".join(f"{i}\n" for i in sorted(ids)))
