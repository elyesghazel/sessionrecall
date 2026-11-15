# Adding a source

A source teaches recall where one coding agent keeps its sessions and how to read
them. Everything else (indexing, search, `--list`, `--show`, redaction, forgetting) only
sees `Session` and `Turn`, so a new agent is one module plus one registry entry.

Today there are three: `claude.py` (Claude Code), `codex.py` (Codex CLI) and
`opencode.py` (OpenCode). Agents that would fit next: Gemini CLI, Cursor, Aider.

## 1. Find out the format

Look at your own sessions first, but never commit them. Note:

- where the sessions live, and which env var moves that place (`CLAUDE_CONFIG_DIR`,
  `CODEX_HOME`, `XDG_DATA_HOME`, ...);
- what one session is (a file, a folder, rows in a database) and what its id is;
- which records are things a person or the agent *said*, and which are tool calls,
  tool output, reasoning, token counts or context the harness injects (instructions
  files, environment blocks, reminders). Only the first kind belongs in the index;
- where the working directory is recorded, for the project column;
- whether the agent exports its session id to the commands it runs, so recall can leave
  the current session out of results (`CLAUDE_CODE_SESSION_ID`, `CODEX_THREAD_ID`).

## 2. Write the module

`src/agentrecall/sources/<agent>.py`, subclassing `agentrecall.sources.base.Source`:

```python
class GeminiSource(Source):
    name = "gemini"                      # used in config, --agent and the results

    @classmethod
    def from_config(cls, options): ...   # the [sources.gemini] table, may be {}

    def available(self) -> bool: ...     # is the agent installed? (auto-detection)
    def sessions(self): ...              # yield Session(name, id, path, mtime, size)
    def turns(self, path, offset=0): ... # (turns after offset, new offset)
    def project(self, path) -> str: ...  # working directory, home shortened with tilde()
    def exists(self, path) -> bool: ...  # only if path is not a real file
    def current_session_id(self): ...    # from an env var, or None
```

What matters:

- **Incremental reads.** `turns(path, offset)` returns only what comes after `offset`,
  plus the offset to resume from. `Session.size` is the offset once everything is read:
  the indexer skips a session when its stored offset equals `size` and starts over when
  the offset is larger (the session was rewritten). For append-only JSONL use
  `read_new_lines()`, which also leaves a half-written last line for the next run. For a
  database, a count of records read works (see `opencode.py`); stop before a record
  that is still being written.
- **`path` is the key.** The index stores offsets per `Session.path`, so it must be
  unique per session. It does not have to be a real file: OpenCode sessions use
  `<db file>/<session id>`. Then override `exists()`, which decides whether a search
  hit says "(transcript deleted)".
- **Only real turns.** Skip tool calls and results, reasoning, system or developer
  messages, and strip injected context. Return `None` or nothing for lines you do not
  understand instead of raising: formats change between versions, and one odd line must
  not stop the index.
- **Timestamps** are ISO 8601 strings, UTC (`...Z`) or with an offset.
- **Ids** are shown as 8 characters. If the agent prefixes ids with a type (`ses_...`),
  `short_id()` drops it, so make sure the 8 characters after it tell sessions apart.
- **Read only.** Open databases read-only (`file:...?mode=ro`) and never write to the
  agent's files.

## 3. Register it

Add the class to `REGISTRY` in `src/agentrecall/sources/__init__.py`. It is then:

- used automatically when `available()` is true,
- configurable as `[sources.<name>]`, and turned off with `enabled = false`,
- selectable with `recall --agent <name>`.

Mention it in the README (supported agents, config example).

## 4. Test it

- Hand-write a small fake session in `tests/fixtures/<agent>/` in the real format,
  including the noise your parser must skip (tool calls, injected context, an
  unfinished record). Invent the content, ids and paths (`/srv/demo/...`); never copy a
  real transcript, not even a trimmed one.
- If the agent stores sessions in a database, commit the rows as JSON and build the
  database in a fixture (see `opencode_dir` in `tests/conftest.py`).
- `tests/test_<agent>_source.py`: sessions are found, turns skip the noise, offsets
  resume correctly, project and current session work.
- Add the source to the `all_agents` fixture and check in `tests/test_cli.py` that its
  session is found by semantic and exact search.
- Tests run with a temporary `HOME` and XDG dirs (`isolated_env`). If your agent reads
  another env var for its location, clear it there, so no test can touch real sessions.
