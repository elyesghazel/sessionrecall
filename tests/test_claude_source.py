from pathlib import Path

from conftest import BACKUP, MONITORING, WEBSHOP
from sessionrecall.sources.base import read_new_lines
from sessionrecall.sources.claude import ClaudeCodeSource, default_projects_dir, parse_line


def session_path(projects: Path, sid: str) -> Path:
    (f,) = projects.glob(f"*/{sid}.jsonl")
    return f


def test_sessions(projects):
    src = ClaudeCodeSource([projects])
    found = {s.id: s for s in src.sessions()}
    assert set(found) == {WEBSHOP, MONITORING, BACKUP}
    s = found[WEBSHOP]
    assert s.source == "claude"
    assert s.size == s.path.stat().st_size


def test_turns_skip_meta_tools_and_noise(projects):
    src = ClaudeCodeSource([projects])
    turns, end = src.turns(session_path(projects, WEBSHOP))
    assert end == session_path(projects, WEBSHOP).stat().st_size
    assert [t.role for t in turns] == ["user", "assistant", "assistant", "user", "assistant"]
    assert turns[0].text.endswith("Can you find out why?")  # system-reminder stripped
    assert turns[1].text == "Let me look at the test first."  # tool_use block dropped
    assert all("tool_result" not in t.text and "Caveat" not in t.text for t in turns)
    assert turns[0].ts == "2026-01-05T09:01:00.000Z"


def test_project_is_cwd(projects):
    src = ClaudeCodeSource([projects])
    assert src.project(session_path(projects, MONITORING)) == "/srv/demo/infra"


def test_project_shortens_home(tmp_path, isolated_env):
    f = tmp_path / "p" / "x.jsonl"
    f.parent.mkdir()
    f.write_text(f'{{"type":"user","cwd":"{isolated_env}/code/app"}}\n')
    assert ClaudeCodeSource([tmp_path]).project(f) == "~/code/app"


def test_project_falls_back_to_folder(tmp_path):
    f = tmp_path / "-some-folder" / "x.jsonl"
    f.parent.mkdir()
    f.write_text('{"type":"summary"}\n')
    assert ClaudeCodeSource([tmp_path]).project(f) == "-some-folder"


def test_incremental_offsets_leave_partial_line(tmp_path):
    f = tmp_path / "s.jsonl"
    f.write_bytes(b'{"a":1}\n{"b":2}\n{"c":')
    lines, end = read_new_lines(f, 0)
    assert lines == ['{"a":1}', '{"b":2}']
    assert end == 16
    with f.open("ab") as fh:
        fh.write(b"3}\n")
    lines, end2 = read_new_lines(f, end)
    assert lines == ['{"c":3}']
    assert end2 == f.stat().st_size


def test_parse_line_rejects_garbage():
    assert parse_line("not json") is None
    assert parse_line("[1, 2]") is None
    assert parse_line('{"type":"user","message":{"content":"   "}}') is None


def test_default_dir_follows_claude_config_dir(monkeypatch, tmp_path, isolated_env):
    assert default_projects_dir() == isolated_env / ".claude" / "projects"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "alt"))
    assert default_projects_dir() == tmp_path / "alt" / "projects"


def test_current_session(monkeypatch):
    assert ClaudeCodeSource().current_session_id() is None
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", WEBSHOP)
    assert ClaudeCodeSource().current_session_id() == WEBSHOP


def test_from_config_paths(tmp_path):
    src = ClaudeCodeSource.from_config({"paths": str(tmp_path)})
    assert src.paths == [tmp_path]
