"""`recall install`: only ever against the temp HOME from conftest."""

from __future__ import annotations

import io
import json
import tomllib
from pathlib import Path

import pytest

from sessionrecall import install

RECALL = "/opt/tools/bin/recall"
INJECT = "/opt/tools/bin/recall-inject"


@pytest.fixture(autouse=True)
def no_agent_env(monkeypatch):
    for var in ("CODEX_HOME", "OPENCODE_CONFIG", "CLAUDE_CONFIG_DIR"):
        monkeypatch.delenv(var, raising=False)


def run(*argv: str) -> str:
    out = io.StringIO()
    install.main([*argv, "--command", RECALL], out=out)
    return out.getvalue()


def backups(path: Path) -> list[Path]:
    return sorted(path.parent.glob(f"{path.name}.bak-sessionrecall-*"))


def test_paths_stay_in_the_temp_home(isolated_env):
    for p in (install.claude_dir(), install.claude_mcp_file(), install.codex_config(), install.opencode_config()):
        assert p.is_relative_to(isolated_env)


def test_claude_fresh_install(isolated_env):
    out = run("claude")
    settings = json.loads((isolated_env / ".claude/settings.json").read_text())
    assert settings["env"] == {"SESSIONRECALL_BACKGROUND": "1"}
    assert settings["hooks"]["PostToolUse"][0]["hooks"][0]["command"] == INJECT
    assert settings["hooks"]["Stop"][0]["hooks"][0]["command"] == INJECT
    mcp = json.loads((isolated_env / ".claude.json").read_text())["mcpServers"]["recall"]
    assert mcp == {"type": "stdio", "command": RECALL, "args": ["mcp"]}
    skill = (isolated_env / ".claude/skills/recall/SKILL.md").read_text()
    assert skill.startswith("---\nname: recall\n") and install.SKILL_MARK in skill
    assert "add PostToolUse hook" in out and "backup" not in out  # nothing existed to back up


def test_claude_keeps_existing_settings_and_backs_up(isolated_env):
    settings_path = isolated_env / ".claude/settings.json"
    settings_path.parent.mkdir(parents=True)
    existing = {
        "model": "opus",
        "env": {"FOO": "bar"},
        "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "/usr/bin/true"}]}]},
    }
    settings_path.write_text(json.dumps(existing))
    claude_json = isolated_env / ".claude.json"
    claude_json.write_text(json.dumps({"numStartups": 3, "mcpServers": {"other": {"command": "x"}}}))

    out = run("claude")
    data = json.loads(settings_path.read_text())
    assert data["model"] == "opus" and data["env"]["FOO"] == "bar"
    assert [h["hooks"][0]["command"] for h in data["hooks"]["Stop"]] == ["/usr/bin/true", INJECT]
    assert json.loads(claude_json.read_text())["mcpServers"].keys() == {"other", "recall"}
    (b,) = backups(settings_path)
    assert json.loads(b.read_text()) == existing
    assert len(backups(claude_json)) == 1
    assert "backup: ~/.claude/settings.json.bak-sessionrecall-" in out


def test_claude_is_idempotent(isolated_env):
    run("claude")
    files = [isolated_env / ".claude/settings.json", isolated_env / ".claude.json",
             isolated_env / ".claude/skills/recall/SKILL.md"]
    before = [f.read_text() for f in files]
    out = run("claude")
    assert [f.read_text() for f in files] == before
    assert out.count("already up to date") == 3
    assert not any(backups(f) for f in files)  # nothing changed, nothing backed up


def test_claude_print_writes_nothing(isolated_env):
    out = run("claude", "--print")
    assert "nothing written" in out and '"SESSIONRECALL_BACKGROUND": "1"' in out
    assert f"claude mcp add --scope user recall -- {RECALL} mcp" in out
    assert not (isolated_env / ".claude").exists() and not (isolated_env / ".claude.json").exists()


