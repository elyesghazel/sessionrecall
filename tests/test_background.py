"""Background search inside Claude Code and the recall-inject hook."""

from __future__ import annotations

import functools
import io
import json
import os
import time

import pytest
from conftest import MONITORING, HashEmbedder

from agentrecall import background, cli

SID = "11111111-2222-4333-8444-555555555555"


@pytest.fixture
def in_session(monkeypatch, config_file):
    monkeypatch.setenv("AGENTRECALL_CONFIG", str(config_file))
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", SID)
    monkeypatch.setenv("AGENTRECALL_BACKGROUND", "1")
    monkeypatch.setattr(cli, "main", functools.partial(cli.main, embedder=HashEmbedder()))
    return background.inbox(SID)


def hook(event: str, sid: str = SID, **extra) -> dict | None:
    out = io.StringIO()
    background.inject(io.StringIO(json.dumps({"session_id": sid, "hook_event_name": event, **extra})), out)
    return json.loads(out.getvalue()) if out.getvalue() else None


def parse(*argv):
    return cli.build_parser().parse_args(list(argv))


def test_only_semantic_searches_in_a_session_go_to_the_background(in_session, monkeypatch):
    assert background.wanted(parse("grafana"))
    for argv in (["--wait", "grafana"], ["--exact", "grafana"], ["-r", "x"], ["--list"], ["--show", "ab"],
                 ["--index"], ["--forget"], ["--forgotten"]):
        assert not background.wanted(parse(*argv)), argv
    monkeypatch.setenv("AGENTRECALL_BACKGROUND", "0")
    assert not background.wanted(parse("grafana"))
    monkeypatch.setenv("AGENTRECALL_BACKGROUND", "1")
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID")
    assert not background.wanted(parse("grafana"))


def test_spawn_starts_a_detached_worker(in_session, monkeypatch, capsys):
    started = []
    monkeypatch.setattr(background.subprocess, "Popen", lambda args, **kw: started.append((args, kw)))
    cli.main(["--since", "30", "grafana", "dashboards"])
    (args, kw), = started
    assert args[1:3] == ["-m", "agentrecall.background"]
    assert args[3].endswith(".part") and args[3].startswith(str(in_session))
    assert args[4:] == ["grafana dashboards", "--since", "30", "grafana", "dashboards"]
    assert kw["start_new_session"]
    assert 'searching for "grafana dashboards" in the background' in capsys.readouterr().out


def test_worker_then_post_tool_use_delivers_once(in_session):
    in_session.mkdir(parents=True)
    part = in_session / "1.part"
    background._worker(part, "grafana", ["grafana"])
    assert not part.exists() and (in_session / "1.txt").exists()
    out = hook("PostToolUse")
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert out["hookSpecificOutput"]["hookEventName"] == "PostToolUse"
    assert "[recall results for: grafana]" in ctx and MONITORING[:8] in ctx
    assert hook("PostToolUse") is None  # delivered, gone


def test_worker_output_is_redacted(in_session):
    in_session.mkdir(parents=True)
    background._worker(in_session / "2.part", "staging password", ["staging", "password"])
    text = (in_session / "2.txt").read_text()
    assert "correcthorse42battery" not in text and "[REDACTED]" in text


def test_stop_blocks_with_results(in_session):
    in_session.mkdir(parents=True)
    (in_session / "3.txt").write_text("[recall results for: x]\nhit\n")
    out = hook("Stop", stop_hook_active=False)
    assert out["decision"] == "block" and "hit" in out["reason"]
    assert hook("Stop") is None


def test_stop_ignores_a_dead_worker(in_session, monkeypatch):
    in_session.mkdir(parents=True)
    part = in_session / "4.part"
    part.write_text("")
    old = time.time() - background.STALE_S - 10
    os.utime(part, (old, old))
    monkeypatch.setattr(background, "STOP_WAIT_S", 5)
    start = time.time()
    assert hook("Stop") is None
    assert time.time() - start < 1


def test_hook_ignores_bad_input(in_session):
    assert hook("PostToolUse", sid="../../etc") is None
    assert hook("PostToolUse", sid="") is None
    out = io.StringIO()
    assert background.inject(io.StringIO("not json"), out) == 0 and out.getvalue() == ""
