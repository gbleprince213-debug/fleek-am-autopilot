"""Pick one next-best action per account, decide who runs it, and score priority.

The decision list is evaluated top to bottom and the first match wins, so the
order encodes the commercial logic:

  1. Fix data that would make outreach wrong (CRM duplicate).
  2. Protect revenue: valuable broker-reliant accounts that stopped buying get
     a human win-back call before anyone mentions self-serve.
  3. Migrate broker-reliant accounts, with more human help the more they spend.
  4. Grow everyone who already self-serves, with the one feature most likely to
     lift their spend.
  5. Leave healthy accounts alone.

Everything is a pure function of the account's own row plus config, so an
unchanged account always gets the same answer on a re-run.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def choose_actions(df: pd.DataFrame, rules: dict, plays: dict) -> pd.DataFrame:
    df = df.copy()
    g = rules["plays"]["growth"]
    seg = df["segment"]
    broker = seg.isin(["broker_reliant", "broker_hybrid"])
    grow = ~broker
    tier = df["value_tier"]
    key, mid, tail = tier.eq("key"), tier.eq("mid"), tier.eq("long_tail")
    rec = df["recency_state"]
    lapsing = rec.isin(["lapsed", "cooling"])
    pdp, offers = df["pdp_views_6m"], df["make_an_offer_6m"]
    high_intent = (pdp >= g["high_intent_pdp_views"]) | (offers >= g["high_intent_offers"])

    rules_in_order = [
        ("fix_crm_duplicate", df["is_duplicate_record"]),
        ("rescue_key_account", broker & lapsing & (key | mid)),
        ("migrate_partial", broker & key & (df["migration_readiness"] < 40)),
        ("migrate_assisted", broker & key),
        ("migrate_guided", broker & mid),
        ("migrate_auto", broker),
        ("welcome_second_order", grow & rec.eq("new") & (df["orders_6m"] <= 1)),
        ("winback", grow & lapsing & (key | mid)),
        # Lapsed but still browsing hard falls through to the intent nudges below
        ("reactivate", grow & rec.eq("lapsed") & ~high_intent),
        ("nudge_video_call", grow & (df["gmv_runrate"] >= g["video_call_runrate"])
                              & (df["video_call_requests"] == 0)),
        ("nudge_chat", grow & high_intent & (df["views_per_order"] >= g["views_per_order_friction"])
                        & (df["chat_threads"] < g["low_chat_threads"])),
        ("nudge_bundles", grow & df["handpick_only"]),
        ("nudge_build_a_bundle", grow & df["bundle_heavy"] & high_intent),
    ]
    df["play"] = np.select([c.fillna(False) for _, c in rules_in_order],
                           [p for p, _ in rules_in_order], default="keep_warm")

    # ---- owner -------------------------------------------------------------
    r = rules["routing"]
    default_owner = df["play"].map({k: v["owner"] for k, v in plays["plays"].items()})
    by_value = np.select([df["gmv_runrate"] >= r["human_min_runrate"], df["gmv_runrate"] >= r["review_min_runrate"]],
                         ["human", "review"], default="auto")
    df["owner"] = np.where(default_owner.eq("by_value"), by_value, default_owner)

    # ---- priority (0-100, absolute so it is stable across runs) -----------
    base = df["play"].map({k: v.get("base_priority", 0) for k, v in plays["plays"].items()}).astype(float)
    headroom = (df["engagement_score"] - df["value_score"]).clip(lower=0)  # intent ahead of spend
    urgency = np.select([rec.eq("cooling"), rec.eq("lapsed") & ~tail], [6, 10], 0)
    priority = (
        base
        + df["value_score"] * 0.45
        + np.where(broker, df["broker_reliance_pct"] * 0.08, headroom * 0.25)
        + urgency
    )
    df["priority"] = np.where(df["play"].eq("keep_warm"), 0, priority.clip(0, 100)).round(0).astype(int)
    df["headroom_score"] = headroom.round(0)

    # ---- coverage recommendation (who should own the relationship) ---------
    df["coverage"] = np.select(
        [broker & (key | mid), broker,
         seg.eq("am_self_serving") & (key | mid), seg.isin(["am_self_serving", "am_light_touch"]),
         seg.eq("self_serve") & key],
        ["AM-owned while migrating", "Pooled: automated migration",
         "Keep AM, light-touch check-ins", "Release from AM coverage (pooled self-serve)",
         "Assign a growth owner (high-value self-serve)"],
        default="Pooled self-serve (automated)",
    )
    return df
