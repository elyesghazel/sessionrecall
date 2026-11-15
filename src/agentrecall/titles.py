"""Optional session titles from an external command.

Agents rarely store a title next to the transcript, but a UI around them might. Point
`[titles] command` at any program that prints `<session-id><TAB><title>` lines and recall
shows those titles in its output. Off unless configured.
"""

from __future__ import annotations

import subprocess
import sys

TIMEOUT_S = 10


def load_titles(command: list[str] | None) -> dict[str, str]:
    if not command:
        return {}
    try:
        out = subprocess.run(command, capture_output=True, text=True, timeout=TIMEOUT_S, check=True).stdout
    except (OSError, subprocess.SubprocessError) as e:
        print(f"recall: titles command failed: {e}", file=sys.stderr)
        return {}
    titles = {}
    for line in out.splitlines():
        sid, sep, title = line.partition("\t")
        if sep and sid.strip():
            titles[sid.strip()] = title.strip()
    return titles
