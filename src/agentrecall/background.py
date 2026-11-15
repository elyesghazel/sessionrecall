"""Background search inside Claude Code, and the `recall-inject` hook that delivers it.

A semantic search can take a few seconds (the model loads, new turns get embedded).
Inside a Claude Code session, with `AGENTRECALL_BACKGROUND=1` (set by `recall install
claude`), `recall <query>` returns at once and runs the search detached. The output
lands in `<cache_dir>/inbox/<session-id>/<n>.txt` (`.part` while running), and the
`recall-inject` hook hands it to the agent:

- PostToolUse: finished results are attached to the next tool result.
- Stop: waits up to 30 s for running searches, then blocks the stop once with them.

Results start with `[recall results for: <query>]`. `recall --wait <query>` searches in
the foreground instead. This module imports only the standard library, because the hook
runs after every tool call.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ENV = "AGENTRECALL_BACKGROUND"
SESSION_ENV = "CLAUDE_CODE_SESSION_ID"
STOP_WAIT_S = 30
STALE_S = 300  # a .part older than this belongs to a worker that died
NOTE = "(Delivered by the recall-inject hook: these are the results of a recall search you started earlier.)\n"
_SAFE_ID = re.compile(r"[\w-]{1,128}")


def inbox(session_id: str) -> Path | None:
    if not _SAFE_ID.fullmatch(session_id or ""):
        return None
    from agentrecall.config import load_config

    return load_config().cache_dir / "inbox" / session_id


def wanted(a: argparse.Namespace) -> bool:
    """True if this invocation is a semantic search that should run in the background."""
    if os.environ.get(ENV) != "1" or not os.environ.get(SESSION_ENV) or a.wait:
        return False
    other_mode = a.regex or a.exact or a.list or a.show or a.index or a.forgotten or a.unforget
    return bool(a.terms) and not other_mode and a.forget is None


def spawn(argv: list[str], terms: list[str]) -> int:
    """Start the search detached and tell the agent where the results will show up."""
    box = inbox(os.environ.get(SESSION_ENV, ""))
    if box is None:
        from agentrecall import cli

        return cli.main([*argv, "--wait"])
    box.mkdir(parents=True, exist_ok=True)
    part = box / f"{time.time_ns()}.part"
    query = " ".join(terms)
    subprocess.Popen(
        [sys.executable, "-m", "agentrecall.background", str(part), query, *argv],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    print(
        f'recall: searching for "{query}" in the background (takes a few seconds).\n'
        'The results will be attached to your next tool result as "[recall results for: ...]",\n'
        "or handed to you before you stop. That is expected, not an error, and you do not\n"
        "need to re-run or wait. Use recall --wait to get them inline instead."
    )
    return 0


def _worker(part: Path, query: str, argv: list[str]) -> None:
    """Run the search in the foreground into `part`, then rename it to .txt."""
    from agentrecall import cli
    from agentrecall.redact import RedactingWriter

    with part.open("w") as f:
        f.write(f"[recall results for: {query}]\n")
        f.flush()
        sys.stdout = RedactingWriter(f)
        sys.stderr = f
        try:
            cli.main([*argv, "--wait"])
        except SystemExit as e:
            if e.code not in (None, 0):
                print(e.code, file=f)
        except Exception as e:  # noqa: BLE001 - the agent should see why, not a hung .part
            print(f"recall failed: {e!r}", file=f)
        finally:
            sys.stdout, sys.stderr = sys.__stdout__, sys.__stderr__
    part.rename(part.with_suffix(".txt"))


def inject(stdin=None, stdout=None) -> int:
    """The Claude Code hook (PostToolUse and Stop). Reads the hook event JSON on stdin."""
    stdin, stdout = stdin or sys.stdin, stdout or sys.stdout
    try:
        event = json.load(stdin)
    except ValueError:
        return 0
    box = inbox(str(event.get("session_id", "")))
    if box is None or not box.is_dir():
        return 0
    name = event.get("hook_event_name")
    if name == "Stop":
        end = time.time() + STOP_WAIT_S
        while _running(box) and time.time() < end:
            time.sleep(0.5)
    done = sorted(box.glob("*.txt"))
    if not done:
        return 0
    text = "\n\n".join(f.read_text(errors="replace").strip() for f in done)
    for f in done:
        f.unlink(missing_ok=True)
    if name == "Stop":
        out = {"decision": "block", "reason": NOTE + text}
    else:
        out = {"hookSpecificOutput": {"hookEventName": name, "additionalContext": NOTE + text}}
    json.dump(out, stdout)
    return 0


def _running(box: Path) -> bool:
    now = time.time()
    return any(now - p.stat().st_mtime < STALE_S for p in box.glob("*.part"))


def inject_main() -> None:
    raise SystemExit(inject())


if __name__ == "__main__":
    _worker(Path(sys.argv[1]), sys.argv[2], sys.argv[3:])
