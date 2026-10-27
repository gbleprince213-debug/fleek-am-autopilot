"""The behaviour the brief cares most about: run it again and nothing duplicates."""
from datetime import date

import pandas as pd

from autopilot.pipeline import run
from autopilot.report import write_outputs

from .conftest import XLSX, make_raw


def _open_dupes(store) -> int:
    return store.conn.execute(
        "SELECT COUNT(*) FROM (SELECT account_id FROM actions WHERE status = 'open' "
        "GROUP BY account_id HAVING COUNT(*) > 1)").fetchone()[0]


def test_second_batch_updates_without_duplicating(rules, plays, store, tmp_path):
    r1 = run(XLSX, "Accounts", rules, plays, store, as_of=date(2026, 3, 2))
    assert (len(r1.new), len(r1.updated), len(r1.unchanged)) == (300, 0, 0)

    r2 = run(XLSX, "new_accounts", rules, plays, store, as_of=date(2026, 3, 3))
    assert len(r2.new) == 45
    assert sorted(r2.updated) == ["ACC-006", "ACC-008", "ACC-048", "ACC-211", "ACC-214"]
    assert "MIGRATION PROGRESS" in r2.changes["ACC-006"]
    assert store.conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 345
    assert _open_dupes(store) == 0

    # The same file again is recognised and skipped
    r3 = run(XLSX, "new_accounts", rules, plays, store, as_of=date(2026, 3, 4))
    assert r3.skipped_file and not r3.new and not r3.updated

    # Forced, every row is unchanged at account level: no new actions
    r4 = run(XLSX, "new_accounts", rules, plays, store, as_of=date(2026, 3, 4), force=True)
    assert not r4.skipped_file and r4.input_seen_before
    assert len(r4.unchanged) == 50 and r4.actions_created == 0
    assert _open_dupes(store) == 0

    paths = write_outputs(store, r2, date(2026, 3, 3), tmp_path / "out", rules, dispatch=True)
    assert "ACC-001" in paths["dashboard"].read_text()
    today = pd.read_csv(paths["queue_today"])
    assert (today["bucket"] == "today").sum() <= rules["routing"]["daily_human_capacity"]


def test_changed_account_supersedes_its_old_action(rules, plays, store):
    csv1 = make_raw({"account_id": "X1", "ownership": "Self Serve", "handpick_orders": 4, "bundle_orders": 0,
                     "bundle_gmv_share_pct": 0})
    csv2 = make_raw({"account_id": "X1", "ownership": "Self Serve", "handpick_orders": 4, "bundle_orders": 0,
                     "bundle_gmv_share_pct": 0, "gmv_jan": 0, "gmv_feb": 0, "gmv_dec": 0, "gmv_total_6m": 300})
    p1, p2 = store.path.parent / "b1.csv", store.path.parent / "b2.csv"
    csv1.to_csv(p1, index=False)
    csv2.to_csv(p2, index=False)
    run(p1, None, rules, plays, store, as_of=date(2026, 3, 2))
    run(p2, None, rules, plays, store, as_of=date(2026, 3, 3))
    acts = pd.read_sql_query("SELECT play, status FROM actions WHERE account_id = 'X1' ORDER BY action_id", store.conn)
    assert list(acts["status"]) == ["superseded", "open"]
    assert acts["play"].iloc[0] != acts["play"].iloc[1]


def test_outcome_logged_then_no_repeat_of_same_play(rules, plays, store):
    row = {"account_id": "Y1", "ownership": "Self Serve", "handpick_orders": 4, "bundle_orders": 0,
           "bundle_gmv_share_pct": 0}
    p1, p2 = store.path.parent / "c1.csv", store.path.parent / "c2.csv"
    make_raw(row).to_csv(p1, index=False)
    make_raw({**row, "pdp_views_6m": 60}).to_csv(p2, index=False)   # small change, same play
    run(p1, None, rules, plays, store, as_of=date(2026, 3, 2))
    assert store.mark("Y1", "sent", "2026-03-02") == 1
    res = run(p2, None, rules, plays, store, as_of=date(2026, 3, 5))
    assert res.actions_skipped_recent == 1 and res.actions_created == 0
