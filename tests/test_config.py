from pathlib import Path

import pytest

from agentrecall.config import MODELS, Config, ConfigError, config_from_dict, load_config
from agentrecall.sources import build_sources
from agentrecall.sources.claude import ClaudeCodeSource


def test_defaults_follow_xdg(isolated_env):
    cfg = load_config()
    assert cfg.model_id == MODELS["multilingual-mini"].id
    assert cfg.index_path == isolated_env / ".cache" / "agentrecall" / "index.sqlite"
    assert cfg.forgotten_path == isolated_env / ".local" / "state" / "agentrecall" / "forgotten"
    assert cfg.sources == {"claude": {}}


def test_file_and_env_override(isolated_env, monkeypatch, tmp_path):
    path = tmp_path / "custom.toml"
    path.write_text('model = "jina-de"\ncache_dir = "~/elsewhere"\nthreads = 2\n'
                    '[titles]\ncommand = "my-titles --json no"\n')
    monkeypatch.setenv("AGENTRECALL_CONFIG", str(path))
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
