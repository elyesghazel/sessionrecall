"""Timestamps: transcripts store UTC, output is local time with weekday and age."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


def local(ts: str) -> datetime | None:
    try:
        d = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d.astimezone()  # a naive value is taken as local time


def stamp(ts: str) -> str:
    d = local(ts)
    return d.strftime("%a %Y-%m-%d %H:%M") if d else ts[:16]


def ago(ts: str) -> str:
    d = local(ts)
    if not d:
        return ""
    n = (datetime.now().astimezone().date() - d.date()).days
    return "today" if n == 0 else "yesterday" if n == 1 else f"{n} days ago"


def now_line() -> str:
    n = datetime.now().astimezone()
    return f"now: {n:%a %Y-%m-%d %H:%M %Z}, ISO week {n.isocalendar().week}; times below are local"


@dataclass(frozen=True)
class DateFilter:
    since_days: int | None = None
    date_from: str | None = None  # YYYY-MM-DD, local, inclusive
    date_to: str | None = None

    @property
    def active(self) -> bool:
        return bool(self.since_days or self.date_from or self.date_to)

    def match(self, ts: str) -> bool:
        d = local(ts)
        if not d:
            return not self.active
        if self.since_days and d < datetime.now().astimezone() - timedelta(days=self.since_days):
            return False
        day = d.date().isoformat()
        return (not self.date_from or day >= self.date_from) and (not self.date_to or day <= self.date_to)
