"""Time the full daily job on a large synthetic book.

    python scripts/make_synthetic.py --rows 30000
    python scripts/bench.py --rows 30000
"""
from __future__ import annotations

import argparse
import sys
import tempfile
import time
import resource
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from autopilot.config import load_plays, load_rules  # noqa: E402
from autopilot.pipeline import run  # noqa: E402
from autopilot.report import write_outputs  # noqa: E402
from autopilot.state import Store  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--rows", type=int, default=30000)
    p.add_argument("--update-rows", type=int, default=1000)
    a = p.parse_args()
    syn = ROOT / "data" / "synthetic"
    book, batch = syn / f"book_{a.rows}.csv", syn / f"batch_{a.update_rows}.csv"
    if not book.exists():
        sys.exit(f"Missing {book}. Run: python scripts/make_synthetic.py --rows {a.rows}")

    rules, plays = load_rules(), load_plays()
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(Path(tmp) / "bench.db")
        rows = []
        for label, path, day in [("full book", book, date(2026, 3, 2)), ("daily batch", batch, date(2026, 3, 3)),
                                 ("same batch again", batch, date(2026, 3, 4))]:
            t = time.perf_counter()
            res = run(path, None, rules, plays, store, as_of=day, force=label == "same batch again")
            t_run = time.perf_counter() - t
            t = time.perf_counter()
            write_outputs(store, res, day, Path(tmp) / "out", rules, dispatch=True)
            t_out = time.perf_counter() - t
            rows.append((label, res.rows_in, len(res.new), len(res.updated), len(res.unchanged),
                         res.actions_created, round(t_run, 2), round(t_out, 2)))
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024  # KB -> MB on Linux
        dup = store.conn.execute("SELECT COUNT(*) FROM (SELECT account_id FROM actions WHERE status='open' "
                                 "GROUP BY account_id HAVING COUNT(*) > 1)").fetchone()[0]
        n_acc = store.conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
        dash = (Path(tmp) / "out" / "dashboard.html").stat().st_size / 1e6

    print(f"{'step':18} {'rows':>7} {'new':>7} {'updated':>8} {'skipped':>8} {'actions':>8} {'score s':>8} {'outputs s':>9}")
    for r in rows:
        print(f"{r[0]:18} {r[1]:>7} {r[2]:>7} {r[3]:>8} {r[4]:>8} {r[5]:>8} {r[6]:>8} {r[7]:>9}")
    print(f"\naccounts in state: {n_acc:,} | accounts with >1 open action: {dup} | "
          f"peak memory: {peak:.0f} MB | dashboard: {dash:.1f} MB")


if __name__ == "__main__":
    main()
