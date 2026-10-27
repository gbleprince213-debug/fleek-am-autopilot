"""Build a large synthetic book (default 30,000 accounts) to prove the tool scales.

Rows are resampled from the real portfolio with noise, then made deliberately
messy (casing, '£1,234' strings, 'n/a', blank statuses, duplicate and blank
ids) so the cleaner is exercised at volume too. Also writes a follow-up batch
of new + updated accounts to test the incremental run.

    python scripts/make_synthetic.py --rows 30000
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "raw" / "fleek_portfolio.xlsx"
MONTHS = ["gmv_sep", "gmv_oct", "gmv_nov", "gmv_dec", "gmv_jan", "gmv_feb"]
COUNTS = ["manual_orders", "self_serve_orders", "app_active_days_6m", "pdp_views_6m", "make_an_offer_6m",
          "chat_threads", "video_call_requests", "handpick_orders", "bundle_orders"]


def synth(n: int, seed: int, id_prefix: str, start: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    base = pd.read_excel(SRC, sheet_name="Accounts")
    df = base.sample(n=n, replace=True, random_state=seed).reset_index(drop=True)
    df["account_id"] = [f"{id_prefix}-{i:06d}" for i in range(start, start + n)]
    scale = rng.lognormal(0, 0.35, size=n)
    for m in MONTHS:
        df[m] = (df[m] * scale * rng.lognormal(0, 0.15, size=n)).round().astype(int)
    for c in COUNTS:
        df[c] = (df[c] * rng.lognormal(0, 0.25, size=n)).round().astype(int)
    df["orders_6m"] = df["manual_orders"] + df["self_serve_orders"]
    df["gmv_total_6m"] = df[MONTHS].sum(axis=1) + rng.integers(-2, 3, size=n)  # rounding gaps like the source
    tot = df["orders_6m"].replace(0, np.nan)
    df["broker_reliance_pct"] = (df["manual_orders"] / tot * 100).round().fillna(0).astype(int)
    df["gmv_trend_pct"] = ((df["gmv_feb"] - df["gmv_sep"]) / df["gmv_sep"].replace(0, np.nan) * 100).round()
    return df


def mess(df: pd.DataFrame, seed: int, rate: float = 0.02) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    df = df.astype(object).copy()
    pick = lambda r=rate: rng.random(len(df)) < r  # noqa: E731
    df.loc[pick(), "ownership"] = df["ownership"].str.lower()
    df.loc[pick(), "ownership"] = df["ownership"].replace({"Self Serve": "self-serve", "Account Managed": "AM"})
    df.loc[pick(), "country"] = df["country"].replace({"United Kingdom": "UK", "United States": "USA"})
    df.loc[pick(), "buyer_persona"] = df["buyer_persona"].astype(str) + " "
    m = pick()
    df.loc[m, "gmv_total_6m"] = df.loc[m, "gmv_total_6m"].map(lambda v: f"£{int(v):,}")
    df.loc[pick(0.01), "app_active_days_6m"] = "n/a"
    df.loc[pick(), "account_status"] = None
    df.loc[pick(0.005), "region"] = "EU"  # wrong region for some UK/US rows
    dupes = df.sample(frac=0.005, random_state=seed)
    df = pd.concat([df, dupes], ignore_index=True)  # duplicate account rows
    df.loc[rng.choice(len(df), size=max(1, len(df) // 1000), replace=False), "account_id"] = None
    return df


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--rows", type=int, default=30000)
    p.add_argument("--update-rows", type=int, default=1000)
    p.add_argument("--out", default=str(ROOT / "data" / "synthetic"))
    a = p.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    book = synth(a.rows, seed=7, id_prefix="SYN")
    mess(book, seed=7).to_csv(out / f"book_{a.rows}.csv", index=False)

    n_upd = a.update_rows // 10
    new = synth(a.update_rows - n_upd, seed=8, id_prefix="SYN", start=a.rows + 1)
    upd = book.sample(n=n_upd, random_state=9).copy()
    upd["gmv_feb"] = (upd["gmv_feb"] * 1.5 + 500).round().astype(int)
    upd["gmv_total_6m"] = upd[MONTHS].sum(axis=1)
    mess(pd.concat([new, upd], ignore_index=True), seed=8).to_csv(out / f"batch_{a.update_rows}.csv", index=False)
    print(f"Wrote {out}/book_{a.rows}.csv and {out}/batch_{a.update_rows}.csv "
          f"({a.update_rows - n_upd} new, {n_upd} updated)")


if __name__ == "__main__":
    main()
