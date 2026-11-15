"""Semantic and exact search. Both return plain data; the CLI formats it."""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass

import numpy as np

from agentrecall.index import Embedder
from agentrecall.sources import Source, Turn, all_sessions
from agentrecall.store import Chunk
from agentrecall.timeutil import DateFilter

HITS_PER_SESSION = 3
# Semantic score bonus when every query word also appears literally in the chunk.
EXACT_WORD_BOOST = 0.08


@dataclass(frozen=True)
class Filters:
    dates: DateFilter = DateFilter()
    role: str | None = None
    exclude: frozenset[str] = frozenset()  # session ids

    def match(self, sid: str, ts: str, role: str) -> bool:
        return sid not in self.exclude and (not self.role or role == self.role) and self.dates.match(ts)


@dataclass(frozen=True)
class SemanticHit:
    chunk: Chunk
    score: float
    match: re.Match[str] | None  # first literal query word in the text, for the snippet


@dataclass(frozen=True)
class SessionResult:
    sid: str
    source: str
    path: str
    score: float  # of the best hit
    best_ts: str  # when the best hit was said
    hits: list[SemanticHit]  # in time order


def query_words(terms: Iterable[str]) -> list[re.Pattern[str]]:
    return [re.compile(re.escape(w), re.I) for w in terms if len(w) >= 3]


def semantic_search(
    chunks: list[Chunk], embedder: Embedder, terms: list[str], filters: Filters, limit: int
) -> list[SessionResult]:
    """Rank chunks by meaning, then group the best few per session."""
    rows = [c for c in chunks if filters.match(c.sid, c.ts, c.role)]
    if not rows:
        return []
    q = embedder.embed_query(" ".join(terms))
    matrix = np.frombuffer(b"".join(c.vec for c in rows), dtype=np.float32).reshape(len(rows), -1)
    scores = matrix @ q
    words = query_words(terms)
    if words:
        literal = np.array([sum(bool(w.search(c.text)) for w in words) / len(words) for c in rows])
        scores = scores + EXACT_WORD_BOOST * literal

    # Walk down the ranking until a session beyond `limit` shows up; the extra hits of
    # the sessions already in come from the chunks ranked above that point.
    best: dict[str, list[int]] = {}
    for i in np.argsort(-scores):
        sid = rows[i].sid
        if sid not in best:
            if len(best) == limit:
                break
            best[sid] = []
        if len(best[sid]) < HITS_PER_SESSION:
            best[sid].append(int(i))

    results = []
    for sid, idx in best.items():
        top = rows[idx[0]]
        hits = [
            SemanticHit(rows[i], float(scores[i]), next((m for w in words if (m := w.search(rows[i].text))), None))
            for i in sorted(idx, key=lambda i: rows[i].ts)
        ]
        results.append(SessionResult(sid, top.source, top.path, float(scores[idx[0]]), top.ts, hits))
    return results


@dataclass(frozen=True)
class ExactHit:
    source: Source
    sid: str
    path: str
    turn: Turn
    match: re.Match[str]


def exact_search(
    sources: Iterable[Source], patterns: list[re.Pattern[str]], filters: Filters
) -> Iterator[ExactHit]:
    """Turns that match every pattern, newest session first."""
    for src, session in all_sessions(sources, set(filters.exclude)):
        turns, _ = src.turns(session.path, 0)
        for t in turns:
            if not filters.match(session.id, t.ts, t.role):
                continue
            matches = [p.search(t.text) for p in patterns]
            if all(matches):
                yield ExactHit(src, session.id, str(session.path), t, matches[0])


def snippet(text: str, match: re.Match[str] | None, width: int = 160) -> str:
    start = max(0, match.start() - width // 2) if match else 0
    out = text[start : start + width].replace("\n", " ")
    return ("..." if start else "") + out + ("..." if start + width < len(text) else "")
