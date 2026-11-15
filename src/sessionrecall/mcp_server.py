"""`recall mcp`: a stdio MCP server, so agents can search their own past sessions.

Needs the optional extra: `uv tool install 'sessionrecall[mcp]'`. Every result passes
through the same secret redaction as the CLI and is cut to fit an agent's context.
"""

import sys
from typing import Annotated, Literal

from sessionrecall import __version__
from sessionrecall.index import Embedder
from sessionrecall.tools import ToolError, Tools

INSTRUCTIONS = """\
Search the user's past coding-agent sessions on this machine (Claude Code and others).
Use it when the user refers to earlier work ("like we did last week", "the fix from
before"), or before redoing something that may have been solved already.
- search: by meaning by default; exact=true for literal words such as error messages.
- list_sessions: recent sessions, or the ones active in a date range.
- show_session: read one session found by the other two (an 8-character id is enough).
Times are local. Scores are relative: judge by the snippets, and say nothing was found
instead of guessing. Secrets in results are printed as [REDACTED]."""

def build_server(tools: Tools):
    try:
        from mcp.server.mcpserver import MCPServer
    except ImportError:
        raise SystemExit(
            "recall mcp needs the MCP SDK: uv tool install 'sessionrecall[mcp]' (or pip install 'sessionrecall[mcp]')"
        ) from None
    from pydantic import Field

    def d(text: str):
        return Field(description=text)

    Agent = Annotated[str | None, d("Only sessions of this agent (a source name such as 'claude'); default all.")]
    Date = Annotated[str | None, d("Local date YYYY-MM-DD, inclusive.")]

    server = MCPServer("recall", version=__version__, instructions=INSTRUCTIONS)

    def call(fn, *args, **kwargs) -> str:
        try:
            return fn(*args, **kwargs) or "nothing found"
        except ToolError as e:
            return f"error: {e}"

    @server.tool(structured_output=False)
    def search(
        query: Annotated[str, d("What to look for, in your own words (or the literal words with exact=true).")],
        agent: Agent = None,
        exact: Annotated[bool, d("Turns containing all words literally (case-insensitive), not by meaning.")] = False,
        since_days: Annotated[int | None, d("Only the last N days.")] = None,
        date_from: Date = None,
        date_to: Date = None,
        role: Literal["user", "assistant"] | None = None,
        limit: Annotated[int | None, d("Max sessions (default 5) or, with exact, max turns (default 20).")] = None,
    ) -> str:
        """Search past sessions. Returns the best snippets per session, with session id, project and time."""
        return call(tools.search, query, agent, exact, since_days, date_from, date_to, role, limit)

    @server.tool(structured_output=False)
    def list_sessions(
        agent: Agent = None,
        since_days: Annotated[int | None, d("Only sessions written in the last N days.")] = None,
        date_from: Date = None,
        date_to: Date = None,
        exclude: Annotated[str | None, d("Regex: drop sessions whose title or first message matches.")] = None,
        limit: Annotated[int | None, d("Max rows (default 20).")] = None,
    ) -> str:
        """Recent sessions, newest first: time, id, project and first message. With dates: sessions active then."""
        return call(tools.list_sessions, agent, since_days, date_from, date_to, exclude, limit)

    @server.tool(structured_output=False)
    def show_session(
        session_id: Annotated[str, d("A session id or a unique prefix of it (8 characters are usually enough).")],
        agent: Agent = None,
        full: Annotated[bool, d("Every turn in full. Default: user turns and final replies, each trimmed.")] = False,
        offset: Annotated[int, d("Character offset to continue a long session from (the result says where).")] = 0,
        max_chars: Annotated[int | None, d("Max characters returned (default and most 12000).")] = None,
    ) -> str:
        """Read one past session, a page at a time."""
        return call(tools.show_session, session_id, agent, full, offset, max_chars)

    return server


def serve(embedder: Embedder | None = None) -> int:
    server = build_server(Tools(embedder=embedder))
    print(f"recall mcp {__version__}: serving on stdio", file=sys.stderr)
    server.run("stdio")
    return 0
