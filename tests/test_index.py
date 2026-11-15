import json

from agentrecall.index import chunk_text, update_index
from agentrecall.sources.claude import ClaudeCodeSource
from agentrecall.store import Store
from conftest import BACKUP, MONITORING, WEBSHOP

CHUNKING = (1000, 200)


def test_chunk_text():
    assert chunk_text("short", 10, 2) == ["short"]
    assert chunk_text("", 10, 2) == [""]
    parts = chunk_text("a" * 25, 10, 2)
    assert [len(p) for p in parts] == [10, 10, 9]
    assert "".join(p[:8] for p in parts[:-1]) + parts[-1] == "a" * 25


def test_index_is_incremental(tmp_path, projects, embedder):
    store = Store(tmp_path / "i.sqlite")
    src = ClaudeCodeSource([projects])
    first = update_index(store, [src], embedder, CHUNKING)
    assert first.added == 13 and first.waiting == 0
    assert {c.sid for c in store.chunks()} == {WEBSHOP, MONITORING, BACKUP}

    again = update_index(store, [src], embedder, CHUNKING)
    assert again.added == 0 and embedder.calls == 13

    (f,) = projects.glob(f"*/{MONITORING}.jsonl")
    line = {"type": "user", "timestamp": "2026-01-09T08:00:00Z", "message": {"content": "One more question."}}
    with f.open("a") as fh:
        fh.write(json.dumps(line) + "\n")
    assert update_index(store, [src], embedder, CHUNKING).added == 1
    assert len(store.chunks()) == 14


def test_rewritten_file_is_reindexed(tmp_path, projects, embedder):
    store = Store(tmp_path / "i.sqlite")
    src = ClaudeCodeSource([projects])
    update_index(store, [src], embedder, CHUNKING)
    (f,) = projects.glob(f"*/{BACKUP}.jsonl")
    f.write_text(f.read_text().splitlines()[0] + "\n")  # shorter than what was read
    update_index(store, [src], embedder, CHUNKING)
    assert [c.role for c in store.chunks() if c.sid == BACKUP] == ["user"]


def test_cap_defers_large_backlog(tmp_path, projects, embedder):
    store = Store(tmp_path / "i.sqlite")
    stats = update_index(store, [ClaudeCodeSource([projects])], embedder, CHUNKING, cap=5)
    assert stats.added == 0 and stats.waiting == 13
    assert store.chunks() == []


def test_excluded_sessions_are_skipped(tmp_path, projects, embedder):
    store = Store(tmp_path / "i.sqlite")
    update_index(store, [ClaudeCodeSource([projects])], embedder, CHUNKING, exclude={WEBSHOP})
    assert WEBSHOP not in {c.sid for c in store.chunks()}


def test_signature_change_resets(tmp_path, projects, embedder):
    store = Store(tmp_path / "i.sqlite")
    assert store.ensure_signature("model-a|1000|200") is False
    update_index(store, [ClaudeCodeSource([projects])], embedder, CHUNKING)
    assert store.ensure_signature("model-a|1000|200") is False
    assert store.chunks()
    assert store.ensure_signature("model-b|1000|200") is True
    assert store.chunks() == [] and store.offsets() == {}


def test_busy_lock_skips(tmp_path, projects, embedder):
    store = Store(tmp_path / "i.sqlite")
    with store.writer_lock() as mine:
        assert mine
        other = Store(tmp_path / "i.sqlite")
        assert update_index(other, [ClaudeCodeSource([projects])], embedder, CHUNKING).added == 0
