"""Segment the book by behaviour, not by the ownership label.

Segments
--------
broker_reliant   The AM does the buying (broker % high) and the customer barely
                 uses the product (low app days, PDP views and offers).
broker_hybrid    The AM still does most of the buying, but the customer already
                 browses the app. The easiest migrations.
am_self_serving  Has an AM, but buys for themselves. Healthy account-managed.
am_light_touch   Has an AM, low broker %, but little activity of any kind.
                 Does not need an AM's time.
self_serve       No AM and buys through the product.

The ownership label is kept alongside so mismatches are visible: an
account-managed customer who behaves like self-serve frees up AM time.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

SEGMENT_LABELS = {
    "broker_reliant": "Broker-reliant",
    "broker_hybrid": "Broker + browsing",
    "am_self_serving": "AM, self-serving",
    "am_light_touch": "AM, light-touch",
    "self_serve": "Self-serve",
}


def segment(df: pd.DataFrame, rules: dict) -> pd.DataFrame:
    df = df.copy()
    cfg = rules["segmentation"]
    broker = df["broker_reliance_pct"] >= cfg["broker_reliant_min_pct"]
    am = df["ownership"].eq("Account Managed")
    signals = df["self_serving_signals"]

    df["segment"] = np.select(
        [broker & df["low_digital"], broker, am & (signals >= 1), am],
        ["broker_reliant", "broker_hybrid", "am_self_serving", "am_light_touch"],
        default="self_serve",
    )
    df["segment_label"] = df["segment"].map(SEGMENT_LABELS)
    df["label_mismatch"] = np.select(
        [am & df["segment"].isin(["am_self_serving", "am_light_touch"]),
         ~am & broker],
        ["AM label, buys for themselves", "Self-serve label, but an AM places orders"],
        default="",
    )

    pct = df["broker_reliance_pct"].astype(int).astype(str)
    app = df["app_active_days_6m"].astype(str)
    pdp = df["pdp_views_6m"].astype(str)
    offers = df["make_an_offer_6m"].astype(str)
    activity = app + " app days, " + pdp + " product views, " + offers + " offers"
    df["segment_reason"] = np.select(
        [df["segment"].eq("broker_reliant"), df["segment"].eq("broker_hybrid"),
         df["segment"].eq("am_self_serving"), df["segment"].eq("am_light_touch")],
        [pct + "% of orders placed by the AM; barely uses the product (" + activity + ")",
         pct + "% of orders placed by the AM, but already browsing (" + activity + ")",
         "Has an AM but places " + (100 - df["broker_reliance_pct"]).astype(int).astype(str)
         + "% of orders themselves (" + activity + ")",
         "Has an AM but little activity either way (" + activity + ")"],
        default="Buys through the product (" + activity + ")",
    )
    return df
