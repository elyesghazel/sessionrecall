from pathlib import Path

import pytest

from sessionrecall.config import MODELS, Config, ConfigError, config_from_dict, load_config
from sessionrecall.sources import build_sources
from sessionrecall.sources.claude import ClaudeCodeSource
from sessionrecall.sources.codex import CodexSource
from sessionrecall.sources.opencode import OpenCodeSource


def test_defaults_follow_xdg(isolated_env):
    cfg = load_config()
    assert cfg.model_id == MODELS["multilingual-mini"].id
    assert cfg.index_path == isolated_env / ".cache" / "sessionrecall" / "index.sqlite"
    assert cfg.forgotten_path == isolated_env / ".local" / "state" / "sessionrecall" / "forgotten"
    assert cfg.sources == {}


def test_file_and_env_override(isolated_env, monkeypatch, tmp_path):
    path = tmp_path / "custom.toml"
    path.write_text('model = "jina-de"\ncache_dir = "~/elsewhere"\nthreads = 2\n'
                    '[titles]\ncommand = "my-titles --json no"\n')
    monkeypatch.setenv("SESSIONRECALL_CONFIG", str(path))
    cfg = load_config()
    assert cfg.model_id == "jinaai/jina-embeddings-v2-base-de"
    assert cfg.cache_dir == isolated_env / "elsewhere"
    assert cfg.threads == 2
    assert cfg.titles_command == ["my-titles", "--json", "no"]


def test_any_fastembed_model_name_passes_through():
    assert config_from_dict({"model": "BAAI/bge-base-en-v1.5"}).model_id == "BAAI/bge-base-en-v1.5"


def test_chunking_matches_model():
    assert Config(model="multilingual-mini").chunking == (480, 96)
    assert Config(model="jina-de").chunking == (1000, 200)
    assert Config(chunk_chars=300, chunk_overlap=0).chunking == (300, 0)
    with pytest.raises(ConfigError):
        _ = Config(chunk_chars=100, chunk_overlap=100).chunking


def test_unknown_key_is_an_error():
    with pytest.raises(ConfigError, match="modle"):
        config_from_dict({"modle": "x"})


def test_bad_toml(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text("model = ")
    with pytest.raises(ConfigError):
        load_config(p)


def test_sources(tmp_path):
    cfg = config_from_dict({"sources": {"claude": {"paths": [str(tmp_path)]}}})
    (src,) = build_sources(cfg)
    assert isinstance(src, ClaudeCodeSource) and src.paths == [Path(tmp_path)]
    assert build_sources(config_from_dict({"sources": {"claude": {"enabled": False}}})) == []
    with pytest.raises(ConfigError, match="unknown source"):
        build_sources(config_from_dict({"sources": {"nope": {}}}))


def test_installed_agents_are_detected(isolated_env, monkeypatch, codex_home):
    assert build_sources(Config()) == []
    (isolated_env / ".claude" / "projects").mkdir(parents=True)
    (isolated_env / ".local" / "share" / "opencode").mkdir(parents=True)
    (isolated_env / ".local" / "share" / "opencode" / "opencode.db").touch()
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    assert [s.name for s in build_sources(Config())] == ["claude", "codex", "opencode"]
    cfg = config_from_dict({"sources": {"codex": {"enabled": False}}})
    assert [s.name for s in build_sources(cfg)] == ["claude", "opencode"]


def test_configured_source_is_used_even_if_not_found(tmp_path):
    cfg = config_from_dict({"sources": {"codex": {"home": str(tmp_path / "nowhere")}, "opencode": {}}})
    srcs = build_sources(cfg)
    assert [type(s) for s in srcs] == [CodexSource, OpenCodeSource]
