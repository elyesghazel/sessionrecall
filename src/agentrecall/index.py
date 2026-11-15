"""Embedding and incremental indexing.

Each run reads only what was appended to a transcript since the last run (by offset),
splits the new turns into overlapping chunks, embeds them and stores unit vectors.
"""

from __future__ import annotations

import os
import warnings
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol

import numpy as np

from agentrecall.sources import Source, all_sessions
from agentrecall.store import Chunk, Store


class Embedder(Protocol):
    def embed(self, texts: Sequence[str]) -> np.ndarray:
        """Unit vectors for documents, shape (len(texts), dim), float32."""
        ...

    def embed_query(self, text: str) -> np.ndarray:
        """Unit vector for a search query, shape (dim,), float32."""
        ...


def normalize(v: np.ndarray) -> np.ndarray:
    v = np.asarray(v, dtype=np.float32)
    norm = np.linalg.norm(v, axis=-1, keepdims=True)
    return v / np.where(norm == 0, 1, norm)


class FastEmbedder:
    """fastembed (ONNX, CPU). The model downloads once into the cache dir on first use."""

    def __init__(self, model: str, cache_dir: Path, threads: int | None = None) -> None:
        self.model_name = model
        self.cache_dir = cache_dir
        self.threads = threads
        self._model = None

    def _load(self):
        if self._model is None:
            os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
            os.environ.setdefault("HF_HUB_VERBOSITY", "error")
            warnings.filterwarnings("ignore")
            from fastembed import TextEmbedding

            self._model = TextEmbedding(self.model_name, cache_dir=str(self.cache_dir), threads=self.threads)
        return self._model

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, 0), dtype=np.float32)
        return normalize(np.stack(list(self._load().embed(list(texts), batch_size=16))))

    def embed_query(self, text: str) -> np.ndarray:
        return normalize(next(iter(self._load().query_embed([text]))))


def chunk_text(text: str, size: int, overlap: int) -> list[str]:
    step = size - overlap
    return [text[i : i + size] for i in range(0, max(len(text) - overlap, 1), step)]


@dataclass(frozen=True)
class IndexStats:
    added: int  # chunks embedded in this run
    waiting: int  # chunks still unindexed (only with a cap)


@dataclass(frozen=True)
class _Pending:
    path: str
    source: str
    sid: str
    end: int
    reset: bool
    chunks: list[Chunk]


def update_index(
    store: Store,
    sources: Iterable[Source],
    embedder: Embedder,
    chunking: tuple[int, int],
    exclude: set[str] = frozenset(),
    cap: int | None = None,
) -> IndexStats:
    """Embed turns added since the last run, one session at a time.

    With `cap`, do nothing if more than `cap` chunks are waiting: a search should not stall
    on a large backlog, `recall --index` takes care of that.
    """
    with store.writer_lock() as mine:
        if not mine:
            return IndexStats(0, 0)  # another process is indexing; search what is there
        work: Iterable[_Pending] = _pending(store, sources, chunking, exclude)
        if cap is not None:
            kept, waiting = [], 0
            for p in work:  # count everything, but hold at most `cap` chunks in memory
                waiting += len(p.chunks)
                if waiting <= cap:
                    kept.append(p)
            if waiting > cap:
                return IndexStats(0, waiting)
            work = kept
        added = 0
        for p in work:
            _write(store, embedder, p)
            added += len(p.chunks)
    return IndexStats(added, 0)


def _write(store: Store, embedder: Embedder, p: _Pending) -> None:
    if p.reset:
        store.reset_file(p.path)
    if p.chunks:
        # Similar lengths per batch means less padding work for the model.
        ordered = sorted(p.chunks, key=lambda c: len(c.text))
        vecs = embedder.embed([c.text for c in ordered])
        store.add(replace(c, vec=v.astype(np.float32).tobytes()) for c, v in zip(ordered, vecs, strict=True))
    store.set_offset(p.path, p.source, p.sid, p.end)
    store.commit()


def _pending(
    store: Store, sources: Iterable[Source], chunking: tuple[int, int], exclude: set[str]
) -> Iterator[_Pending]:
    size, overlap = chunking
    done = store.offsets()
    for src, session in all_sessions(sources, exclude):
        path = str(session.path)
        offset = done.get(path, 0)
        reset = offset > session.size  # rewritten or truncated: start over
        if reset:
            offset = 0
        elif offset == session.size:
            continue
        turns, end = src.turns(session.path, offset)
        chunks = [
            Chunk(path, src.name, session.id, t.ts, t.role, piece)
            for t in turns
            for piece in chunk_text(t.text, size, overlap)
        ]
        yield _Pending(path, src.name, session.id, end, reset, chunks)
