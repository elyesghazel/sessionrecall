"""`recall install claude|codex|opencode`: wire recall into an agent's config.

Every change is planned first and printed. Files are only written when something
actually changes (so running it twice is a no-op), and every existing file is copied
to `<file>.bak-agentrecall-<time>` before it is rewritten. `--print` shows the plan and
the snippets without writing anything; `--uninstall` removes exactly what install adds.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tomllib
from dataclasses import dataclass, field
from datetime import datetime
from importlib import resources
from pathlib import Path
from typing import Any

SERVER = "recall"  # the MCP server name in every agent's config
BACKGROUND_ENV = "AGENTRECALL_BACKGROUND"
SKILL_MARK = "installed by agentrecall"


class InstallError(Exception):
    pass


@dataclass
class Change:
    path: Path
    before: str | None  # None: the file does not exist yet
    after: str | None  # None: delete the file
    notes: list[str] = field(default_factory=list)
    snippet: str = ""  # what to paste by hand, for --print
    backup: bool = True  # False for files that are entirely ours

    @property
    def changed(self) -> bool:
        return self.before != self.after


# --- helpers ----------------------------------------------------------------------


def executable(name: str) -> str:
    """The absolute path of one of our console scripts, so hooks work without PATH."""
    here = Path(sys.executable).parent
    for candidate in (here / name, here / f"{name}.exe"):
        if candidate.exists():
            return str(candidate)
    return shutil.which(name) or name


def tilde(path: Path) -> str:
    home = str(Path.home())
    s = str(path)
    return "~" + s[len(home):] if s == home or s.startswith(home + os.sep) else s


def _read(path: Path) -> str | None:
    try:
        return path.read_text()
    except FileNotFoundError:
        return None


def _load_json(path: Path, text: str | None) -> dict[str, Any]:
    if text is None or not text.strip():
        return {}
    try:
        data = json.loads(text)
    except ValueError as e:
        raise InstallError(f"{tilde(path)} is not plain JSON ({e}); add the snippet by hand (see --print)") from None
    if not isinstance(data, dict):
        raise InstallError(f"{tilde(path)}: expected a JSON object at the top")
    return data


def _dump_json(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def _table(data: dict[str, Any], *keys: str) -> dict[str, Any]:
    for key in keys:
        value = data.setdefault(key, {})
        if not isinstance(value, dict):
            raise InstallError(f"{'.'.join(keys)}: expected an object, found {type(value).__name__}")
        data = value
    return data


# --- Claude Code --------------------------------------------------------------------


def claude_dir() -> Path:
    base = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(base).expanduser() if base else Path.home() / ".claude"


def claude_mcp_file() -> Path:
    """User-scope MCP servers live in ~/.claude.json (inside $CLAUDE_CONFIG_DIR if set)."""
    base = os.environ.get("CLAUDE_CONFIG_DIR")
    return (Path(base).expanduser() if base else Path.home()) / ".claude.json"


def _hook_entries(inject: str) -> dict[str, dict[str, Any]]:
    return {
        "PostToolUse": {"matcher": "*", "hooks": [{"type": "command", "command": inject, "timeout": 10}]},
        "Stop": {"hooks": [{"type": "command", "command": inject, "timeout": 40}]},
    }


def plan_claude(uninstall: bool, *, hook: bool, mcp: bool, skill: bool, recall: str, inject: str) -> list[Change]:
    changes = []

    if hook:
        path = claude_dir() / "settings.json"
        before = _read(path)
        data = _load_json(path, before)
        notes: list[str] = []
        hooks = data.get("hooks") if isinstance(data.get("hooks"), dict) else None
        for event, entry in _hook_entries(inject).items():
            groups = hooks.get(event, []) if hooks else []
            ours = [g for g in groups if _has_command(g, inject)]
            if uninstall:
                for g in ours:
                    g["hooks"] = [h for h in g.get("hooks", []) if h.get("command") != inject]
                    if not g["hooks"]:
                        groups.remove(g)
                if ours:
                    notes.append(f"remove {event} hook {inject}")
                if hooks is not None and event in hooks and not groups:
                    del hooks[event]
            elif not ours:
                others = [h.get("command") for g in groups for h in g.get("hooks", [])
                          if str(h.get("command", "")).rstrip().endswith("recall-inject")]
                if others:
                    notes.append(f"note: another recall-inject {event} hook is configured ({others[0]}); both will run")
                _table(data, "hooks").setdefault(event, []).append(entry)
                hooks = data["hooks"]
                notes.append(f"add {event} hook {inject}")
        env = data.get("env") if isinstance(data.get("env"), dict) else None
        if uninstall:
            if env and BACKGROUND_ENV in env:
                del env[BACKGROUND_ENV]
                notes.append(f"remove env {BACKGROUND_ENV}")
                if not env:
                    del data["env"]
            if hooks is not None and not hooks:
                del data["hooks"]
        elif (env or {}).get(BACKGROUND_ENV) != "1":
            _table(data, "env")[BACKGROUND_ENV] = "1"
            notes.append(f"set env {BACKGROUND_ENV}=1 (recall <query> runs in the background inside a session)")
        after = _dump_json(data) if notes and any(not n.startswith("note:") for n in notes) else before
        snippet = _dump_json({"env": {BACKGROUND_ENV: "1"}, "hooks": {k: [v] for k, v in _hook_entries(inject).items()}})
        changes.append(Change(path, before, after, notes, snippet))

    if mcp:
        path = claude_mcp_file()
        entry = {"type": "stdio", "command": recall, "args": ["mcp"]}
        changes.append(_json_server(path, ("mcpServers",), entry, uninstall,
                                    hint=f"or: claude mcp add --scope user {SERVER} -- {recall} mcp"))

    if skill:
        path = claude_dir() / "skills" / "recall" / "SKILL.md"
        before = _read(path)
        text = resources.files("agentrecall").joinpath("skill/SKILL.md").read_text()
        ours = before is None or SKILL_MARK in before
        if uninstall:
            after = None if before is not None and ours else before
            notes = ["delete the /recall skill"] if after != before else []
        elif not ours:
            raise InstallError(f"{tilde(path)} exists and was not installed by agentrecall; move it away or use --no-skill")
        else:
            after = text
            notes = ["write the /recall skill"] if before != text else []
        changes.append(Change(path, before, after, notes, "(a copy of agentrecall/skill/SKILL.md)", backup=False))
    return changes


def _has_command(group: dict[str, Any], command: str) -> bool:
    return any(h.get("command") == command for h in group.get("hooks", []) if isinstance(h, dict))


def _json_server(path: Path, keys: tuple[str, ...], entry: dict[str, Any], uninstall: bool, hint: str = "") -> Change:
    """Add or remove `SERVER` in the JSON object at `keys` of a JSON config file."""
    before = _read(path)
    snippet = _dump_json(_nest(keys, {SERVER: entry}))
    if hint:
        snippet += hint + "\n"
    data = _load_json(path, before)
    table = data
    for key in keys:
        table = table.get(key) if isinstance(table, dict) else None
    current = table.get(SERVER) if isinstance(table, dict) else None
    where = ".".join((*keys, SERVER))
    if uninstall:
        if current is None:
            return Change(path, before, before, [], snippet)
        del table[SERVER]
        return Change(path, before, _dump_json(data), [f"remove {where}"], snippet)
    if current == entry:
        return Change(path, before, before, [], snippet)
    _table(data, *keys)[SERVER] = entry
    return Change(path, before, _dump_json(data), [f"{'update' if current else 'add'} {where}"], snippet)


def _nest(keys: tuple[str, ...], value: dict[str, Any]) -> dict[str, Any]:
    for key in reversed(keys):
        value = {key: value}
    return value


# --- Codex --------------------------------------------------------------------------


def codex_config() -> Path:
    base = os.environ.get("CODEX_HOME")
    return (Path(base).expanduser() if base else Path.home() / ".codex") / "config.toml"


_SECTION = re.compile(rf"^\s*\[\s*mcp_servers\s*\.\s*(?:{SERVER}|\"{SERVER}\")\s*(?:\]|\.)")
_HEADER = re.compile(r"^\s*\[")


def _toml_str(s: str) -> str:
    return json.dumps(s)  # a JSON string is a valid TOML basic string


def plan_codex(uninstall: bool, *, recall: str) -> list[Change]:
    path = codex_config()
    before = _read(path)
    block = f"[mcp_servers.{SERVER}]\ncommand = {_toml_str(recall)}\nargs = [\"mcp\"]\n"
    try:
        data = tomllib.loads(before or "")
    except tomllib.TOMLDecodeError as e:
        raise InstallError(f"{tilde(path)} is not valid TOML ({e}); fix it or add the snippet by hand") from None
    current = (data.get("mcp_servers") or {}).get(SERVER)
    wanted = {"command": recall, "args": ["mcp"]}
    if (current is None and uninstall) or (current == wanted and not uninstall):
        return [Change(path, before, before, [], block)]

    kept, inside = [], False
    for line in (before or "").splitlines(keepends=True):
        if _HEADER.match(line):
            inside = bool(_SECTION.match(line))
        if not inside:
            kept.append(line)
    text = "".join(kept).rstrip("\n")
    if (tomllib.loads(text).get("mcp_servers") or {}).get(SERVER) is not None:
        raise InstallError(f"{tilde(path)} defines mcp_servers.{SERVER} inline; edit it by hand")
    if uninstall:
        after = text + "\n" if text else ""
        note = f"remove [mcp_servers.{SERVER}]"
    else:
        after = (text + "\n\n" if text else "") + block
        note = f"{'update' if current else 'add'} [mcp_servers.{SERVER}]"
    tomllib.loads(after)  # never write a file Codex cannot read
    return [Change(path, before, after, [note], block)]


# --- OpenCode -----------------------------------------------------------------------


def opencode_config() -> Path:
    if env := os.environ.get("OPENCODE_CONFIG"):
        return Path(env).expanduser()
    base = os.environ.get("XDG_CONFIG_HOME")
    folder = (Path(base) if base else Path.home() / ".config") / "opencode"
    jsonc = folder / "opencode.jsonc"
    return jsonc if jsonc.exists() else folder / "opencode.json"


def plan_opencode(uninstall: bool, *, recall: str) -> list[Change]:
    path = opencode_config()
    before = _read(path)
    data = _load_json(path, before)
    mcp = data.get("mcp") if isinstance(data.get("mcp"), dict) else {}
    # Older OpenCode configs put servers right under "mcp"; newer ones under "mcp.servers".
    legacy = "servers" not in mcp and any(isinstance(v, dict) and "type" in v for v in mcp.values())
    entry: dict[str, Any] = {"type": "local", "command": [recall, "mcp"]}
    if legacy:
        entry["enabled"] = True
    keys = ("mcp",) if legacy else ("mcp", "servers")
    change = _json_server(path, keys, entry, uninstall)
    if before is None and change.after is not None:
        fresh = {"$schema": "https://opencode.ai/config.json", **json.loads(change.after)}
        change.after = _dump_json(fresh)
    return [change]


# --- running a plan -----------------------------------------------------------------


def apply(changes: list[Change], out=sys.stdout) -> None:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    for c in changes:
        if not c.changed:
            continue
        if c.before is not None and c.backup:
            backup = c.path.with_name(f"{c.path.name}.bak-agentrecall-{stamp}")
            shutil.copy2(c.path, backup)
            print(f"  backup: {tilde(backup)}", file=out)
        if c.after is None:
            c.path.unlink()
            _prune(c.path.parent)
            continue
        c.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = c.path.with_name(f".{c.path.name}.agentrecall-tmp")
        tmp.write_text(c.after)
        if c.before is not None:
            shutil.copymode(c.path, tmp)
        os.replace(tmp, c.path)


def _prune(folder: Path) -> None:
    try:
        folder.rmdir()  # only the skill's own folder, and only if empty
    except OSError:
        pass


def report(changes: list[Change], show_snippets: bool, out=sys.stdout) -> None:
    for c in changes:
        notes = c.notes if c.changed else [n for n in c.notes if n.startswith("note:")] or ["already up to date"]
        print(f"{tilde(c.path)}:", file=out)
        for n in notes:
            print(f"  {n}", file=out)
        if show_snippets and c.snippet:
            print("  snippet:", file=out)
            print("".join(f"    {line}\n" for line in c.snippet.rstrip("\n").splitlines()), end="", file=out)


AGENTS = ("claude", "codex", "opencode")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="recall install", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("agent", choices=AGENTS)
    ap.add_argument("--print", dest="dry", action="store_true", help="show what would change and the snippets, write nothing")
    ap.add_argument("--uninstall", action="store_true", help="remove what install added")
    ap.add_argument("--command", metavar="PATH", help="the recall executable to put in the config (default: this one)")
    ap.add_argument("--no-mcp", action="store_true", help="skip the MCP server entry")
    ap.add_argument("--no-hook", action="store_true", help="claude: skip the background search hook")
    ap.add_argument("--no-skill", action="store_true", help="claude: skip the /recall skill")
    return ap


def main(argv: list[str], out=sys.stdout) -> int:
    a = build_parser().parse_args(argv)
    recall = a.command or executable("recall")
    inject = str(Path(a.command).with_name("recall-inject")) if a.command and os.sep in a.command else (
        "recall-inject" if a.command else executable("recall-inject"))
    try:
        if a.agent == "claude":
            changes = plan_claude(a.uninstall, hook=not a.no_hook, mcp=not a.no_mcp, skill=not a.no_skill,
                                  recall=recall, inject=inject)
        elif a.no_mcp:
            changes = []
        elif a.agent == "codex":
            changes = plan_codex(a.uninstall, recall=recall)
        else:
            changes = plan_opencode(a.uninstall, recall=recall)
    except InstallError as e:
        raise SystemExit(f"recall install: {e}") from None
    report(changes, a.dry, out)
    if a.dry:
        print("(--print: nothing written)", file=out)
        return 0
    if any(c.changed for c in changes):
        apply(changes, out)
        print(f"done. Restart {a.agent} to pick it up.", file=out)
    return 0
