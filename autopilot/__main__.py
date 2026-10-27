"""Command line: python -m autopilot <command>

  run      process one export (xlsx sheet or csv) and write the outputs
  inbox    process every file in data/inbox not seen before (the daily job)
  status   runs so far, the book by segment, open actions by owner
  queue    print today's queue
  show     everything about one account
  mark     log an outcome (sent, done, snoozed, dismissed) for an account
  reset    delete the state database and outputs
"""
from __future__ import annotations

import argparse
import shutil
import sys
from datetime import date
from pathlib import Path

import pandas as pd

from .config import ROOT, load_plays, load_rules
from .ingest import IngestError
from .pipeline import run
from .report import build_queue, write_outputs
from .state import Store

DEFAULT_DB = ROOT / "state" / "autopilot.db"
DEFAULT_OUT = ROOT / "out"
INBOX = ROOT / "data" / "inbox"


def _date(s: str) -> date:
    return date.fromisoformat(s)


def _print_result(res, paths) -> None:
    if res.skipped_file:
        print(f"{res.source}: already processed (run {res.run_id}). Nothing to do. Use --force to re-apply.")
    else:
        print(f"Run {res.run_id}  {res.source}")
        print(f"  {res.rows_in} rows | {len(res.new)} new | {len(res.updated)} updated | "
              f"{len(res.unchanged)} skipped (no change) | {res.dq_issues} data fixes")
        held = f", {res.actions_skipped_recent} held back (same nudge sent recently)" if res.actions_skipped_recent else ""
        print(f"  actions: {res.actions_created} created, {res.actions_refreshed} refreshed, "
              f"{res.actions_superseded} superseded{held} | {res.seconds}s")
        for aid, detail in res.changes.items():
            print(f"    {aid}: {detail}")
    if paths:
        print(f"  outputs in {paths['dashboard'].parent}/ (open dashboard.html)")


def cmd_run(args) -> int:
    rules, plays = load_rules(), load_plays()
    store = Store(args.db)
    as_of = args.as_of or date.today()
    try:
        res = run(args.input, args.sheet, rules, plays, store, as_of=as_of, llm_top=args.llm, force=args.force)
    except IngestError as exc:
        print(f"Input problem: {exc}", file=sys.stderr)
        return 2
    if res.skipped_file:
        _print_result(res, None)  # nothing changed, so leave the last outputs as they are
        return 0
    paths = write_outputs(store, res, as_of, args.out, rules, dispatch=args.dispatch)
    _print_result(res, paths)
    return 0


def cmd_inbox(args) -> int:
    rules, plays = load_rules(), load_plays()
    store = Store(args.db)
    as_of = args.as_of or date.today()
    files = sorted(p for p in Path(args.inbox).glob("*") if p.suffix.lower() in {".xlsx", ".csv", ".tsv"})
    if not files:
        print(f"No files in {args.inbox}")
        return 0
    last_real = None
    for f in files:
        sheets = [None]
        if f.suffix.lower() == ".xlsx":
            sheets = [s for s in pd.ExcelFile(f).sheet_names if s.lower() != "readme"]
        for sheet in sheets:
            res = run(f, sheet, rules, plays, store, as_of=as_of, llm_top=args.llm)
            _print_result(res, None)
            if not res.skipped_file:
                last_real = res
    if last_real is None:
        print("Nothing new in the inbox.")
        return 0
    paths = write_outputs(store, last_real, as_of, args.out, rules, dispatch=args.dispatch)
    print(f"  outputs in {paths['dashboard'].parent}/ (open dashboard.html)")
    return 0


def cmd_status(args) -> int:
    store = Store(args.db)
    runs = store.runs()
    if runs.empty:
        print("No runs yet. Try: python -m autopilot run --input <file> --sheet Accounts")
        return 0
    print(runs[["run_id", "as_of", "source", "rows_in", "new", "updated", "unchanged", "actions_created",
                "actions_superseded"]].to_string(index=False))
    acc = store.account_rows()
    seg = acc.groupby("segment_label").agg(accounts=("account_id", "count"), gmv=("gmv_total_6m", "sum"))
    seg["share"] = (seg["gmv"] / seg["gmv"].sum() * 100).round(1)
    print("\nBook by behaviour\n" + seg.sort_values("gmv", ascending=False).to_string())
    acts = pd.read_sql_query("SELECT owner, status, COUNT(*) n FROM actions GROUP BY owner, status", store.conn)
    print("\nActions\n" + acts.pivot(index="owner", columns="status", values="n").fillna(0).astype(int).to_string())
    return 0