def test_claude_uninstall_restores(isolated_env):
    settings_path = isolated_env / ".claude/settings.json"
    settings_path.parent.mkdir(parents=True)
    original = {"env": {"FOO": "bar"}, "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "/usr/bin/true"}]}]}}
    settings_path.write_text(json.dumps(original))
    run("claude")
    out = run("claude", "--uninstall")
    assert json.loads(settings_path.read_text()) == original
    assert "recall" not in json.loads((isolated_env / ".claude.json").read_text())["mcpServers"]
    assert not (isolated_env / ".claude/skills/recall").exists()
    assert "remove Stop hook" in out and "delete the /recall skill" in out
    assert "already up to date" in run("claude", "--uninstall")


def test_claude_refuses_foreign_skill_and_bad_json(isolated_env):
    skill = isolated_env / ".claude/skills/recall/SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("my own skill\n")
    with pytest.raises(SystemExit, match="not installed by sessionrecall"):
        run("claude")
    assert skill.read_text() == "my own skill\n"
    run("claude", "--no-skill")  # the rest still installs
    assert skill.read_text() == "my own skill\n"

    (isolated_env / ".claude/settings.json").write_text("{ not json")
    with pytest.raises(SystemExit, match="not plain JSON"):
        run("claude", "--no-skill")


def test_claude_options(isolated_env, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(isolated_env / "alt"))
    run("claude", "--no-hook", "--no-skill")
    assert (isolated_env / "alt/.claude.json").exists()
    assert not (isolated_env / "alt/settings.json").exists()
    assert not (isolated_env / ".claude.json").exists()


def test_codex(isolated_env):
    config = isolated_env / ".codex/config.toml"
    config.parent.mkdir()
    original = 'model = "o3"\n\n[mcp_servers.other]\ncommand = "x"\n'
    config.write_text(original)
    run("codex")
    data = tomllib.loads(config.read_text())
    assert data["model"] == "o3" and "other" in data["mcp_servers"]
    assert data["mcp_servers"]["recall"] == {"command": RECALL, "args": ["mcp"]}
    assert len(backups(config)) == 1

    text = config.read_text()
    assert "already up to date" in run("codex")
    assert config.read_text() == text

    # A changed command replaces the old block (and its sub-tables) instead of adding one.
    config.write_text(text.replace(RECALL, "/old/recall") + '\n[mcp_servers.recall.env]\nA = "1"\n\n[after]\nx = 1\n')
    run("codex")
    data = tomllib.loads(config.read_text())
    assert data["mcp_servers"]["recall"] == {"command": RECALL, "args": ["mcp"]}
    assert data["after"] == {"x": 1}

    run("codex", "--uninstall")
    data = tomllib.loads(config.read_text())
    assert "recall" not in data["mcp_servers"] and data["after"] == {"x": 1} and data["model"] == "o3"


def test_codex_home_and_print(isolated_env, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(isolated_env / "codex-alt"))
    out = run("codex", "--print")
    assert "[mcp_servers.recall]" in out and not (isolated_env / "codex-alt").exists()
    run("codex")
    assert tomllib.loads((isolated_env / "codex-alt/config.toml").read_text())["mcp_servers"]["recall"]


def test_codex_refuses_invalid_toml(isolated_env):
    config = isolated_env / ".codex/config.toml"
    config.parent.mkdir()
    config.write_text("this is = = not toml\n")
    with pytest.raises(SystemExit, match="not valid TOML"):
        run("codex")
    assert config.read_text() == "this is = = not toml\n"


def test_opencode(isolated_env):
    run("opencode")
    path = isolated_env / ".config/opencode/opencode.json"
    data = json.loads(path.read_text())
    assert data["$schema"] == "https://opencode.ai/config.json"
    assert data["mcp"]["servers"]["recall"] == {"type": "local", "command": [RECALL, "mcp"]}
    assert "already up to date" in run("opencode")
    run("opencode", "--uninstall")
    assert json.loads(path.read_text())["mcp"]["servers"] == {}


def test_opencode_legacy_layout_and_jsonc(isolated_env):
    folder = isolated_env / ".config/opencode"
    folder.mkdir(parents=True)
    path = folder / "opencode.json"
    path.write_text(json.dumps({"theme": "x", "mcp": {"other": {"type": "local", "command": ["y"]}}}))
    run("opencode")
    data = json.loads(path.read_text())
    assert data["mcp"]["recall"] == {"type": "local", "command": [RECALL, "mcp"], "enabled": True}
    assert data["theme"] == "x"

    jsonc = folder / "opencode.jsonc"
    jsonc.write_text('{\n  // my comment\n  "theme": "x"\n}\n')
    with pytest.raises(SystemExit, match="add the snippet by hand"):
        run("opencode")
    assert "// my comment" in jsonc.read_text()
