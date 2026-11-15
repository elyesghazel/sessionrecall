---
name: recall
description: Search the user's past coding-agent sessions on this machine by meaning, with the `recall` CLI or the recall MCP tools. Use when the user types /recall, refers to earlier work ("like last time", "the fix we did last week", "where did we leave X", "didn't we already solve this"), asks what happened in a past session or on a date, or before redoing something that may have been solved in an earlier session.
---

<!-- installed by agentrecall (recall install claude); recall install claude --uninstall removes it -->

# recall: search past sessions

Your earlier sessions are searchable. Search before saying you don't know what was done
before, and before rebuilding something that may already exist.

## How to search

Prefer the `recall` MCP tools when they are available (`search`, `list_sessions`,
`show_session`); otherwise use the CLI through the shell:

```sh
recall how did we fix the flaky test     # by meaning; your own words are fine
recall --exact ORDER BY                  # turns containing all words literally
recall -r 'pg_(dump|restore)'            # regex
recall --since 7 deploy                  # last 7 days
recall --from 2026-01-05 --to 2026-01-11 backup    # local date range, inclusive
recall --list                            # recent sessions (with --from/--to: active then)
recall --show 3f9a1c2e --digest          # read a session: user turns + final replies
recall --show 3f9a1c2e                   # every turn
```

If the user named an argument after /recall, search for it.

## Background results

When the installer enabled background search, `recall <query>` inside a session returns
at once with a notice and searches in the background. The results arrive in a later tool
result, or just before you stop, as a block starting with `[recall results for: ...]`.
That block is the answer to your earlier search, not noise: do not re-run the search
while waiting. Use `recall --wait <query>` when you need the results inline.

## Reading results

- Each hit shows the session id (first 8 characters), project, local time and age. Pass
  the id to `--show` / `show_session` for the full context.
- Scores are relative. Judge by the snippets; if none of them is about the question, say
  nothing was found instead of guessing.
- A recent session may not be indexed yet. If a semantic search misses something you
  expect, try `--exact` with a distinctive word.
- Secrets are printed as `[REDACTED]`. Never try to recover them from the transcript files.
- Sessions the user has forgotten (`recall --forget`) never show up. Respect that: do not
  read their transcript files directly.
