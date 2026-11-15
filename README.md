# agentrecall

Semantic search over your past coding-agent sessions. Local, private, no cloud.

You remember *that* you solved something with your agent a few weeks ago, but not the
words you used. `recall` embeds your session transcripts on your own machine and finds
them by meaning: "replaced the status page" finds the session where you "moved
monitoring to Grafana".

Supported: **Claude Code**, **Codex CLI** and **OpenCode**. Installed agents are found
automatically.

> Work in progress, not released yet.

## Install

```sh
uv tool install agentrecall    # or: pipx install agentrecall
# from a checkout:
uv tool install .
```

Python 3.11 or newer. The first search downloads the embedding model once (see
[Models](#models)).

## Use

```sh
recall --index                         # embed everything once (later runs only read what is new)
recall how did we fix the flaky test   # semantic search
recall --exact ORDER BY                # turns containing all terms
recall -r 'pg_(dump|restore)'          # regex
recall --since 7 deploy                # only the last 7 days
recall --agent codex rate limit        # only one agent (claude, codex, opencode)
recall --from 2026-01-05 --to 2026-01-11 backup
recall --list                          # recent sessions
recall --show 3f9a1c2e                 # print a session (an id prefix is enough)
recall --show 3f9a1c2e --digest        # just your turns and the final replies
recall --forget 3f9a1c2e               # hide a session from recall for good
```

Results show the session id, agent, project, local time and age, and the best matching
snippets:

```
== 7b2d4e6f  claude  /srv/demo/infra  [0.74, best hit 3 days ago]
  Thu 2026-01-08 15:00 (3 days ago) user: The old status page keeps breaking. Replace it with ...
  Thu 2026-01-08 15:05 (3 days ago) assi: I removed the status page container and set up Grafana ...
```

Scores are relative: judge by the snippets, not the number.

A search embeds up to 150 new chunks itself. Keep the index fresh with a timer, e.g. cron:

```cron
*/15 * * * * nice -n 19 recall --index
```

## Let your agent search (MCP)

`recall mcp` is a stdio [MCP](https://modelcontextprotocol.io) server, so an agent can
search its own past sessions. It needs the `mcp` extra:

```sh
uv tool install 'agentrecall[mcp]'    # or: pipx install 'agentrecall[mcp]'
```

Tools (each takes an optional `agent`, a source name such as `claude`):

| tool | what it returns |
|---|---|
| `search` | best snippets per session, by meaning; `exact: true` for literal words. Filters: `since_days`, `date_from`, `date_to`, `role`, `limit` |
| `list_sessions` | recent sessions (with dates: the ones active then), `exclude` regex, `limit` |
| `show_session` | one session, user turns and final replies trimmed (`full: true` for everything), paged by `offset` |

Results are redacted like everything else recall prints and capped at 12,000 characters,
so a tool call never floods the agent's context.

### Install into an agent

```sh
recall install claude     # MCP server + /recall skill + background search hook
recall install codex      # [mcp_servers.recall] in ~/.codex/config.toml ($CODEX_HOME)
recall install opencode   # mcp.servers.recall in ~/.config/opencode/opencode.json
```

Each one prints what it changes and backs up every file it rewrites to
`<file>.bak-agentrecall-<time>`. Running it again changes nothing. `--print` shows the
plan and the snippets without writing; `--uninstall` removes exactly what was added.
`--command PATH` puts another `recall` executable into the config (default: the one
you ran). Restart the agent afterwards.

Or add it by hand:

- **Claude Code**: `claude mcp add --scope user recall -- recall mcp`
  (stored in `~/.claude.json` under `mcpServers`).
- **Codex** (`~/.codex/config.toml`):

  ```toml
  [mcp_servers.recall]
  command = "recall"
  args = ["mcp"]
  ```

- **OpenCode** (`~/.config/opencode/opencode.json`; older versions put servers directly
  under `mcp` with `"enabled": true`, which `recall install opencode` detects):

  ```json
  {
    "$schema": "https://opencode.ai/config.json",
    "mcp": { "servers": { "recall": { "type": "local", "command": ["recall", "mcp"] } } }
  }
  ```

### Claude Code extras

`recall install claude` also adds, in `~/.claude/settings.json` (or `$CLAUDE_CONFIG_DIR`):

- **Background search.** It sets `AGENTRECALL_BACKGROUND=1`, so `recall <query>` run by
  the agent inside a session returns at once and searches detached (the model load and
  new embeddings can take a few seconds). The `recall-inject` hook (PostToolUse and Stop)
  then attaches the results, headed `[recall results for: ...]`, to the next tool result,
  or blocks the stop once to hand them over. Pending results wait in
  `<cache_dir>/inbox/<session-id>/`. `recall --wait <query>` searches inline instead.
  Skip all of this with `--no-hook`.
- **A `/recall` skill** in `~/.claude/skills/recall/SKILL.md` that tells the agent when
  and how to search. Skip with `--no-skill`; an existing skill of your own with that
  name is never overwritten.

## Models

Any [fastembed](https://github.com/qdrant/fastembed) text model works. Presets:

| preset | model | download | RAM while indexing | languages |
|---|---|---|---|---|
| `multilingual-mini` (default) | paraphrase-multilingual-MiniLM-L12-v2 | ~240 MB | ~0.7 GB | ~50 |
| `jina-de` | jina-embeddings-v2-base-de | ~610 MB | ~1.1 GB | German + English, long context |
| `english-small` | bge-small-en-v1.5 | ~70 MB | less | English |

The default model reads 128 tokens per chunk, so chunks are smaller (480 characters)
than for long-context models (1000). Changing the model or chunking rebuilds the index
on the next run.

## Configure

Everything has a default; the config file is optional:
`~/.config/agentrecall/config.toml` (or `$AGENTRECALL_CONFIG`, or `--config`).

```toml
model = "multilingual-mini"        # a preset or any fastembed model name
# cache_dir = "~/.cache/agentrecall"     index + model files ($XDG_CACHE_HOME)
# state_dir = "~/.local/state/agentrecall"   list of forgotten sessions
# threads = 4
# inline_max = 150                 # new chunks a search embeds itself

# Agents installed here are used without a table. A table configures one;
# `enabled = false` turns it off.
[sources.claude]
# paths = ["~/.claude/projects"]   # default; follows $CLAUDE_CONFIG_DIR

[sources.codex]
# home = "~/.codex"                # default; follows $CODEX_HOME (reads sessions/ and archived_sessions/)

[sources.opencode]
# data_dir = "~/.local/share/opencode"   # default; follows $XDG_DATA_HOME
# enabled = false

[titles]
# Optional: a program that prints "<session-id><TAB><title>" lines, for agents
# or UIs that keep session titles somewhere else. Off by default.
# command = ["my-session-titles"]
```

## Privacy

- Everything stays on your machine: transcripts are read locally, the model runs
  locally, the index is a SQLite file in your cache dir.
- Output is redacted: API keys, tokens, bearer headers, `password=...` values, URL
  credentials and private keys are printed as `[REDACTED]`, so a search result never
  carries a secret into another session. The index itself keeps the original text.
- `recall --forget <id>` removes a session's chunks from the index and hides it from
  every mode, including turns added later. `--unforget` undoes it, `--forgotten` lists
  them. The transcript file itself is never touched.
- The session you run recall from (Claude Code sets `CLAUDE_CODE_SESSION_ID`, Codex
  `CODEX_THREAD_ID`) is left out of search results, so your own question is not the top
  hit.
- The index keeps chunks of transcripts deleted since, so search still finds them;
  `--show` cannot print those any more.

## How it works

Each source turns an agent's storage into sessions and turns
(`agentrecall.sources.base.Source`: `sessions()` and `turns(path, offset)`). The indexer
reads only what was appended since the last run (by byte offset, or message count for OpenCode), splits turns into
overlapping chunks, embeds them and stores unit vectors in SQLite. A search embeds the
query, ranks all chunks by cosine similarity plus a small bonus for literal query words,
and shows the best three chunks of each top session.

Adding an agent means one module in `src/agentrecall/sources/` and one entry in
`REGISTRY`; see [docs/adding-a-source.md](docs/adding-a-source.md).

| agent | where | what is read |
|---|---|---|
| Claude Code | `~/.claude/projects/<project>/<id>.jsonl` | user and assistant text, without tool calls and injected reminders |
| Codex CLI | `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`, `archived_sessions/` | `response_item` messages, without AGENTS.md, environment context, tools and reasoning |
| OpenCode | `~/.local/share/opencode/opencode.db`, or `storage/` JSON in older versions | text parts of user and assistant messages, without tools, reasoning and synthetic parts |

## Develop

```sh
uv sync
uv run pytest                                  # fast, uses a fake embedder
AGENTRECALL_TEST_MODEL=1 uv run pytest -m model   # also runs the real model (downloads it)
```

Tests run against hand-written fake sessions in `tests/fixtures/` with a temporary
`HOME`; they never read your real transcripts.

## License

MIT
