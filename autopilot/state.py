"""SQLite state store: what the tool has seen and what it has asked people to do.

One file (state/autopilot.db) so the tool runs anywhere with no setup. The
schema is plain SQL, so moving to Postgres or a warehouse later is a
connection-string change, not a rewrite.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable

import pandas as pd

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at    TEXT NOT NULL,
    as_of         TEXT NOT NULL,
    source        TEXT NOT NULL,
    fingerprint   TEXT NOT NULL,
    rows_in       INTEGER, new INTEGER, updated INTEGER, unchanged INTEGER,
    dq_issues     INTEGER, actions_created INTEGER, actions_refreshed INTEGER,
    actions_superseded INTEGER, seconds REAL
);
CREATE TABLE IF NOT EXISTS accounts (
    account_id      TEXT PRIMARY KEY,
    row_hash        TEXT NOT NULL,
    segment         TEXT, play TEXT, owner TEXT, priority INTEGER,
    gmv_total_6m    REAL,
    first_seen_run  INTEGER, last_seen_run INTEGER, last_changed_run INTEGER,
    data_json       TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS account_history (
    account_id TEXT, run_id INTEGER, change_type TEXT, row_hash TEXT,
    segment TEXT, play TEXT, broker_reliance_pct REAL, gmv_total_6m REAL, detail TEXT
);
CREATE INDEX IF NOT EXISTS ix_hist_acc ON account_history(account_id);
CREATE TABLE IF NOT EXISTS actions (
    action_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id   TEXT NOT NULL,
    run_id       INTEGER NOT NULL,
    play         TEXT NOT NULL, title TEXT, owner TEXT, channel TEXT,
    priority     INTEGER, status TEXT NOT NULL,
    created_at   TEXT, updated_at TEXT, due_date TEXT, contacted_at TEXT,
    why TEXT, goal TEXT, subject TEXT, message TEXT, call_note TEXT, note TEXT
);
CREATE INDEX IF NOT EXISTS ix_actions_acc ON actions(account_id, status);
CREATE TABLE IF NOT EXISTS dq_issues (
    run_id INTEGER, account_id TEXT, field TEXT, issue TEXT, action TEXT,
    severity TEXT, original TEXT, fixed TEXT
);
CREATE TABLE IF NOT EXISTS inputs (
    fingerprint TEXT PRIMARY KEY, source TEXT, first_run_id INTEGER, last_run_id INTEGER
);
"""

