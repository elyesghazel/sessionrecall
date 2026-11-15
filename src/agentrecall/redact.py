"""Secret redaction for everything recall prints.

Transcripts often contain API keys, tokens and passwords that were pasted into a chat.
The index and the transcripts keep the original text; only output is cleaned, so a
secret never travels on from a search result into another session.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import TextIO

MASK = "[REDACTED]"

# Values that look like placeholders ("$TOKEN", "<your key>", "{{ secret }}") stay readable.
_PLACEHOLDER_START = ("$", "<", "[", "{", "%")

_Replacement = str | Callable[[re.Match[str]], str]


def _keep_prefix(m: re.Match[str]) -> str:
    return m.group(1) + MASK


def _keyword_value(m: re.Match[str]) -> str:
    value = m.group(2)
    return m.group(1) + (value if value.startswith(_PLACEHOLDER_START) else MASK)


def _url_password(m: re.Match[str]) -> str:
    return m.group(1) + MASK + m.group(3)


PATTERNS: list[tuple[re.Pattern[str], _Replacement]] = [
    # PEM private keys, including a truncated one at the end of the text.
    (
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(-----END [A-Z ]*PRIVATE KEY-----|\Z)", re.S),
        MASK,
    ),
    # Well-known token formats.
    (
        re.compile(
            r"\b("
            r"sk-ant-[\w-]{20,}"
            r"|sk-(proj-)?[A-Za-z0-9_-]{20,}"
            r"|gh[pousr]_[A-Za-z0-9]{30,}"
            r"|github_pat_\w{30,}"
            r"|glpat-[\w-]{20,}"
            r"|xox[abposr]-[\w-]{10,}"
            r"|AKIA[0-9A-Z]{16}"
            r"|AIza[\w-]{35}"
            r"|ya29\.[\w-]{20,}"
            r"|shpat_[a-f0-9]{32}"
            r"|shpss_[a-f0-9]{32}"
            r"|whsec_\w{20,}"
            r"|rk_live_\w{20,}"
            r"|sk_live_\w{20,}"
            r"|eyJ[\w-]{10,}\.eyJ[\w-]{10,}\.[\w-]{10,}"  # JWT
            r")"
        ),
        MASK,
    ),
    # Authorization: Bearer <token>
    (re.compile(r"(?i)(\bbearer\s+)[\w.~+/=-]{16,}"), _keep_prefix),
    # password=..., api_key: "...", TOKEN=... (the keyword stays, the value goes)
    (
        re.compile(
            r"(?i)((?:password|passwd|passwort|pw|secret|token|api[_-]?key|apikey|client[_-]?secret|"
            r"private[_-]?key|access[_-]?key|auth)[\w-]*[\"']?\s*[:=]\s*[\"']?)([^\s\"'`,;]{8,})"
        ),
        _keyword_value,
    ),
    # scheme://user:password@host
    (re.compile(r"(?i)(://[^/\s:@]+:)([^@\s/]{6,})(@)"), _url_password),
]


def redact(text: str) -> str:
    """Return text with anything that looks like a secret replaced by [REDACTED]."""
    for pattern, replacement in PATTERNS:
        text = pattern.sub(replacement, text)
    return text


class RedactingWriter:
    """A text stream wrapper that redacts everything written through it."""

    def __init__(self, inner: TextIO) -> None:
        self.inner = inner

    def write(self, s: str) -> int:
        return self.inner.write(redact(s))

    def flush(self) -> None:
        self.inner.flush()

    def __getattr__(self, name: str):
        return getattr(self.inner, name)
