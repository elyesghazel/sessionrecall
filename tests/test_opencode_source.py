import json
import sqlite3

from agentrecall.sources.opencode import OpenCodeSource, default_data_dir

from conftest import DARK_MODE, RSS, WEBP


def by_id(data_dir):
    return {s.id: s for s in OpenCodeSource(data_dir).sessions()}


def test_sessions_from_database_and_files(opencode_dir):
    found = by_id(opencode_dir)
    assert set(found) == {WEBP, RSS, DARK_MODE}
    assert found[WEBP].path == opencode_dir / "opencode.db" / WEBP
    assert found[WEBP].size == 5  # messages
    assert found[DARK_MODE].path.name == f"{DARK_MODE}.json" and found[DARK_MODE].size == 2
    assert found[DARK_MODE].mtime < found[WEBP].mtime < found[RSS].mtime


def test_database_turns_skip_tools_reasoning_and_synthetic(opencode_dir):
    src = OpenCodeSource(opencode_dir)
    turns, end = src.turns(by_id(opencode_dir)[WEBP].path)
    assert end == 5
    assert [t.role for t in turns] == ["user", "assistant", "user", "assistant"]
    assert turns[0].text == "The blog takes ages to load, the photos are huge. Fix it."
    assert turns[0].ts == "2026-01-07T08:00:00.000Z"
    assert "WebP" in turns[1].text
    text = "\n".join(t.text for t in turns)
    assert "Called the Read tool" not in text and "du -sh" not in text and "image pipeline" not in text


def test_streaming_reply_waits_for_next_run(opencode_dir):
    src = OpenCodeSource(opencode_dir)
    path = by_id(opencode_dir)[RSS].path
    turns, end = src.turns(path)
    assert [t.role for t in turns] == ["user"] and end == 1
    db = sqlite3.connect(opencode_dir / "opencode.db")
    (data,) = db.execute("select data from message where id='msg_02b'").fetchone()
    done = json.loads(data)
    done["time"]["completed"] = done["time"]["created"] + 5000
    db.execute("update message set data=? where id='msg_02b'", (json.dumps(done),))
    db.commit()
    turns, end = src.turns(path, end)
    assert [t.role for t in turns] == ["assistant"] and end == 2


def test_file_storage_turns(opencode_dir):
    src = OpenCodeSource(opencode_dir)
    path = by_id(opencode_dir)[DARK_MODE].path
    turns, end = src.turns(path)
    assert [t.role for t in turns] == ["user", "assistant"] and end == 2
    assert "toggle" in turns[1].text
    assert src.turns(path, 2) == ([], 2)


def test_project_and_exists(opencode_dir, tmp_path):
    src = OpenCodeSource(opencode_dir)
    found = by_id(opencode_dir)
    assert src.project(found[WEBP].path) == "/srv/demo/blog"
    assert src.project(found[DARK_MODE].path) == "/srv/demo/blog"
    assert src.exists(found[WEBP].path)
    assert not src.exists(opencode_dir / "opencode.db" / "ses_gone")
    assert src.project(opencode_dir / "opencode.db" / "ses_gone") == "opencode"


def test_defaults_and_detection(monkeypatch, isolated_env, opencode_dir, tmp_path):
    assert default_data_dir() == isolated_env / ".local/share/opencode"
    assert not OpenCodeSource().available()
    assert OpenCodeSource(opencode_dir).available()
    (opencode_dir / "opencode.db").unlink()
    assert OpenCodeSource(opencode_dir).available()  # older file storage alone
    assert OpenCodeSource.from_config({"data_dir": str(tmp_path)}).data_dir == tmp_path


def test_broken_database_is_skipped(tmp_path):
    (tmp_path / "opencode.db").write_text("not a database")
    src = OpenCodeSource(tmp_path)
    assert list(src.sessions()) == []
    assert src.turns(tmp_path / "opencode.db" / "x") == ([], 0)
