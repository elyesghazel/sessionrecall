"""The three agent-facing operations behind `recall mcp`: search, list_sessions, show_session.

They reuse the CLI's commands and capture what those print, so an agent sees exactly
what a person would, redacted the same way, but cut to a size that fits in a context
window. This module needs no MCP SDK; `agentrecall.mcp_server` wraps it.
"""

from __future__ import annotations

import io
import re
import threading
from collections.abc import Callable
from dataclasses import replace
from functools import cached_property

from agentrecall.cli import App
from agentrecall.config import Config, load_config
from agentrecall.index import Embedder, FastEmbedder
from agentrecall.redact import RedactingWriter, redact
from agentrecall.search import Filters
from agentrecall.store import Store
from agentrecall.timeutil import DateFilter

MAX_CHARS = 12_000  # hard cap on one tool result
SEARCH_LIMIT, LIST_LIMIT, EXACT_LIMIT = 5, 20, 20
DIGEST_CHARS = 600  # per turn in show_session unless full=True


class ToolError(Exception):
    """A problem the calling agent can fix (bad id, unknown agent, bad date)."""


class _SourceStore:
    """A Store view that only returns one source's chunks."""

    def __init__(self, store: Store, source: str) -> None:
        self._store, self._source = store, source

    def chunks(self):
        return [c for c in self._store.chunks() if c.source == self._source]

    def __getattr__(self, name: str):
        return getattr(self._store, name)


class _AgentApp(App):
    def __init__(self, config: Config, out, embedder: Embedder, agent: str | None) -> None:
        super().__init__(config, out, embedder)
        self.agent = agent

    @cached_property
    def store(self):
        store = super().store
        return _SourceStore(store, self.agent) if self.agent else store


class Tools:
    """One instance per server; each call builds a fresh App (SQLite is per thread)."""

    def __init__(self, config: Config | None = None, embedder: Embedder | None = None) -> None:
        self.config = config or load_config()
        self._embedder = embedder
        self._lock = threading.Lock()  # one call at a time: the model and the index are shared

    @cached_property
    def embedder(self) -> Embedder:
        c = self.config
        return self._embedder or FastEmbedder(c.model_id, c.models_dir, c.threads)

    def agents(self) -> list[str]:
        return [n for n, opts in self.config.sources.items() if opts.get("enabled", True)]

    def _run(self, agent: str | None, body: Callable[[App], None]) -> str:
        if agent:
            if agent not in self.agents():
                raise ToolError(f"unknown agent {agent!r}, configured: {', '.join(self.agents())}")
            config = replace(self.config, sources={agent: self.config.sources[agent]})
        else:
            config = self.config
        buf = io.StringIO()
        with self._lock:
            app = _AgentApp(config, RedactingWriter(buf), self.embedder, agent)
            try:
                body(app)
            except SystemExit as e:  # the CLI's way of saying "nothing found" and the like
                if e.code not in (None, 0):
                    buf.write(f"{e.code}\n")
            finally:
                if "store" in app.__dict__:
                    app.store.close()
        return redact(buf.getvalue()).strip()

    # --- the tools ----------------------------------------------------------------

    def search(
        self,
        query: str,
        agent: str | None = None,
        exact: bool = False,
        since_days: int | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        role: str | None = None,
        limit: int | None = None,
    ) -> str:
        terms = query.split()
        if not terms:
            raise ToolError("query is empty")
        if role not in (None, "user", "assistant"):
            raise ToolError("role must be 'user' or 'assistant'")
        dates = _dates(since_days, date_from, date_to)

        def body(app: App) -> None:
            exclude = app.forgotten.ids() | ({app.current_session} if app.current_session else set())
            filters = Filters(dates, role, frozenset(exclude))
            if exact:
                app.exact([re.compile(re.escape(t), re.I) for t in terms], filters, _clamp(limit, EXACT_LIMIT, 100))
            else:
                app.semantic(terms, filters, _clamp(limit, SEARCH_LIMIT, 20))

        return _cap(self._run(agent, body))

    def list_sessions(
        self,
        agent: str | None = None,
        since_days: int | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        exclude: str | None = None,
        limit: int | None = None,
    ) -> str:
        dates = _dates(since_days, date_from, date_to)
        if exclude:
            _regex(exclude)
        return _cap(self._run(agent, lambda app: app.list(dates, exclude, _clamp(limit, LIST_LIMIT, 200))))

    def show_session(
        self,
        session_id: str,
        agent: str | None = None,
        full: bool = False,
        offset: int = 0,
        max_chars: int | None = None,
    ) -> str:
        sid = session_id.strip()
        if len(sid) < 4:
            raise ToolError("give at least 4 characters of the session id")
        text = self._run(agent, lambda app: app.show(sid, 0 if full else DIGEST_CHARS))
        return _page(text, max(0, offset), _clamp(max_chars, MAX_CHARS, MAX_CHARS))


def _clamp(value: int | None, default: int, most: int) -> int:
    return default if value is None or value < 1 else min(value, most)


def _dates(since_days: int | None, date_from: str | None, date_to: str | None) -> DateFilter:
    for d in (date_from, date_to):
        if d and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d):
            raise ToolError(f"not a YYYY-MM-DD date: {d}")
    return DateFilter(since_days or None, date_from or None, date_to or None)


def _regex(pattern: str) -> None:
    try:
        re.compile(pattern)
    except re.error as e:
        raise ToolError(f"bad regex: {e}") from None


def _cap(text: str) -> str:
    return _page(text, 0, MAX_CHARS, more="narrow the search or lower limit")


def _page(text: str, offset: int, size: int, more: str | None = None) -> str:
    part = text[offset : offset + size]
    rest = len(text) - offset - len(part)
    if offset >= len(text) and text:
        return f"(offset {offset} is past the end, the text is {len(text)} characters)"
    if rest > 0:
        hint = more or f"call again with offset={offset + len(part)}"
        part += f"\n\n[cut: {rest} more characters, {hint}]"
    return part
