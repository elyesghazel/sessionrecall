"""The MCP server, end to end: a scripted JSON-RPC client talks to `recall mcp` over stdio."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import BACKUP, MIGRATION, MONITORING, RATE_LIMIT, WEBP, WEBSHOP, HashEmbedder

from agentrecall.tools import MAX_CHARS, ToolError, Tools

pytest.importorskip("mcp")

# Runs the real server, with the fake embedder so nothing is downloaded.
LAUNCH = (
    "import sys; sys.path.insert(0, sys.argv[1]);"
    "from conftest import HashEmbedder; from agentrecall import cli;"
    "raise SystemExit(cli.main(['mcp'], embedder=HashEmbedder()))"
)


class StdioClient:
    def __init__(self, config_file: Path) -> None:
        env = {**os.environ, "AGENTRECALL_CONFIG": str(config_file)}
        self.proc = subprocess.Popen(
            [sys.executable, "-c", LAUNCH, str(Path(__file__).parent)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env,
        )
        self.next_id = 0

    def send(self, method: str, params: dict | None = None, notify: bool = False) -> dict | None:
        msg: dict = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        if not notify:
            self.next_id += 1
            msg["id"] = self.next_id
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()
        if notify:
            return None
        while True:
            line = self.proc.stdout.readline()
            if not line:
                raise AssertionError(f"server exited: {self.proc.stderr.read()}")
            reply = json.loads(line)
            if reply.get("id") == self.next_id:
                return reply

    def call(self, tool: str, **arguments) -> str:
        reply = self.send("tools/call", {"name": tool, "arguments": arguments})
        assert "error" not in reply, reply
        result = reply["result"]
        return "".join(c["text"] for c in result["content"] if c["type"] == "text")

    def close(self) -> None:
        self.proc.stdin.close()
        self.proc.wait(timeout=10)


@pytest.fixture
def client(config_file):
    c = StdioClient(config_file)
    init = c.send("initialize", {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "test-client", "version": "0"},
    })
    assert init["result"]["serverInfo"]["name"] == "recall"
    assert "past coding-agent sessions" in init["result"]["instructions"]
    c.send("notifications/initialized", notify=True)
    yield c
    c.close()


def test_tools_listed_with_agent_argument(client):
    tools = {t["name"]: t for t in client.send("tools/list", {})["result"]["tools"]}
    assert set(tools) == {"search", "list_sessions", "show_session"}
    for t in tools.values():
        assert "agent" in t["inputSchema"]["properties"]
        assert t["description"]
    assert tools["search"]["inputSchema"]["required"] == ["query"]
    assert tools["show_session"]["inputSchema"]["required"] == ["session_id"]


def test_search_over_stdio(client):
    out = client.call("search", query="grafana dashboards for servers")
    assert out.startswith("now: ")
    assert f"== {MONITORING[:8]}" in out.split("\n\n")[1]
    assert client.call("search", query="pg_dump", exact=True).count("== ") == 1
    assert BACKUP[:8] in client.call("search", query="pg_dump", exact=True)


def test_results_are_redacted(client):
    for out in (client.call("search", query="staging password"),
                client.call("search", query="staging", exact=True),
                client.call("show_session", session_id=WEBSHOP[:8], full=True)):
        assert "correcthorse42battery" not in out
        assert "[REDACTED]" in out


def test_list_and_show_over_stdio(client):
    listing = client.call("list_sessions")
    assert all(sid[:8] in listing for sid in (WEBSHOP, MONITORING, BACKUP))
    shown = client.call("show_session", session_id=MONITORING[:8])
    assert shown.startswith("# ") and MONITORING in shown and "--- user" in shown


def test_agent_filter_and_errors_over_stdio(client):
    assert "== " in client.call("search", query="grafana", agent="claude")
    assert client.call("search", query="grafana", agent="nope").startswith("error: unknown agent 'nope'")
    assert client.call("search", query="grafana", agent="codex") == "nothing found"  # not on this machine
    assert client.call("show_session", session_id="ffffffff") == "no session ffffffff"
    assert client.call("list_sessions", date_from="last week").startswith("error: not a YYYY-MM-DD date")


# --- the tool layer directly (no SDK, no subprocess) ----------------------------------


@pytest.fixture
def tools(config_file) -> Tools:
    from agentrecall.config import load_config

    return Tools(load_config(config_file), HashEmbedder())


def test_show_session_pages(tools):
    full = tools.show_session(WEBSHOP[:8], full=True)
    first = tools.show_session(WEBSHOP[:8], full=True, max_chars=200)
    assert len(first) < 300 and "[cut: " in first and "offset=200" in first
    second = tools.show_session(WEBSHOP[:8], full=True, offset=200, max_chars=200)
    assert full[200:300] in second
    assert "past the end" in tools.show_session(WEBSHOP[:8], offset=10**6)


def test_results_never_exceed_the_cap(tools, projects):
    (f,) = projects.glob(f"*/{BACKUP}.jsonl")
    with f.open("a") as fh:
        line = {"type": "assistant", "timestamp": "2026-01-11T08:00:00Z",
                "message": {"content": [{"type": "text", "text": "backup log " * 5000}]}}
        fh.write(json.dumps(line) + "\n")
    out = tools.show_session(BACKUP[:8], full=True, max_chars=10**9)
    assert len(out) <= MAX_CHARS + 100
    assert len(tools.show_session(BACKUP[:8])) < MAX_CHARS  # the digest trims turns


def test_tool_errors(tools):
    with pytest.raises(ToolError):
        tools.search("   ")
    with pytest.raises(ToolError):
        tools.show_session("ab")
    with pytest.raises(ToolError):
        tools.list_sessions(exclude="(")
    with pytest.raises(ToolError):
        tools.search("x", role="system")


def test_agent_argument_over_stdio(all_agents):
    c = StdioClient(all_agents)
    c.send("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                          "clientInfo": {"name": "test-client", "version": "0"}})
    c.send("notifications/initialized", notify=True)
    try:
        everything = c.call("search", query="nginx login bots")
        assert f"== {RATE_LIMIT[:8]}  codex" in everything
        codex = c.call("search", query="the", agent="codex", limit=20)
        assert RATE_LIMIT[:8] in codex and MONITORING[:8] not in codex and "opencode" not in codex
        assert c.call("search", query="user_name", exact=True, agent="codex").count("== ") == 1
        assert MIGRATION[:8] in c.call("list_sessions", agent="codex")
        assert "claude" not in c.call("list_sessions", agent="opencode").split("\n", 1)[1]
        assert "/srv/demo/blog" in c.call("show_session", session_id=WEBP)
        assert c.call("show_session", session_id=WEBP, agent="codex").startswith("no session")
    finally:
        c.close()
