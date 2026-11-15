import json
import sys

import pytest

from agentrecall import cli

from conftest import BACKUP, MONITORING, WEBSHOP


def session_order(out: str) -> list[str]:
    return [line.split()[1] for line in out.splitlines() if line.startswith("== ")]


def test_semantic_search(recall):
    out = recall("grafana", "dashboards", "for", "servers")
    assert out.startswith("now: ")
    assert session_order(out)[0] == MONITORING[:8]
    assert "/srv/demo/infra" in out
    assert "Grafana" in out


def test_search_indexes_on_the_fly_then_reuses(recall, embedder):
    recall("checkout test")
    calls = embedder.calls
    recall("checkout test")
    assert embedder.calls == calls


def test_semantic_limit_and_role(recall):
    assert len(session_order(recall("the", "-n", "1"))) == 1
    out = recall("alert disk full", "--role", "user")
    assert " user: " in out and " assi: " not in out


def test_output_is_redacted(recall):
    for out in (recall("staging password"), recall("--exact", "staging"), recall("--show", WEBSHOP[:8])):
        assert "correcthorse42battery" not in out
        assert "password=[REDACTED]" in out


def test_exact_and_regex(recall):
    out = recall("--exact", "order", "by")
    assert session_order(out) == [WEBSHOP[:8]]
    out = recall("-r", r"\bpg_dump\b")
    assert session_order(out) == [BACKUP[:8]]
    assert "pg_dump" in out


def test_exact_limit(recall):
    out = recall("--exact", "e", "-n", "2")
    assert "(limit 2 reached, use -n)" in out


def test_date_filters(recall):
    out = recall("--exact", "the", "--from", "2026-01-06", "--to", "2026-01-09")
    assert session_order(out) == [MONITORING[:8]]
    out = recall("backup database", "--to", "2026-01-05")
    assert session_order(out) == [WEBSHOP[:8]]


def test_bad_date(recall):
    with pytest.raises(SystemExit):
        recall("--from", "last week", "x")


def test_list(recall):
    lines = recall("--list").splitlines()[1:]
    assert [l.split()[3] for l in lines] == [BACKUP[:8], MONITORING[:8], WEBSHOP[:8]]
    assert "Wie richte ich" in lines[0]


def test_list_range_and_exclude(recall):
    out = recall("--list", "--from", "2026-01-08", "--to", "2026-01-08")
    (line,) = out.splitlines()[1:]
    assert MONITORING[:8] in line and "2 turns" not in line and "4 turns" in line
    out = recall("--list", "--exclude", "status page|backup")
    assert MONITORING[:8] not in out and BACKUP[:8] not in out and WEBSHOP[:8] in out


def test_show_and_digest(recall):
    out = recall("--show", MONITORING[:6])
    assert out.startswith(f"# {MONITORING} (/srv/demo/infra)")
    assert out.count("--- ") == 4
    full = recall("--show", WEBSHOP[:8])
    digest = recall("--show", WEBSHOP[:8], "--digest", "20")
    assert "Let me look at the test first." in full
    assert "Let me look at the test first." not in digest  # not the final reply of its turn
    assert "Found it: the test r [...]" in digest


def test_show_ambiguous_and_missing(recall, projects):
    (f,) = projects.glob(f"*/{BACKUP}.jsonl")
    f.with_name(BACKUP[:4] + "ffff-0000-4000-8000-000000000000.jsonl").write_text(f.read_text())
    with pytest.raises(SystemExit, match="2 sessions match"):
        recall("--show", BACKUP[:4])
    with pytest.raises(SystemExit, match="no session"):
        recall("--show", "ffff")


def test_forget_and_unforget(recall):
    recall("--index")
    out = recall("--forget", MONITORING[:8])
    assert out.startswith(f"forgotten: {MONITORING}")
    assert MONITORING[:8] not in recall("grafana dashboards")
    assert MONITORING[:8] not in recall("--list")
    assert MONITORING[:8] not in recall("--exact", "grafana")
    with pytest.raises(SystemExit):
        recall("--show", MONITORING[:8])
    assert recall("--forgotten").strip() == MONITORING

    assert recall("--unforget", MONITORING[:8]).startswith(f"restored: {MONITORING}")
    assert session_order(recall("grafana dashboards"))[0] == MONITORING[:8]
    assert recall("--forgotten") == ""


def test_forget_defaults_to_current_session(recall, monkeypatch):
    with pytest.raises(SystemExit, match="no session id"):
        recall("--forget")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", BACKUP)
    assert recall("--forget").startswith(f"forgotten: {BACKUP}")


def test_current_session_left_out_of_search(recall, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", MONITORING)
    assert MONITORING[:8] not in recall("grafana dashboards")
    assert "(this session)" in recall("--list")


def test_transcript_deleted_after_indexing(recall, projects):
    recall("--index")
    (f,) = projects.glob(f"*/{MONITORING}.jsonl")
    f.unlink()
    out = recall("grafana dashboards")
    assert "(transcript deleted)" in out


def test_titles_command(recall, config_file, tmp_path):
    script = tmp_path / "titles.py"
    script.write_text(f"print('{MONITORING}\\tMove monitoring to Grafana')\n")
    config_file.write_text(config_file.read_text() + f'[titles]\ncommand = ["{sys.executable}", "{script}"]\n')
    assert "Move monitoring to Grafana" in recall("--list")
    assert "Move monitoring to Grafana" in recall("grafana")


def test_empty_index_message(recall, projects):
    for f in projects.glob("*/*.jsonl"):
        f.unlink()
    with pytest.raises(SystemExit, match="index is empty"):
        recall("anything")


def test_large_backlog_is_left_to_index(recall, config_file, projects):
    config_file.write_text(config_file.read_text().replace("[sources", "inline_max = 2\n[sources", 1))
    with pytest.raises(SystemExit, match="index still building"):
        recall("grafana")
    recall("--index")
    (f,) = projects.glob(f"*/{BACKUP}.jsonl")
    with f.open("a") as fh:
        for i in range(3):
            line = {"type": "user", "timestamp": "2026-01-11T08:00:00Z", "message": {"content": f"note {i}"}}
            fh.write(json.dumps(line) + "\n")
    assert "index catching up: 3 newer chunks" in recall("grafana")


def test_needs_a_query(recall):
    with pytest.raises(SystemExit):
        recall()


def test_config_error_is_reported(config_file, capsys):
    config_file.write_text("nonsense = 1\n")
    with pytest.raises(SystemExit, match="unknown key"):
        cli.main(["--list"])
