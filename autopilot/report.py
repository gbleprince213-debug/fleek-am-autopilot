"""Write the run outputs a person or an agent consumes.

out/
  queue_today.csv      AM's call list for today (capped at daily capacity)
  review_queue.csv     drafts waiting for AM approval
  outbox.jsonl         automated messages for a sender agent / CRM to deliver
  accounts.csv         the whole book, cleaned and scored
  data_quality.csv     every fix the cleaner made this run
  run_summary.md       what happened this run, in plain English
  dashboard.html       everything above, clickable, one self-contained file
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from .pipeline import RunResult
from .segment import SEGMENT_LABELS
from .state import Store

QUEUE_COLS = ["bucket", "priority", "account_id", "segment_label", "title", "owner", "channel",
              "gmv_total_6m", "why", "subject", "message", "call_note", "due_date", "created_at", "overdue"]


def book(store: Store) -> pd.DataFrame:
    return store.account_rows()


def build_queue(store: Store, as_of: date, rules: dict) -> pd.DataFrame:
    acts = store.open_actions()
    if acts.empty:
        return pd.DataFrame(columns=QUEUE_COLS)
    accs = store.account_rows(acts["account_id"].tolist())[["account_id", "segment_label", "gmv_total_6m"]]
    q = acts.merge(accs, on="account_id", how="left")
    today = as_of.isoformat()
    q = q[q["due_date"] <= today].copy()
    q = q.sort_values(["priority", "gmv_total_6m"], ascending=[False, False])
    cap = rules["routing"]["daily_human_capacity"]
    human = q["owner"].eq("human")
    human_rank = human.cumsum().where(human)
    q["bucket"] = "outbox"
    q.loc[q["owner"].eq("review"), "bucket"] = "approval"
    q.loc[human & (human_rank <= cap), "bucket"] = "today"
    q.loc[human & (human_rank > cap), "bucket"] = "next"
    follow = (as_of - timedelta(days=rules["routing"]["follow_up_days"])).isoformat()
    q["overdue"] = human & (q["created_at"] < follow)
    return q[QUEUE_COLS].reset_index(drop=True)


def dispatch_auto(store: Store, queue: pd.DataFrame, as_of: date, out_dir: Path) -> int:
    """Stand-in for the sender agent: write automated messages to the outbox and
    mark them sent, so cooldowns apply and they are never sent twice."""
    out = queue[queue["bucket"].eq("outbox")]
    path = out_dir / "outbox.jsonl"
    with open(path, "a", encoding="utf-8") as fh:
        for r in out.itertuples(index=False):
            fh.write(json.dumps({"date": as_of.isoformat(), "account_id": r.account_id, "channel": r.channel,
                                 "subject": r.subject, "message": r.message, "play": r.title}) + "\n")
    with store.tx():
        for aid in out["account_id"]:
            store.conn.execute(
                "UPDATE actions SET status = 'sent', contacted_at = ?, updated_at = ?, note = 'sent by agent' "
                "WHERE account_id = ? AND status = 'open' AND owner = 'auto'", [as_of.isoformat()] * 2 + [aid])
    return len(out)


def summary_markdown(res: RunResult, store: Store, queue: pd.DataFrame, accounts: pd.DataFrame,
                     dispatched: int) -> str:
    lines = [f"# Run {res.run_id}: {res.source}", ""]
    if res.input_seen_before and not res.new and not res.updated:
        lines += ["This exact file was already processed. Nothing to do.", ""]
    lines += [
        f"- Rows in batch: **{res.rows_in}**",
        f"- New accounts: **{len(res.new)}**",
        f"- Updated accounts (data changed): **{len(res.updated)}**",
        f"- Skipped (already handled, no change): **{len(res.unchanged)}**",
        f"- Data-quality fixes logged: **{res.dq_issues}**",
        f"- Actions created / refreshed / superseded: **{res.actions_created} / {res.actions_refreshed} / "
        f"{res.actions_superseded}**",
        f"- Automated messages sent by the agent: **{dispatched}**",
        f"- Took {res.seconds}s",
        "",
    ]
    if res.changes:
        lines += ["## What changed", ""]
        lines += [f"- **{k}**: {v}" for k, v in res.changes.items()]
        lines.append("")
    if not accounts.empty:
        total = accounts["gmv_total_6m"].sum()
        seg = accounts.groupby("segment").agg(accounts=("account_id", "count"), gmv=("gmv_total_6m", "sum"))
        lines += ["## Book by behaviour", "", "| Segment | Accounts | 6m GMV | Share |", "|---|---:|---:|---:|"]
        for s, r in seg.sort_values("gmv", ascending=False).iterrows():
            lines.append(f"| {SEGMENT_LABELS.get(s, s)} | {r.accounts} | £{r.gmv:,.0f} | {r.gmv / total:.0%} |")
        lines.append("")
    today = queue[queue["bucket"].eq("today")]
    if not today.empty:
        lines += ["## Today's calls", "", "| # | Account | Action | Why |", "|---|---|---|---|"]
        for i, r in enumerate(today.itertuples(index=False), 1):
            lines.append(f"| {i} | {r.account_id} | {r.title} | {r.why} |")
        lines.append("")
    n_appr = int(queue["bucket"].eq("approval").sum())
    lines += [f"{n_appr} drafts are waiting for approval in `review_queue.csv`."]
    return "\n".join(lines) + "\n"


def write_outputs(store: Store, res: RunResult, as_of: date, out_dir: str | Path, rules: dict,
                  dispatch: bool = False) -> dict[str, Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    queue = build_queue(store, as_of, rules)
    dispatched = dispatch_auto(store, queue, as_of, out_dir) if dispatch else 0
    accounts = book(store)

    paths = {
        "queue_today": out_dir / "queue_today.csv",
        "review_queue": out_dir / "review_queue.csv",
        "accounts": out_dir / "accounts.csv",
        "data_quality": out_dir / "data_quality.csv",
        "run_summary": out_dir / "run_summary.md",
        "dashboard": out_dir / "dashboard.html",
    }
    queue[queue["bucket"].isin(["today", "next"])].to_csv(paths["queue_today"], index=False)
    queue[queue["bucket"].eq("approval")].to_csv(paths["review_queue"], index=False)
    if not accounts.empty:
        accounts.sort_values("priority", ascending=False).to_csv(paths["accounts"], index=False)
    store.dq(res.run_id).to_csv(paths["data_quality"], index=False)
    paths["run_summary"].write_text(summary_markdown(res, store, queue, accounts, dispatched), encoding="utf-8")

    from .dashboard import render_dashboard
    paths["dashboard"].write_text(render_dashboard(store, queue, accounts, res, as_of, rules, dispatched),
                                  encoding="utf-8")
    if dispatch:
        paths["outbox"] = out_dir / "outbox.jsonl"
    return paths
