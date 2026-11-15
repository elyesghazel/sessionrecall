"""Session sources, one per coding agent."""

from __future__ import annotations

from collections.abc import Iterable

from agentrecall.config import Config, ConfigError
from agentrecall.sources.base import Role, Session, Source, Turn
from agentrecall.sources.claude import ClaudeCodeSource

REGISTRY: dict[str, type[Source]] = {
    ClaudeCodeSource.name: ClaudeCodeSource,
}

__all__ = ["REGISTRY", "Role", "Session", "Source", "Turn", "build_sources", "all_sessions"]


def build_sources(config: Config) -> list[Source]:
    out = []
    for name, options in config.sources.items():
        if name not in REGISTRY:
            raise ConfigError(f"unknown source {name!r} (known: {', '.join(REGISTRY)})")
        if options.get("enabled", True):
            out.append(REGISTRY[name].from_config(options))
    return out


def all_sessions(sources: Iterable[Source], exclude: set[str] = frozenset()) -> list[tuple[Source, Session]]:
    """Every session from every source, newest first, minus the ids in `exclude`."""
    found = [(src, s) for src in sources for s in src.sessions() if s.id not in exclude]
    return sorted(found, key=lambda pair: pair[1].mtime, reverse=True)
