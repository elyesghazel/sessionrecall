"""recall - search your past coding-agent sessions.

  recall <query...>            semantic search, ranked by meaning (exact words get a boost)
  recall --exact <terms...>    turns containing all terms (case-insensitive)
  recall -r '<regex>'          a regular expression instead of terms
  recall --since 7 <query>     only the last 7 days
  recall --from 2026-01-05 --to 2026-01-11 <query>   only that local date range (inclusive)
  recall --agent codex <query> only one agent's sessions (claude, codex, opencode)
  recall --list                recent sessions (with --from/--to: sessions active then)
  recall --show <session-id>   print a session's conversation (an id prefix is enough)
  recall --show <id> --digest  only user turns and final replies, trimmed
  recall --index               embed new turns (run it from cron or a timer)
  recall --forget [<id>]       hide a session from recall for good (default: this one)
  recall --unforget <id>       undo that;  recall --forgotten  lists them

Everything recall prints passes through secret redaction. The index lives in the cache
dir and keeps chunks of transcripts deleted since, so search still finds them.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from datetime import datetime
from functools import cached_property
from pathlib import Path
from typing import TextIO

from agentrecall import __version__
from agentrecall.config import Config, ConfigError, load_config
from agentrecall.index import Embedder, FastEmbedder, update_index
from agentrecall.redact import RedactingWriter
from agentrecall.search import Filters, exact_search, semantic_search, snippet
from agentrecall.sources import REGISTRY, Session, Source, all_sessions, build_sources, id_matches, short_id
from agentrecall.store import Forgotten, Store
from agentrecall.timeutil import DateFilter, ago, now_line, stamp
from agentrecall.titles import load_titles


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="recall", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("terms", nargs="*")
    ap.add_argument("-r", "--regex")
    ap.add_argument("--exact", action="store_true", help="plain substring match on all terms")
    ap.add_argument("--since", type=int, metavar="DAYS")
    ap.add_argument("--from", dest="date_from", type=_date, metavar="YYYY-MM-DD",
                    help="only turns on or after this local date")
    ap.add_argument("--to", dest="date_to", type=_date, metavar="YYYY-MM-DD",
                    help="only turns on or before this local date")
    ap.add_argument("--role", choices=["user", "assistant"])
    ap.add_argument("--agent", choices=sorted(REGISTRY), help="only sessions of this agent")
    ap.add_argument("-n", "--limit", type=int,
                    help="max sessions (semantic, default 8), hits (exact, default 40) or rows (--list, default 40)")
    ap.add_argument("--list", action="store_true", help="list recent sessions")
    ap.add_argument("--exclude", metavar="REGEX", help="with --list: drop sessions whose title or first message matches")
    ap.add_argument("--show", metavar="SESSION")
    ap.add_argument("--digest", type=int, nargs="?", const=1200, default=0, metavar="CHARS",
                    help="with --show: user turns and final replies, each cut to CHARS")
    ap.add_argument("--index", action="store_true", help="embed new turns and exit")
    ap.add_argument("--forget", nargs="?", const="", metavar="SESSION",
                    help="hide a session from recall (default: the current one)")
    ap.add_argument("--unforget", metavar="SESSION")
    ap.add_argument("--forgotten", action="store_true", help="list forgotten sessions")
    ap.add_argument("--config", type=Path, metavar="PATH", help="config file (default ~/.config/agentrecall/config.toml)")
    ap.add_argument("--version", action="version", version=f"agentrecall {__version__}")
    return ap


def _date(value: str) -> str:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date().isoformat()
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a YYYY-MM-DD date: {value}") from None


class App:
    """What one recall invocation needs, built lazily so --list never loads the model."""

    def __init__(
        self, config: Config, out: TextIO, embedder: Embedder | None = None, agent: str | None = None
    ) -> None:
        self.config = config
        self.out = out
        self._embedder = embedder
        self.agent = agent

    def print(self, *parts: object) -> None:
        print(*parts, file=self.out)

    @cached_property
    def sources(self) -> list[Source]:
        return build_sources(self.config)

    @cached_property
    def by_name(self) -> dict[str, Source]:
        return {s.name: s for s in self.sources}

    @cached_property
    def forgotten(self) -> Forgotten:
        return Forgotten(self.config.forgotten_path)

    @cached_property
    def titles(self) -> dict[str, str]:
        return load_titles(self.config.titles_command)

    @cached_property
    def current_session(self) -> str | None:
        return next((sid for s in self.sources if (sid := s.current_session_id())), None)

    @cached_property
    def embedder(self) -> Embedder:
        return self._embedder or FastEmbedder(self.config.model_id, self.config.models_dir, self.config.threads)

    @cached_property
    def store(self) -> Store:
        store = Store(self.config.index_path)
        size, overlap = self.config.chunking
        if store.ensure_signature(f"{self.config.model_id}|{size}|{overlap}"):
            print("recall: model or chunking changed, rebuilding the index", file=sys.stderr)
        return store

    def sessions(self) -> list[tuple[Source, Session]]:
        found = all_sessions(self.sources, self.forgotten.ids())
        return [(src, s) for src, s in found if not self.agent or src.name == self.agent]

    def project(self, source_name: str, path: str) -> str:
        src = self.by_name.get(source_name)
        if not (src.exists(Path(path)) if src else Path(path).exists()):
            return "(transcript deleted)"
        return src.project(Path(path)) if src else source_name

    def header(self, sid: str, agent: str, where: str, extra: str = "") -> str:
        return "  ".join(p for p in (f"== {short_id(sid)}", agent, where, self.titles.get(sid, ""), extra) if p)

    # --- commands ---------------------------------------------------------------

    def index(self) -> None:
        stats = update_index(self.store, self.sources, self.embedder, self.config.chunking, self.forgotten.ids())
        if sys.stderr.isatty():
            print(f"recall: indexed {stats.added} new chunks", file=sys.stderr)

    def semantic(self, terms: list[str], filters: Filters, limit: int) -> None:
        stats = update_index(self.store, self.sources, self.embedder, self.config.chunking,
                             self.forgotten.ids(), cap=self.config.inline_max)
        chunks = self.store.chunks()
        results = semantic_search(chunks, self.embedder, terms, filters, limit)
        if not results:
            if stats.waiting and not chunks:
                raise SystemExit(f"index still building ({stats.waiting} chunks to go), run recall --index")
            raise SystemExit("index is empty, run recall --index" if not chunks else "nothing found")
        self.print(now_line())
        for r in results:
            self.print()
            self.print(self.header(r.sid, r.source, self.project(r.source, r.path),
                                   f"[{r.score:.2f}, best hit {ago(r.best_ts)}]"))
            for h in r.hits:
                c = h.chunk
                self.print(f"  {stamp(c.ts)} ({ago(c.ts)}) {c.role[:4]}: {snippet(c.text, h.match, 200)}")
        if stats.waiting:
            self.print(f"\n(index catching up: {stats.waiting} newer chunks not searched yet, run recall --index)")

    def exact(self, patterns: list[re.Pattern[str]], filters: Filters, limit: int) -> None:
        self.print(now_line())
        shown, last = 0, None
        for hit in exact_search(self.sources, patterns, filters):
            if hit.sid != last:
                self.print()
                self.print(self.header(hit.sid, hit.source.name, hit.source.project(Path(hit.path))))
                last = hit.sid
            t = hit.turn
            self.print(f"  {stamp(t.ts)} ({ago(t.ts)}) {t.role[:4]}: {snippet(t.text, hit.match)}")
            shown += 1
            if shown >= limit:
                self.print(f"\n(limit {limit} reached, use -n)")
                return

    def list(self, dates: DateFilter, exclude: str | None, limit: int) -> None:
        self.print(now_line())
        shown = 0
        cutoff = time.time() - dates.since_days * 86400 if dates.since_days else 0
        for src, s in self.sessions():
            if s.mtime < cutoff:
                continue
            if dates.date_from and datetime.fromtimestamp(s.mtime).date().isoformat() < dates.date_from:
                continue  # last written before the range, so no turns in it
            turns, _ = src.turns(s.path, 0)
            first = next((t.text for t in turns if t.role == "user"), "")
            title = self.titles.get(s.id, "")
            if exclude and re.search(exclude, f"{title} {first}", re.I):
                continue
            if dates.date_from or dates.date_to:
                inside = [t.ts for t in turns if dates.match(t.ts)]
                if not inside:
                    continue
                when = f"{stamp(min(inside))} - {stamp(max(inside))[-5:]}, {len(inside)} turns"
            else:
                when = datetime.fromtimestamp(s.mtime).strftime("%a %Y-%m-%d %H:%M")
            label = title or first.replace("\n", " ")[:70]
            mark = "  (this session)" if s.id == self.current_session else ""
            self.print(f"{when}  {short_id(s.id)}  {src.name:<8} {src.project(s.path):<28} {label}{mark}")
            shown += 1
            if shown >= limit:
                break

    def show(self, prefix: str, digest: int) -> None:
        matches = [(src, s) for src, s in self.sessions() if id_matches(s.id, prefix)]
        ids = {s.id for _, s in matches}
        if not ids:
            raise SystemExit(f"no session {prefix}")
        if len(ids) > 1:
            raise SystemExit(f"{prefix}: {len(ids)} sessions match, give more of the id")
        src, s = matches[0]
        title = self.titles.get(s.id)
        self.print(f"# {title + ' ' if title else ''}{s.id} ({src.project(s.path)})")
        self.print(now_line())
        self.print()
        turns, _ = src.turns(s.path, 0)
        for i, t in enumerate(turns):
            text = t.text
            if digest:
                # User turns plus the last assistant reply before the next user turn.
                final = i + 1 == len(turns) or turns[i + 1].role == "user"
                if t.role == "assistant" and not final:
                    continue
                text = text if len(text) <= digest else text[:digest] + " [...]"
            self.print(f"--- {t.role} {stamp(t.ts)} ({ago(t.ts)})\n{text}\n")

    def forget(self, arg: str, undo: bool) -> None:
        sid = self._resolve_id(arg or self.current_session or "", undo)
        gone = self.forgotten.ids()
        self.forgotten.save(gone - {sid} if undo else gone | {sid})
        if undo:
            self.store.unread_session(sid)  # embedded again on the next index run
        else:
            self.store.drop_session(sid)
        self.print(f"{'restored' if undo else 'forgotten'}: {sid} {self.titles.get(sid, '')}".rstrip())
        if not undo:
            self.print("Its chunks are gone from the index, and no recall mode (search, --list, --show)\n"
                       "will see it again, including turns added later. The transcript file is untouched.")

    def _resolve_id(self, prefix: str, undo: bool) -> str:
        if not prefix:
            raise SystemExit("no session id given and not run from inside an agent session")
        known = self.forgotten.ids() if undo else (
            {s.id for src in self.sources for s in src.sessions()}
            | {sid for (sid,) in self.store.db.execute("select distinct sid from chunks")}
        )
        if prefix in known:
            return prefix
        ids = {i for i in known if id_matches(i, prefix)}
        if len(ids) != 1:
            raise SystemExit(f"{prefix}: {'no' if not ids else 'more than one'} matching session")
        return ids.pop()

    def list_forgotten(self) -> None:
        for sid in sorted(self.forgotten.ids()):
            self.print(f"{sid} {self.titles.get(sid, '')}".rstrip())


def main(argv: list[str] | None = None, *, embedder: Embedder | None = None) -> int:
    ap = build_parser()
    a = ap.parse_args(argv)
    try:
        config = load_config(a.config)
        app = App(config, RedactingWriter(sys.stdout), embedder, a.agent)
        return run(ap, a, app)
    except ConfigError as e:
        raise SystemExit(f"recall: {e}") from None
    except BrokenPipeError:  # e.g. `recall --list | head`
        sys.stderr.close()
        return 0


def run(ap: argparse.ArgumentParser, a: argparse.Namespace, app: App) -> int:
    if a.index:
        app.index()
        return 0
    if a.forget is not None or a.unforget:
        app.forget(a.unforget or a.forget, undo=bool(a.unforget))
        return 0
    if a.forgotten:
        app.list_forgotten()
        return 0
    if a.show:
        app.show(a.show, a.digest)
        return 0

    dates = DateFilter(a.since, a.date_from, a.date_to)
    if a.list:
        app.list(dates, a.exclude, a.limit or 40)
        return 0
    if not a.terms and not a.regex:
        ap.error("give search terms, -r, --list or --show")

    exclude = app.forgotten.ids() | ({app.current_session} if app.current_session else set())
    filters = Filters(dates, a.role, frozenset(exclude), a.agent)
    if a.regex or a.exact:
        try:
            pats = [re.compile(a.regex, re.I)] if a.regex else [re.compile(re.escape(t), re.I) for t in a.terms]
        except re.error as e:
            ap.error(f"bad regex: {e}")
        app.exact(pats, filters, a.limit or 40)
    else:
        app.semantic(a.terms, filters, a.limit or 8)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
