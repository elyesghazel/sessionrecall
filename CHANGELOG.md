# Changelog

All notable changes are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow
[Semantic Versioning](https://semver.org/).

## [0.1.0] - unreleased

The project was called `agentrecall` before release and was renamed to `sessionrecall`.
It is not published to PyPI: the names were taken or rejected, and
[recall-agents](https://github.com/alirng/recall) and
[session-recall](https://pypi.org/project/session-recall/) already cover this ground and
are further along. sessionrecall stays a small portfolio project, installed from GitHub.
The release workflow builds the wheel and attaches it to a GitHub release instead of
uploading it to PyPI.

### Added

- `recall` CLI: semantic search over past coding-agent sessions, plus `--exact`, `--regex`,
  date (`--since`, `--from`, `--to`), `--role` and `--agent` filters, `--list`, `--show`
  and `--show --digest`.
- Sources for Claude Code, Codex CLI (current and early rollout formats, archived
  sessions) and OpenCode (SQLite database and older JSON storage). Installed agents are
  found automatically.
- Incremental local index in SQLite with fastembed models; presets `multilingual-mini`
  (default), `jina-de` and `english-small`.
- Secret redaction on every output path, `--forget` / `--unforget` / `--forgotten`.
- `recall mcp`: stdio MCP server with `search`, `list_sessions` and `show_session`.
- `recall install claude|codex|opencode` with `--print` and `--uninstall`; for Claude Code
  also a `/recall` skill and background search through the `recall-inject` hook.

[0.1.0]: https://github.com/elyesghazel/sessionrecall/releases/tag/v0.1.0
