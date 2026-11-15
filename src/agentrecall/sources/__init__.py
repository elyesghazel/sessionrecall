"""Session sources, one per coding agent."""

from __future__ import annotations

from collections.abc import Iterable

from agentrecall.config import Config, ConfigError
from agentrecall.sources.base import Role, Session, Source, Turn, id_matches, short_id
from agentrecall.sources.claude import ClaudeCodeSource
from agentrecall.sources.codex import CodexSource
from agentrecall.sources.opencode import OpenCodeSource

REGISTRY: dict[str, type[Source]] = {
    ClaudeCodeSource.name: ClaudeCodeSource,
    CodexSource.name: CodexSource,
    OpenCodeSource.name: OpenCodeSource,
}

__all__ = ["REGISTRY", "Role", "Session", "Source", "Turn", "all_sessions", "build_sources", "id_matches", "short_id"]


def build_sources(config: Config) -> list[Source]:
    """Every agent found on this machine, plus the ones configured, minus `enabled = false`."""
    for name in config.sources:
        if name not in REGISTRY:
            raise ConfigError(f"unknown source {name!r} (known: {', '.join(REGISTRY)})")
    out = []
    for name, cls in REGISTRY.items():
        options = config.sources.get(name)
        if options is not None and not options.get("enabled", True):
            continue
        src = cls.from_config(options or {})
        if options is not None or src.available():
            out.append(src)
    return out


def all_sessions(sources: Iterable[Source], exclude: set[str] = frozenset()) -> list[tuple[Source, Session]]:
    """Every session from every source, newest first, minus the ids in `exclude`."""
    found = [(src, s) for src in sources for s in src.sessions() if s.id not in exclude]
    return sorted(found, key=lambda pair: pair[1].mtime, reverse=True)
