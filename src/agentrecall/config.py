"""Configuration: ~/.config/agentrecall/config.toml, with defaults for everything.

Example config.toml:

    model = "multilingual-mini"       # a preset below or any fastembed model name
    # cache_dir = "~/.cache/agentrecall"
    # threads = 4

    [sources.claude]
    # paths = ["~/.claude/projects"]

    [titles]
    # command = ["my-titles-script"]  # prints "<session-id><TAB><title>" lines
"""

from __future__ import annotations

import os
import shlex
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

APP = "agentrecall"


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class ModelPreset:
    """A known-good embedding model. Any other fastembed model name also works."""

    id: str
    dim: int
    download_mb: int
    max_tokens: int
    languages: str


MODELS: dict[str, ModelPreset] = {
    "multilingual-mini": ModelPreset(
        "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", 384, 220, 128, "~50 languages"
    ),
    "jina-de": ModelPreset("jinaai/jina-embeddings-v2-base-de", 768, 640, 8192, "German + English"),
    "english-small": ModelPreset("BAAI/bge-small-en-v1.5", 384, 70, 512, "English"),
}
DEFAULT_MODEL = "multilingual-mini"


def _xdg(var: str, fallback: str) -> Path:
    value = os.environ.get(var)
    return Path(value) if value else Path.home() / fallback


def _path(value: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(value)))


def default_config_path() -> Path:
    if env := os.environ.get("AGENTRECALL_CONFIG"):
        return _path(env)
    return _xdg("XDG_CONFIG_HOME", ".config") / APP / "config.toml"


@dataclass
class Config:
    model: str = DEFAULT_MODEL
    cache_dir: Path = field(default_factory=lambda: _xdg("XDG_CACHE_HOME", ".cache") / APP)
    state_dir: Path = field(default_factory=lambda: _xdg("XDG_STATE_HOME", ".local/state") / APP)
    threads: int | None = None
    # A search embeds at most this many new chunks itself; more are left to `recall --index`.
    inline_max: int = 150
    chunk_chars: int | None = None
    chunk_overlap: int | None = None
    # Source name -> its options table. Every source here is enabled unless `enabled = false`.
    sources: dict[str, dict[str, Any]] = field(default_factory=lambda: {"claude": {}})
    titles_command: list[str] | None = None

    @property
    def model_id(self) -> str:
        preset = MODELS.get(self.model)
        return preset.id if preset else self.model

    @property
    def chunking(self) -> tuple[int, int]:
        """(chunk size, overlap) in characters, sized to what the model reads."""
        preset = MODELS.get(self.model)
        short = preset is not None and preset.max_tokens <= 128
        size = self.chunk_chars or (480 if short else 1000)
        overlap = self.chunk_overlap if self.chunk_overlap is not None else size // 5
        if not 0 <= overlap < size:
            raise ConfigError("chunk_overlap must be smaller than chunk_chars")
        return size, overlap

    @property
    def index_path(self) -> Path:
        return self.cache_dir / "index.sqlite"

    @property
    def models_dir(self) -> Path:
        return self.cache_dir / "models"

    @property
    def forgotten_path(self) -> Path:
        return self.state_dir / "forgotten"


_KEYS = {"model", "cache_dir", "state_dir", "threads", "inline_max", "chunk_chars", "chunk_overlap",
         "sources", "titles"}


def load_config(path: Path | None = None) -> Config:
    """Read the config file if it exists; a missing file means all defaults."""
    path = path or default_config_path()
    if not path.exists():
        return Config()
    try:
        data = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path}: {e}") from e
    return config_from_dict(data, where=str(path))


def config_from_dict(data: dict[str, Any], where: str = "config") -> Config:
    unknown = set(data) - _KEYS
    if unknown:
        raise ConfigError(f"{where}: unknown key(s): {', '.join(sorted(unknown))}")
    cfg = Config()
    if "model" in data:
        cfg.model = str(data["model"])
    for key in ("cache_dir", "state_dir"):
        if key in data:
            setattr(cfg, key, _path(data[key]))
    for key in ("threads", "inline_max", "chunk_chars", "chunk_overlap"):
        if key in data:
            if not isinstance(data[key], int):
                raise ConfigError(f"{where}: {key} must be an integer")
            setattr(cfg, key, data[key])
    if "sources" in data:
        if not isinstance(data["sources"], dict):
            raise ConfigError(f"{where}: [sources] must be a table")
        cfg.sources = {name: dict(opts) for name, opts in data["sources"].items()}
    command = (data.get("titles") or {}).get("command")
    if command:
        cfg.titles_command = shlex.split(command) if isinstance(command, str) else [str(c) for c in command]
    return cfg
