"""Write the synthetic demo corpus: a fake HOME with Claude Code, Codex and OpenCode sessions.

Every session below is made up for the demo. Run it again after editing:

    python demo/build_corpus.py          # writes demo/corpus/
"""

from __future__ import annotations

import json
import shutil
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

OUT = Path(__file__).parent / "corpus"
NS = uuid.UUID("6f1d2c3b-0000-4000-8000-000000000000")

# (agent, project dir, start time UTC, title, [(role, text), ...])
# Roles alternate user / assistant. Tool calls are added automatically where
# an agent would have run something, so the transcripts look like the real formats.
SESSIONS = [
    ("claude", "/work/tally", "2026-09-08T08:12", "Import bank CSVs", [
        ("user", "tally needs an `import` subcommand that reads a bank CSV export and appends the rows to the ledger file."),
        ("assistant", "I added `tally import <file>` with clap. It parses the CSV with serde into a `Row { date, amount, payee }`, skips the header, and appends to the ledger. Bad lines are reported with their line number instead of aborting the whole import."),
        ("user", "Some banks use a comma as the decimal separator. Can it cope with that?"),
        ("assistant", "Yes. There is now a `--decimal-comma` flag, and if it is not given the importer guesses from the first ten amounts. Amounts are parsed into integer cents, so there is no float rounding."),
    ]),
    ("opencode", "/work/shopfront", "2026-09-14T13:40", "Move off create-react-app", [
        ("user", "The dev server takes 40 seconds to start and create-react-app is unmaintained. Move shopfront to Vite."),
        ("assistant", "Done. I replaced react-scripts with Vite and @vitejs/plugin-react, moved index.html to the project root, and renamed the REACT_APP_ env variables to VITE_. Cold start is now about 900 ms."),
        ("user", "Jest broke after that."),
        ("assistant", "I switched the tests to Vitest with the jsdom environment. The existing tests run unchanged apart from replacing `jest.fn` with `vi.fn`."),
    ]),
    ("claude", "/work/infra", "2026-09-20T18:05", "Postgres 15 to 16", [
        ("user", "Upgrade the main database from Postgres 15 to 16. It is about 80 GB, downtime should be short."),
        ("assistant", "Plan: take a fresh base backup, stop the app, run `pg_upgrade --link` from the 15 to the 16 cluster, start 16, run `vacuumdb --analyze-in-stages`, then start the app again. With --link the data files are hard-linked, so the upgrade itself takes seconds, not a full copy."),
        ("user", "Ok, go. Keep the old cluster until we are sure."),
        ("assistant", "The upgrade finished in 41 seconds and the app is back. The old 15 data directory is still there but must not be started any more, because --link shares the files. I left a note in infra/README to delete it after a week."),
    ]),
    ("claude", "/work/tally", "2026-10-02T09:30", "Release binaries", [
        ("user", "People want tally binaries for Raspberry Pi. Build releases for aarch64 too."),
        ("assistant", "I added a GitHub Actions release workflow that runs on tags. It uses `cross` to build x86_64 and aarch64 Linux binaries, strips them, and uploads them with checksums to the release."),
        ("user", "The aarch64 build fails on openssl."),
        ("assistant", "reqwest pulled in native-tls. I switched it to the rustls feature, so there is no openssl dependency left and the cross build passes."),
    ]),
    ("codex", "/work/billing-api", "2026-10-06T07:50", "Add column to orders", [
        ("user", "Add a non-null currency column to the orders table. It has 30 million rows and the migration must not lock it."),
        ("assistant", "I split it into three migrations: add `currency` as nullable with no default, backfill it in batches of 10,000 rows by id, then add a CHECK (currency IS NOT NULL) constraint as NOT VALID and VALIDATE it separately. Validating only takes a light lock, so writes keep going."),
        ("user", "And then make it a real NOT NULL?"),
        ("assistant", "Yes, the last migration runs ALTER COLUMN SET NOT NULL. Postgres sees the validated check constraint and skips the full table scan, then the check constraint is dropped."),
    ]),
    ("claude", "/work/shopfront", "2026-10-12T14:20", "Admin overview", [
        ("user", "Nobody uses the charts on the admin overview and the page takes eight seconds to load. Get rid of it."),
        ("assistant", "I removed the overview route and its chart components, which also drops recharts from the bundle (about 160 KB). In its place there is a small ops page: open orders, failed payments and stock alerts as three plain lists. It loads in under 300 ms."),
        ("user", "Make the ops page the default after login."),
        ("assistant", "Done. /admin now redirects to /admin/ops, and the old /admin/overview URL redirects there too so bookmarks keep working."),
    ]),
    ("opencode", "/work/infra", "2026-10-15T19:10", "Restart loop", [
        ("user", "The worker container keeps restarting every few seconds after the deploy."),
        ("assistant", "It starts before Redis accepts connections and exits on the first failed connect. I added a healthcheck to the redis service and `depends_on: redis: condition: service_healthy` to the worker, so compose waits for Redis first."),
        ("user", "Is restart: always still needed?"),
        ("assistant", "Keep it as `unless-stopped`. The healthcheck fixes the start order, the restart policy still covers crashes later."),
    ]),
    ("codex", "/work/billing-api", "2026-10-20T10:15", "Invoice test", [
        ("user", "test_invoice_due_date passes locally but fails on CI about once a day."),
        ("assistant", "It builds the due date with date.today() but the invoice service uses UTC. CI runs in UTC, so between midnight UTC and midnight local time the two dates differ by a day. I pinned the clock with freezegun in the test and made the service take an explicit `now` argument."),
        ("user", "Are there more tests like that?"),
        ("assistant", "Three more used date.today() or datetime.now() without a timezone. I changed them the same way and added a ruff rule (DTZ) so naive datetimes fail the lint."),
    ]),
    ("claude", "/work/shopfront", "2026-10-27T16:45", "Checkout test in CI", [
        ("user", "The checkout end-to-end test is red on CI every few runs, always at the payment step."),
        ("assistant", "The test clicks Pay and then waits a fixed 2 seconds before checking the confirmation. On the slower CI runners the payment mock sometimes needs longer. I replaced the sleep with `page.waitForResponse('/api/payments')` and an assertion on the confirmation heading."),
        ("user", "Run it a few times to be sure."),
        ("assistant", "I ran it 50 times with `--repeat-each 50` on the CI image: all green. I also turned on Playwright traces for retries, so the next failure comes with a recording."),
    ]),
    ("codex", "/work/billing-api", "2026-11-03T08:40", "Duplicate webhooks", [
        ("user", "Some customers were charged twice. The payment provider retries webhooks and we process each one."),
        ("assistant", "I added an idempotency table keyed on the provider's event id. The webhook handler inserts the id first with ON CONFLICT DO NOTHING and returns 200 without doing anything if the row already existed."),
        ("user", "What about two retries arriving at the same time?"),
        ("assistant", "The insert and the charge run in one transaction, and the unique key makes the second insert wait for the first. Only one of them gets to process the event."),
    ]),
    ("opencode", "/work/notes-app", "2026-11-05T20:00", "Full text search", [
        ("user", "Searching notes with LIKE is slow once there are a few thousand. Can SQLite do better?"),
        ("assistant", "Yes, with FTS5. I added a `notes_fts` virtual table with the porter tokenizer, triggers that keep it in sync on insert, update and delete, and changed the search endpoint to use MATCH with bm25 ranking."),
        ("user", "Can it highlight the matches?"),
        ("assistant", "The query now returns `snippet(notes_fts, 1, '<mark>', '</mark>', '...', 12)`, and the frontend renders the mark tags."),
    ]),
    ("codex", "/work/tally", "2026-11-08T11:25", "Faster import", [
        ("user", "Importing a 200 MB CSV takes almost a minute. Profile it."),
        ("assistant", "Most of the time goes into allocating a String per field. I switched the reader to `csv::ByteRecord`, parse the fields straight from bytes, and reuse one record buffer. The same file now imports in 6 seconds."),
    ]),
    ("claude", "/work/infra", "2026-11-10T07:35", "Expired certificate", [
        ("user", "The TLS certificate for the API expired this morning even though certbot is installed."),
        ("assistant", "The certbot timer was renewing fine, but nginx never reloaded, so it kept serving the old certificate. I added a deploy hook in /etc/letsencrypt/renewal-hooks/deploy that runs `systemctl reload nginx`, and reloaded it now."),
        ("user", "How do we notice next time before it expires?"),
        ("assistant", "I added a daily check that warns when any served certificate has less than 14 days left, using the existing alerting."),
    ]),
    ("claude", "/work/shopfront", "2026-11-13T15:05", "Dark mode", [
        ("user", "Add dark mode to shopfront, following the system setting by default."),
        ("assistant", "I moved the colors into CSS variables on :root, added a dark set under prefers-color-scheme, and a toggle in the header that can override it. The choice is kept in localStorage."),
    ]),
]