OPEN_STATUSES = ("open",)
CLOSED_BY_PERSON = ("sent", "done", "snoozed", "dismissed")


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    @contextmanager
    def tx(self):
        try:
            yield self.conn
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    # ---- reads -------------------------------------------------------------
    def known_hashes(self) -> dict[str, str]:
        return dict(self.conn.execute("SELECT account_id, row_hash FROM accounts").fetchall())

    def account_rows(self, ids: Iterable[str] | None = None) -> pd.DataFrame:
        if ids is None:
            rows = self.conn.execute("SELECT data_json FROM accounts").fetchall()
        else:
            ids = list(ids)
            if not ids:
                return pd.DataFrame()
            rows = []
            for i in range(0, len(ids), 900):  # SQLite variable limit
                chunk = ids[i:i + 900]
                q = f"SELECT data_json FROM accounts WHERE account_id IN ({','.join('?' * len(chunk))})"
                rows += self.conn.execute(q, chunk).fetchall()
        return pd.DataFrame([json.loads(r[0]) for r in rows])

    def open_actions(self) -> pd.DataFrame:
        return pd.read_sql_query("SELECT * FROM actions WHERE status = 'open'", self.conn)

    def latest_actions(self, account_ids: list[str]) -> dict[str, sqlite3.Row]:
        """Most recent action per account (any status)."""
        out: dict[str, sqlite3.Row] = {}
        for i in range(0, len(account_ids), 900):
            chunk = account_ids[i:i + 900]
            q = (f"SELECT * FROM actions WHERE action_id IN (SELECT MAX(action_id) FROM actions "
                 f"WHERE account_id IN ({','.join('?' * len(chunk))}) GROUP BY account_id)")
            for r in self.conn.execute(q, chunk):
                out[r["account_id"]] = r
        return out

    def runs(self) -> pd.DataFrame:
        return pd.read_sql_query("SELECT * FROM runs ORDER BY run_id", self.conn)

    def history(self, account_id: str | None = None) -> pd.DataFrame:
        if account_id:
            return pd.read_sql_query("SELECT * FROM account_history WHERE account_id = ? ORDER BY run_id",
                                     self.conn, params=[account_id])
        return pd.read_sql_query("SELECT * FROM account_history ORDER BY run_id", self.conn)

    def dq(self, run_id: int | None = None) -> pd.DataFrame:
        if run_id is None:
            return pd.read_sql_query("SELECT * FROM dq_issues", self.conn)
        return pd.read_sql_query("SELECT * FROM dq_issues WHERE run_id = ?", self.conn, params=[run_id])

    def input_seen(self, fingerprint: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM inputs WHERE fingerprint = ?", [fingerprint]).fetchone()

    # ---- writes ------------------------------------------------------------
    def start_run(self, started_at: str, as_of: str, source: str, fingerprint: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO runs (started_at, as_of, source, fingerprint) VALUES (?, ?, ?, ?)",
            [started_at, as_of, source, fingerprint])
        return int(cur.lastrowid)

    def finish_run(self, run_id: int, **stats) -> None:
        cols = ", ".join(f"{k} = ?" for k in stats)
        self.conn.execute(f"UPDATE runs SET {cols} WHERE run_id = ?", [*stats.values(), run_id])
        fp, src = self.conn.execute("SELECT fingerprint, source FROM runs WHERE run_id = ?", [run_id]).fetchone()
        self.conn.execute(
            "INSERT INTO inputs (fingerprint, source, first_run_id, last_run_id) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(fingerprint) DO UPDATE SET last_run_id = excluded.last_run_id",
            [fp, src, run_id, run_id])

    def save_issues(self, run_id: int, issues: pd.DataFrame) -> None:
        if issues.empty:
            return
        rows = issues.assign(run_id=run_id)[
            ["run_id", "account_id", "field", "issue", "action", "severity", "original", "fixed"]
        ].astype(object).values.tolist()
        self.conn.executemany("INSERT INTO dq_issues VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)

    def upsert_accounts(self, rows: list[tuple]) -> None:
        self.conn.executemany(
            """INSERT INTO accounts (account_id, row_hash, segment, play, owner, priority, gmv_total_6m,
                   first_seen_run, last_seen_run, last_changed_run, data_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(account_id) DO UPDATE SET
                   row_hash = excluded.row_hash, segment = excluded.segment, play = excluded.play,
                   owner = excluded.owner, priority = excluded.priority, gmv_total_6m = excluded.gmv_total_6m,
                   last_seen_run = excluded.last_seen_run, last_changed_run = excluded.last_changed_run,
                   data_json = excluded.data_json""",
            rows)

    def touch_seen(self, run_id: int, ids: list[str]) -> None:
        self.conn.executemany("UPDATE accounts SET last_seen_run = ? WHERE account_id = ?",
                              [(run_id, i) for i in ids])

    def add_history(self, rows: list[tuple]) -> None:
        self.conn.executemany("INSERT INTO account_history VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)

    def insert_actions(self, rows: list[dict]) -> None:
        if not rows:
            return
        cols = list(rows[0].keys())
        self.conn.executemany(
            f"INSERT INTO actions ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
            [[r[c] for c in cols] for r in rows])

    def update_actions(self, rows: list[dict]) -> None:
        for r in rows:
            aid = r.pop("action_id")
            cols = ", ".join(f"{k} = ?" for k in r)
            self.conn.execute(f"UPDATE actions SET {cols} WHERE action_id = ?", [*r.values(), aid])

    def mark(self, account_id: str, status: str, when: str, note: str | None = None) -> int:
        cur = self.conn.execute(
            """UPDATE actions SET status = ?, updated_at = ?, note = COALESCE(?, note),
                   contacted_at = CASE WHEN ? IN ('sent', 'done') THEN ? ELSE contacted_at END
               WHERE account_id = ? AND status = 'open'""",
            [status, when, note, status, when, account_id])
        self.conn.commit()
        return cur.rowcount
