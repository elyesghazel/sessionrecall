# Source this to get a shell whose HOME is the synthetic demo corpus:
#
#     source demo/env.sh
#
# It copies demo/corpus/ into $DEMO_HOME (default /tmp/sessionrecall-demo), dates each
# transcript at its last turn, installs this checkout there with `uv tool install`, and
# points every agent and recall path at it. Nothing outside $DEMO_HOME is read or
# written, so your own sessions never show up. The home sits at a short neutral path
# because `recall install --print` shows absolute paths. The embedding model is kept in
# $DEMO_HOME/.cache between runs.

DEMO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
DEMO_HOME="${DEMO_HOME:-/tmp/sessionrecall-demo}"
UV="$(command -v uv)"
export UV_CACHE_DIR="${UV_CACHE_DIR:-$("$UV" cache dir)}"

# Only ever clean a directory this script created.
if [ -d "$DEMO_HOME" ] && [ -n "$(ls -A "$DEMO_HOME")" ] && [ ! -e "$DEMO_HOME/.sessionrecall-demo" ]; then
  echo "demo/env.sh: $DEMO_HOME exists and is not a demo home, refusing to touch it" >&2
  return 1 2>/dev/null || exit 1
fi
mkdir -p "$DEMO_HOME" && touch "$DEMO_HOME/.sessionrecall-demo"
# Start from the corpus each time; keep the installed recall and the downloaded model.
rm -rf "$DEMO_HOME/.claude" "$DEMO_HOME/.claude.json" "$DEMO_HOME/.codex" "$DEMO_HOME/.config" \
  "$DEMO_HOME/.local/share/opencode" "$DEMO_HOME/.local/state" "$DEMO_HOME/.cache/sessionrecall/index.sqlite"
cp -r "$DEMO_DIR/corpus/." "$DEMO_HOME/"

# Transcript mtimes: when the last turn happened (a git checkout sets them to now).
python3 - "$DEMO_HOME" <<'PY'
import json, os, sys
from datetime import datetime
from pathlib import Path
for f in [*Path(sys.argv[1], ".claude").rglob("*.jsonl"), *Path(sys.argv[1], ".codex").rglob("*.jsonl")]:
    stamps = []
    for line in f.read_text().splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        t = d.get("timestamp") if isinstance(d, dict) else None
        if isinstance(t, str):
            stamps.append(datetime.fromisoformat(t.replace("Z", "+00:00")).timestamp())
    if stamps:
        os.utime(f, (max(stamps), max(stamps)))
PY

export HOME="$DEMO_HOME"
export XDG_CONFIG_HOME="$HOME/.config" XDG_CACHE_HOME="$HOME/.cache" \
  XDG_STATE_HOME="$HOME/.local/state" XDG_DATA_HOME="$HOME/.local/share"
unset CLAUDE_CONFIG_DIR CODEX_HOME SESSIONRECALL_CONFIG CLAUDE_CODE_SESSION_ID CODEX_THREAD_ID \
  SESSIONRECALL_BACKGROUND
export PATH="$HOME/.local/bin:$DEMO_DIR/bin:/usr/local/bin:/usr/bin:/bin"
[ -x "$HOME/.local/bin/recall" ] || "$UV" tool install --quiet --force --python 3.12 "$DEMO_DIR/..[mcp]"
cd "$HOME"