def ts(t: datetime) -> str:
    return t.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def ms(t: datetime) -> int:
    return int(t.timestamp() * 1000)


def sid(n: int) -> str:
    return str(uuid.uuid5(NS, str(n)))


def claude(n: int, cwd: str, start: datetime, turns: list[tuple[str, str]]) -> None:
    session = sid(n)
    folder = OUT / ".claude" / "projects" / cwd.replace("/", "-")
    folder.mkdir(parents=True, exist_ok=True)
    lines, t = [], start
    for i, (role, text) in enumerate(turns):
        base = {"type": role, "cwd": cwd, "sessionId": session, "timestamp": ts(t)}
        if role == "user":
            lines.append({**base, "message": {"role": "user", "content": text}})
        else:
            tool = f"toolu_{n:02d}{i:02d}"
            lines.append({**base, "message": {"role": "assistant", "content": [
                {"type": "tool_use", "id": tool, "name": "Bash", "input": {"command": "git status --short"}}]}})
            lines.append({**base, "type": "user", "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": tool, "content": "(ok)"}]}})
            lines.append({**base, "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}})
        t += timedelta(minutes=4 if role == "user" else 9)
    (folder / f"{session}.jsonl").write_text("".join(json.dumps(x) + "\n" for x in lines))


def codex(n: int, cwd: str, start: datetime, turns: list[tuple[str, str]]) -> None:
    session = sid(n)
    folder = OUT / ".codex" / "sessions" / start.strftime("%Y/%m/%d")
    folder.mkdir(parents=True, exist_ok=True)
    name = f"rollout-{start.strftime('%Y-%m-%dT%H-%M-%S')}-{session}.jsonl"

    def item(t: datetime, payload: dict) -> dict:
        return {"timestamp": ts(t), "type": "response_item", "payload": payload}

    def msg(role: str, kind: str, text: str) -> dict:
        return {"type": "message", "role": role, "content": [{"type": kind, "text": text}]}

    lines = [
        {"timestamp": ts(start), "type": "session_meta", "payload": {
            "id": session, "timestamp": ts(start), "cwd": cwd, "originator": "codex_cli_rs",
            "cli_version": "0.0.0", "source": "cli"}},
        item(start, msg("user", "input_text",
                        f"<environment_context>\n  <cwd>{cwd}</cwd>\n  <shell>bash</shell>\n</environment_context>")),
    ]
    t = start + timedelta(seconds=30)
    for i, (role, text) in enumerate(turns):
        if role == "user":
            lines.append(item(t, msg("user", "input_text", text)))
        else:
            call = f"call_{n:02d}{i:02d}"
            lines.append(item(t, {"type": "function_call", "name": "shell",
                                  "arguments": json.dumps({"command": ["git", "diff", "--stat"]}), "call_id": call}))
            lines.append(item(t, {"type": "function_call_output", "call_id": call, "output": "(ok)"}))
            lines.append(item(t, msg("assistant", "output_text", text)))
        t += timedelta(minutes=3 if role == "user" else 8)
    (folder / name).write_text("".join(json.dumps(x) + "\n" for x in lines))


def opencode(n: int, cwd: str, start: datetime, title: str, turns: list[tuple[str, str]]) -> None:
    storage = OUT / ".local" / "share" / "opencode" / "storage"
    session = f"ses_{uuid.uuid5(NS, str(n)).hex[:26]}"
    project = "proj_" + cwd.rsplit("/", 1)[-1].replace("-", "_")
    t = start
    for i, (role, text) in enumerate(turns):
        mid = f"msg_{n:02d}{i:02d}"
        info = {"id": mid, "sessionID": session, "role": role, "time": {"created": ms(t)}}
        if role == "assistant":
            info["time"]["completed"] = ms(t + timedelta(seconds=20))
        write(storage / "message" / session / f"{mid}.json", info)
        write(storage / "part" / mid / f"prt_{mid[4:]}_0.json",
              {"id": f"prt_{mid[4:]}_0", "sessionID": session, "messageID": mid, "type": "text", "text": text})
        t += timedelta(minutes=4 if role == "user" else 9)
    write(storage / "session" / project / f"{session}.json", {
        "id": session, "projectID": project, "directory": cwd, "title": title, "version": "0.15.0",
        "time": {"created": ms(start), "updated": ms(t)}})


def write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1) + "\n")


def main() -> None:
    shutil.rmtree(OUT, ignore_errors=True)
    for n, (agent, cwd, start, title, turns) in enumerate(SESSIONS, 1):
        t = datetime.fromisoformat(start).replace(tzinfo=UTC)
        if agent == "claude":
            claude(n, cwd, t, turns)
        elif agent == "codex":
            codex(n, cwd, t, turns)
        else:
            opencode(n, cwd, t, title, turns)
    print(f"wrote {len(SESSIONS)} sessions to {OUT}")


if __name__ == "__main__":
    main()
