import json

from conftest import MIGRATION, RATE_LIMIT
from sessionrecall.sources.codex import CodexSource, default_home, parse_line


def by_id(home):
    return {s.id: s for s in CodexSource(home).sessions()}


def test_sessions_include_archived(codex_home):
    found = by_id(codex_home)
    assert set(found) == {RATE_LIMIT, MIGRATION}
    s = found[RATE_LIMIT]
    assert s.source == "codex" and s.size == s.path.stat().st_size


def test_turns_skip_injected_context_tools_and_events(codex_home):
    src = CodexSource(codex_home)
    turns, end = src.turns(by_id(codex_home)[RATE_LIMIT].path)
    assert [t.role for t in turns] == ["user", "assistant", "user", "assistant"]
    assert turns[0].text == "Bots hammer the login endpoint all night. Can nginx slow them down?"
    assert turns[0].ts == "2026-01-06T10:01:00.000Z"
    assert turns[1].text.startswith("I added a limit_req_zone")
    assert turns[2].text == "Will that block people behind one office network?"  # turn_aborted stripped
    text = "\n".join(t.text for t in turns)
    for noise in ("AGENTS.md", "environment_context", "permissions", "nginx.conf", "server {", "Look at"):
        assert noise not in text


def test_early_format(codex_home):
    src = CodexSource(codex_home)
    path = by_id(codex_home)[MIGRATION].path
    turns, _ = src.turns(path)
    assert [t.role for t in turns] == ["user", "assistant"]
    assert "user_name" in turns[0].text
    assert src.project(path) == "/srv/demo/api"


def test_incremental(codex_home):
    src = CodexSource(codex_home)
    path = by_id(codex_home)[RATE_LIMIT].path
    _, end = src.turns(path)
    line = {"timestamp": "2026-01-06T11:00:00Z", "type": "response_item",
            "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Thanks."}]}}
    with path.open("a") as f:
        f.write(json.dumps(line) + "\n")
    turns, end2 = src.turns(path, end)
    assert [t.text for t in turns] == ["Thanks."] and end2 == path.stat().st_size


def test_project_and_home(codex_home, isolated_env, tmp_path):
    src = CodexSource(codex_home)
    assert src.project(by_id(codex_home)[RATE_LIMIT].path) == "/srv/demo/api"
    f = tmp_path / "rollout-2026-01-01T00-00-00-00000000-0000-4000-8000-000000000000.jsonl"
    f.write_text(json.dumps({"type": "session_meta", "payload": {"cwd": f"{isolated_env}/code/x"}}) + "\n")
    assert src.project(f) == "~/code/x"
    f.write_text("garbage\n")
    assert src.project(f) == "codex"


def test_parse_line_rejects_garbage():
    assert parse_line("nope") is None
    assert parse_line("[]") is None
    assert parse_line('{"type":"response_item","payload":{"type":"message","role":"developer","content":"x"}}') is None
    assert parse_line('{"type":"response_item","payload":{"type":"message","role":"user","content":[]}}') is None


def test_defaults_and_detection(monkeypatch, isolated_env, tmp_path, codex_home):
    assert default_home() == isolated_env / ".codex"
    assert not CodexSource().available()
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    assert default_home() == codex_home and CodexSource().available()
    assert CodexSource.from_config({"home": str(tmp_path)}).home == tmp_path


def test_current_session(monkeypatch):
    assert CodexSource().current_session_id() is None
    monkeypatch.setenv("CODEX_THREAD_ID", RATE_LIMIT)
    assert CodexSource().current_session_id() == RATE_LIMIT