def cmd_queue(args) -> int:
    rules = load_rules()
    store = Store(args.db)
    q = build_queue(store, args.as_of or date.today(), rules)
    if args.owner:
        q = q[q["owner"] == args.owner]
    buckets = [args.bucket] if args.bucket else ["today", "next", "approval", "outbox"]
    for b in buckets:
        part = q[q["bucket"] == b].head(args.limit)
        if part.empty:
            continue
        print(f"\n== {b.upper()} ({int((q['bucket'] == b).sum())}) ==")
        for r in part.itertuples(index=False):
            print(f"  [{r.priority:>3}] {r.account_id}  {r.title}  ({r.owner})\n        {r.why}")
    return 0


def cmd_show(args) -> int:
    store = Store(args.db)
    acc = store.account_rows([args.account_id.upper()])
    if acc.empty:
        print(f"{args.account_id} not found")
        return 1
    a = acc.iloc[0]
    print(f"{a.account_id}  {a.segment_label}  ({a.ownership} label)  coverage: {a.coverage}")
    print(f"  {a.segment_reason}")
    print(f"  6m GMV £{a.gmv_total_6m:,.0f} | {a.orders_6m} orders ({a.manual_orders} by AM) | "
          f"recency {a.recency_state} | momentum {a.momentum_label} | health {a.health_score}")
    act = store.conn.execute("SELECT * FROM actions WHERE account_id = ? ORDER BY action_id DESC LIMIT 1",
                             [a.account_id]).fetchone()
    if act:
        print(f"\nNext action: {act['title']}  [{act['owner']}, {act['status']}, priority {act['priority']}]")
        print(f"  Why: {act['why']}")
        if act["call_note"]:
            print("\n--- Call note ---\n" + act["call_note"])
        if act["message"]:
            print(f"\n--- Message: {act['subject']} ---\n" + act["message"])
    hist = store.history(a.account_id)
    print("\nHistory")
    for h in hist.itertuples(index=False):
        print(f"  run {h.run_id}: {h.change_type}, {h.segment} -> {h.play}. {h.detail}")
    return 0


def cmd_mark(args) -> int:
    store = Store(args.db)
    n = store.mark(args.account_id.upper(), args.status, (args.as_of or date.today()).isoformat(), args.note)
    print(f"{args.account_id}: {n} open action(s) marked {args.status}" if n else f"{args.account_id}: no open action")
    return 0 if n else 1


def cmd_reset(args) -> int:
    for p in [Path(args.db), Path(str(args.db) + "-wal"), Path(str(args.db) + "-shm")]:
        p.unlink(missing_ok=True)
    shutil.rmtree(args.out, ignore_errors=True)
    print("State and outputs cleared.")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="autopilot", description="Fleek AM Autopilot")
    p.add_argument("--db", default=DEFAULT_DB, help="state database (default state/autopilot.db)")
    p.add_argument("--out", default=DEFAULT_OUT, help="output folder (default out/)")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="process one export")
    r.add_argument("--input", "-i", required=True)
    r.add_argument("--sheet", "-s", default=None, help="xlsx sheet (default: first non-Readme sheet)")
    r.add_argument("--as-of", type=_date, default=None, help="run date, YYYY-MM-DD (default today)")
    r.add_argument("--dispatch", action="store_true", help="let the agent send automated messages")
    r.add_argument("--force", action="store_true", help="re-apply a file that was already processed")
    r.add_argument("--llm", type=int, default=0, metavar="N", help="polish the top N human/review drafts with Claude")
    r.set_defaults(fn=cmd_run)

    ib = sub.add_parser("inbox", help="process every new file in data/inbox")
    ib.add_argument("--inbox", default=INBOX)
    ib.add_argument("--as-of", type=_date, default=None)
    ib.add_argument("--dispatch", action="store_true")
    ib.add_argument("--llm", type=int, default=0, metavar="N")
    ib.set_defaults(fn=cmd_inbox)

    sub.add_parser("status", help="runs, segments, actions").set_defaults(fn=cmd_status)

    qq = sub.add_parser("queue", help="today's queue")
    qq.add_argument("--owner", choices=["human", "review", "auto"])
    qq.add_argument("--bucket", choices=["today", "next", "approval", "outbox"])
    qq.add_argument("--limit", type=int, default=15)
    qq.add_argument("--as-of", type=_date, default=None)
    qq.set_defaults(fn=cmd_queue)

    sh = sub.add_parser("show", help="one account in full")
    sh.add_argument("account_id")
    sh.set_defaults(fn=cmd_show)

    mk = sub.add_parser("mark", help="log an outcome for an account's open action")
    mk.add_argument("account_id")
    mk.add_argument("status", choices=["sent", "done", "snoozed", "dismissed"])
    mk.add_argument("--note", default=None)
    mk.add_argument("--as-of", type=_date, default=None)
    mk.set_defaults(fn=cmd_mark)

    sub.add_parser("reset", help="clear state and outputs").set_defaults(fn=cmd_reset)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
