"""OpenCode: sessions in ~/.local/share/opencode, as SQLite (current) or JSON files (older).

Current versions keep everything in `opencode.db` (`opencode-<channel>.db` on preview
channels): a `session` table, a `message` table (`data` JSON with `role` and `time`) and a
`part` table (`data` JSON, the `text` parts are what was said). Older versions wrote the
same records as files:

    storage/session/<project>/<session>.json
    storage/message/<session>/<message>.json
    storage/part/<message>/<part>.json

Either way a session's cursor is the number of messages read. A reply still being
written (the last message, not completed yet) is left for the next run. Tool calls,
reasoning and synthetic parts OpenCode adds itself are skipped.
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agentrecall.sources.base import Session, Source, Turn, tilde


def default_data_dir() -> Path:
    base = os.environ.get("XDG_DATA_HOME")
    return (Path(base) if base else Path.home() / ".local" / "share") / "opencode"


def iso(ms: Any) -> str:
    if not isinstance(ms, (int, float)):
        return ""
    return datetime.fromtimestamp(ms / 1000, UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class _Message:
    role: str
    created: Any
    done: bool
    parts: list[dict[str, Any]]


def _loads(data: str | bytes) -> dict[str, Any]:
    try:
        value = json.loads(data)
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def _message(info: dict[str, Any], parts: list[dict[str, Any]]) -> _Message:
    time = info.get("time") or {}
    done = info.get("role") != "assistant" or bool(time.get("completed") or info.get("error"))
    return _Message(str(info.get("role", "")), time.get("created"), done, parts)


def _turns(messages: list[_Message], offset: int) -> tuple[list[Turn], int]:
    out, end = [], offset
    for i, m in enumerate(messages[offset:], offset):
        if not m.done and i == len(messages) - 1:
            break  # still streaming
        end = i + 1
        if m.role not in ("user", "assistant"):
            continue
        text = "\n".join(
            p.get("text", "")
            for p in m.parts
            if p.get("type") == "text" and not p.get("synthetic") and not p.get("ignored")
        ).strip()
        if text:
            out.append(Turn(iso(m.created), m.role, text))  # type: ignore[arg-type]
    return out, end


class OpenCodeSource(Source):
    name = "opencode"

    def __init__(self, data_dir: Path | None = None) -> None:
        self.data_dir = data_dir or default_data_dir()

    @classmethod
    def from_config(cls, options: dict[str, Any]) -> OpenCodeSource:
        path = options.get("data_dir")
        return cls(Path(os.path.expanduser(path)) if path else None)

    @property
    def storage(self) -> Path:
        return self.data_dir / "storage"

    def databases(self) -> list[Path]:
        return sorted(self.data_dir.glob("opencode*.db"))

    def available(self) -> bool:
        return bool(self.databases()) or (self.storage / "session").is_dir()

    # A database session's path is <db>/<session id>; a file session's is its info file.
    def _is_db(self, path: Path) -> bool:
        return path.parent.suffix == ".db"

    def _connect(self, db: Path) -> sqlite3.Connection:
        return sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=10)

    def sessions(self) -> Iterator[Session]:
        for db in self.databases():
            try:
                con = self._connect(db)
                rows = con.execute(
                    "select s.id, s.time_updated, count(m.id) from session s"
                    " left join message m on m.session_id = s.id group by s.id"
                ).fetchall()
                con.close()
            except sqlite3.Error:
                continue
            for sid, updated, count in rows:
                yield Session(self.name, sid, db / sid, (updated or 0) / 1000, count)
        for f in self.storage.glob("session/*/*.json"):
            sid = f.stem
            msgs = self.storage / "message" / sid
            count = sum(1 for _ in msgs.glob("*.json"))
            updated = (_loads(f.read_bytes()).get("time") or {}).get("updated")
            mtime = updated / 1000 if isinstance(updated, (int, float)) else f.stat().st_mtime
            yield Session(self.name, sid, f, mtime, count)

    def _messages(self, path: Path) -> list[_Message]:
        if self._is_db(path):
            con = self._connect(path.parent)
            try:
                msgs = con.execute(
                    "select id, data from message where session_id = ? order by time_created, id", (path.name,)
                ).fetchall()
                parts: dict[str, list[dict[str, Any]]] = {}
                for mid, data in con.execute(
                    "select message_id, data from part where session_id = ? order by time_created, id", (path.name,)
                ):
                    parts.setdefault(mid, []).append(_loads(data))
            finally:
                con.close()
            return [_message(_loads(data), parts.get(mid, [])) for mid, data in msgs]
        infos = [_loads(f.read_bytes()) for f in (self.storage / "message" / path.stem).glob("*.json")]
        infos.sort(key=lambda m: ((m.get("time") or {}).get("created") or 0, str(m.get("id", ""))))
        out = []
        for info in infos:
            files = sorted((self.storage / "part" / str(info.get("id", ""))).glob("*.json"))
            out.append(_message(info, [_loads(p.read_bytes()) for p in files]))
        return out

    def turns(self, path: Path, offset: int = 0) -> tuple[list[Turn], int]:
        try:
            return _turns(self._messages(path), offset)
        except (OSError, sqlite3.Error):
            return [], offset

    def _info(self, path: Path) -> dict[str, Any]:
        if not self._is_db(path):
            return _loads(path.read_bytes()) if path.exists() else {}
        try:
            con = self._connect(path.parent)
            row = con.execute("select directory from session where id = ?", (path.name,)).fetchone()
            con.close()
        except sqlite3.Error:
            return {}
        return {"directory": row[0]} if row else {}

    def exists(self, path: Path) -> bool:
        return bool(self._info(path)) if self._is_db(path) else path.exists()

    def project(self, path: Path) -> str:
        directory = self._info(path).get("directory")
        return tilde(directory) if isinstance(directory, str) and directory else "opencode"
