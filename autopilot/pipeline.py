"""One run of the daily job: ingest -> clean -> detect changes -> score -> act.

Only accounts that are new, or whose cleaned data changed since the last time
the tool saw them, are re-scored. Unchanged accounts are skipped, and their open
actions are left exactly as they were. Each account has at most one open action;
if its situation changes, the old action is superseded rather than duplicated.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from .actions import choose_actions
from .clean import clean
from .drafts import render_drafts
from .features import add_features
from .ingest import read_portfolio
from .segment import segment
from .state import Store

# Columns stored per account for the dashboard and for diffing the next run
STORED = [
    "account_id", "ownership", "buyer_persona", "region", "country", "account_status", "tenure_months",
    "gmv_total_6m", "orders_6m", "gmv_sep", "gmv_oct", "gmv_nov", "gmv_dec", "gmv_jan", "gmv_feb",
    "gmv_trend_pct", "broker_reliance_pct", "manual_orders", "self_serve_orders", "app_active_days_6m",
    "pdp_views_6m", "make_an_offer_6m", "chat_threads", "video_call_requests", "handpick_orders",
    "bundle_orders", "bundle_gmv_share_pct", "is_duplicate_record", "tracking_gap", "product_mix_unknown",
    "months_on_book", "gmv_runrate", "months_with_spend", "spend_consistency", "months_since_last_spend",
    "momentum", "momentum_label", "recency_state", "value_tier", "value_score", "avg_order_value",
    "engagement_score", "health_score", "migration_readiness", "headroom_score", "segment", "segment_label",
    "segment_reason", "label_mismatch", "coverage", "play", "owner", "priority", "action_title", "why",
]

# Fields compared between runs to explain what changed
DIFF_FIELDS = {
    "gmv_total_6m": ("6m GMV", "£{:,.0f}"),
    "gmv_feb": ("Feb GMV", "£{:,.0f}"),
    "orders_6m": ("orders", "{:,.0f}"),
    "broker_reliance_pct": ("broker reliance", "{:.0f}%"),
    "pdp_views_6m": ("product views", "{:,.0f}"),
    "app_active_days_6m": ("app days", "{:,.0f}"),
    "make_an_offer_6m": ("offers", "{:,.0f}"),
    "bundle_orders": ("bundle orders", "{:,.0f}"),
    "segment_label": ("segment", "{}"),
    "action_title": ("action", "{}"),
}


@dataclass
class RunResult:
    run_id: int
    source: str
    rows_in: int
    new: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    changes: dict[str, str] = field(default_factory=dict)
    dq_issues: int = 0
    actions_created: int = 0
    actions_refreshed: int = 0
    actions_superseded: int = 0
    actions_skipped_recent: int = 0
    seconds: float = 0.0
    input_seen_before: bool = False


def hash_rows(df: pd.DataFrame, rules: dict) -> pd.Series:
    cols = [c for c in rules["data"]["text"] + rules["data"]["numeric"] if c in df.columns]
    return pd.util.hash_pandas_object(df[cols], index=False).astype(str)


def score(df: pd.DataFrame, rules: dict, plays: dict) -> pd.DataFrame:
    """Pure scoring: same rows + same config in, same answer out."""
    return render_drafts(choose_actions(segment(add_features(df, rules), rules), rules, plays), rules, plays)


def _describe_change(prev: dict, cur: dict) -> str:
    parts = []
    for col, (label, fmt) in DIFF_FIELDS.items():
        a, b = prev.get(col), cur.get(col)
        if a is None or b is None or a == b:
            continue
        try:
            parts.append(f"{label} {fmt.format(a)} -> {fmt.format(b)}")
        except (ValueError, TypeError):
            parts.append(f"{label} {a} -> {b}")
    return "; ".join(parts) or "minor field changes"


def run(input_path: str | Path, sheet: str | None, rules: dict, plays: dict, store: Store,
        as_of: date | None = None, llm_top: int = 0, force: bool = False) -> RunResult:
    t0 = time.perf_counter()
    as_of = as_of or date.today()
    now = datetime.now().isoformat(timespec="seconds")
    raw = read_portfolio(input_path, sheet, rules)
    source, fp = raw.attrs["source"], raw.attrs["fingerprint"]
    seen = store.input_seen(fp)
    seen_before = seen is not None
    if seen_before and not force:
        # Same file + sheet already ingested. Re-applying it could roll accounts
        # back to older data, so skip unless explicitly forced.
        return RunResult(run_id=int(seen["last_run_id"]), source=source, rows_in=len(raw),
                         unchanged=raw["account_id"].astype(str).tolist(), input_seen_before=True,
                         seconds=round(time.perf_counter() - t0, 3))

    with store.tx():
        run_id = store.start_run(now, as_of.isoformat(), source, fp)
        df, issues = clean(raw, rules)
        store.save_issues(run_id, issues)

        df["row_hash"] = hash_rows(df, rules)
        known = store.known_hashes()
        prev_hash = df["account_id"].map(known)
        is_new = prev_hash.isna()
        is_changed = ~is_new & (prev_hash != df["row_hash"])
        res = RunResult(run_id=run_id, source=source, rows_in=len(df), dq_issues=len(issues),
                        input_seen_before=seen_before,
                        new=df.loc[is_new, "account_id"].tolist(),
                        updated=df.loc[is_changed, "account_id"].tolist(),
                        unchanged=df.loc[~is_new & ~is_changed, "account_id"].tolist())

        work = df[is_new | is_changed].copy()
        store.touch_seen(run_id, res.unchanged)
        if not work.empty:
            work = score(work, rules, plays)
            if llm_top:
                from .llm import polish_top
                work = polish_top(work, llm_top)
            _persist(store, run_id, work, res, as_of, rules)

        res.seconds = round(time.perf_counter() - t0, 3)
        store.finish_run(run_id, rows_in=res.rows_in, new=len(res.new), updated=len(res.updated),
                         unchanged=len(res.unchanged), dq_issues=res.dq_issues,
                         actions_created=res.actions_created, actions_refreshed=res.actions_refreshed,
                         actions_superseded=res.actions_superseded, seconds=res.seconds)
    return res


def _persist(store: Store, run_id: int, work: pd.DataFrame, res: RunResult, as_of: date, rules: dict) -> None:
    today = as_of.isoformat()
    cooldown = timedelta(days=rules["routing"]["contact_cooldown_days"])
    repeat_window = timedelta(days=rules["routing"].get("same_play_repeat_days", 30))
    records = json.loads(work[STORED].to_json(orient="records"))
    changed_ids = set(res.updated)
    prev = {r["account_id"]: r for r in store.account_rows(changed_ids).to_dict("records")} if changed_ids else {}

    acc_rows, hist_rows = [], []
    progress_pts = rules["segmentation"].get("migration_progress_pts", 10)
    for i, (rec, row_hash) in enumerate(zip(records, work["row_hash"])):
        aid = rec["account_id"]
        change_type = "updated" if aid in changed_ids else "new"
        detail = _describe_change(prev.get(aid, {}), rec) if change_type == "updated" else "first seen"
        if change_type == "updated":
            before = prev.get(aid, {}).get("broker_reliance_pct")
            if before is not None and before - rec["broker_reliance_pct"] >= progress_pts:
                detail = "MIGRATION PROGRESS. " + detail
            res.changes[aid] = detail
            rec["why"] = f"{rec['why']} Since last run: {detail}."
            work.iat[i, work.columns.get_loc("why")] = rec["why"]
        acc_rows.append((aid, row_hash, rec["segment"], rec["play"], rec["owner"], rec["priority"],
                         rec["gmv_total_6m"], run_id, run_id, run_id, json.dumps(rec)))
        hist_rows.append((aid, run_id, change_type, row_hash, rec["segment"], rec["play"],
                          rec["broker_reliance_pct"], rec["gmv_total_6m"], detail))
    store.upsert_accounts(acc_rows)
    store.add_history(hist_rows)

    # ---- reconcile actions: never more than one open action per account ----
    latest = store.latest_actions(work["account_id"].tolist())
    inserts, updates = [], []
    cols = ["account_id", "play", "action_title", "owner", "channel", "priority", "why", "goal",
            "draft_subject", "draft_message", "call_note"]
    for r in work[cols].itertuples(index=False):
        last = latest.get(r.account_id)
        is_open = last is not None and last["status"] == "open"
        if r.play == "keep_warm":
            if is_open:
                updates.append({"action_id": last["action_id"], "status": "resolved", "updated_at": today,
                                "note": "No longer needed: account now healthy (keep warm)."})
                res.actions_superseded += 1
            continue
        payload = {"title": r.action_title, "owner": r.owner, "channel": r.channel, "priority": int(r.priority),
                   "why": r.why, "goal": r.goal, "subject": r.draft_subject, "message": r.draft_message,
                   "call_note": r.call_note, "updated_at": today, "run_id": run_id}
        if is_open and last["play"] == r.play:
            updates.append({"action_id": last["action_id"], **payload})
            res.actions_refreshed += 1
            continue
        if (not is_open and last is not None and last["play"] == r.play and last["status"] in ("sent", "done")
                and last["contacted_at"]
                and (as_of - date.fromisoformat(last["contacted_at"][:10])).days < repeat_window.days):
            res.actions_skipped_recent += 1  # same nudge already went out recently: wait for the outcome
            continue
        if is_open:
            updates.append({"action_id": last["action_id"], "status": "superseded", "updated_at": today,
                            "note": f"Replaced by '{r.action_title}' after new data."})
            res.actions_superseded += 1
        due = today
        if last is not None and last["contacted_at"]:
            due = max(today, (date.fromisoformat(last["contacted_at"][:10]) + cooldown).isoformat())
        inserts.append({"account_id": r.account_id, "play": r.play, "status": "open", "created_at": today,
                        "due_date": due, **payload})
        res.actions_created += 1
    store.update_actions(updates)
    store.insert_actions(inserts)
