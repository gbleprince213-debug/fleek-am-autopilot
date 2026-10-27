"""Derived behaviour metrics.

The raw file judges every account over Sep-Feb, but a customer who joined in
December has three months of zeros that are not churn. Everything here is
measured over *months on book* = min(tenure, 6) so new and old accounts are
compared fairly. All maths is vectorised with numpy.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def add_features(df: pd.DataFrame, rules: dict) -> pd.DataFrame:
    df = df.copy()
    months = rules["data"]["months"]
    w = len(months)
    rec = rules["recency"]
    val = rules["value"]
    seg = rules["segmentation"]

    m = df[months].to_numpy(dtype=float)                    # n x 6, oldest -> newest
    mob = np.clip(df["tenure_months"].to_numpy(), 1, w).astype(int)
    col = np.arange(w)[None, :]
    on_book = col >= (w - mob)[:, None]                    # months the account existed for
    df["months_on_book"] = mob

    spend = np.where(on_book, m, 0.0)
    gmv = spend.sum(axis=1)
    df["gmv_runrate"] = (gmv / mob).round(0)
    df["months_with_spend"] = (spend > 0).sum(axis=1)
    df["spend_consistency"] = (df["months_with_spend"] / mob).round(2)

    # Months since last spend (0 = bought in the latest month)
    any_spend = (spend > 0).any(axis=1)
    last_idx = np.where(any_spend, w - 1 - np.argmax((spend > 0)[:, ::-1], axis=1), -1)
    df["months_since_last_spend"] = np.where(any_spend, (w - 1) - last_idx, mob)
    df.loc[df.get("monthly_split_missing", False) == True, "months_since_last_spend"] = np.nan  # noqa: E712

    # Momentum: recent half of months on book vs the earlier half, bounded -100..100.
    # Symmetric so a zero month does not explode the % like the raw Sep->Feb trend does.
    recent_n = np.ceil(mob / 2).astype(int)
    recent_mask = col >= (w - recent_n)[:, None]
    early_mask = on_book & ~recent_mask
    early_n = np.maximum(mob - recent_n, 1)
    recent_avg = np.where(recent_mask, m, 0).sum(axis=1) / recent_n
    early_avg = np.where(early_mask, m, 0).sum(axis=1) / early_n
    denom = recent_avg + early_avg
    momentum = np.where((mob >= 2) & (denom > 0), (recent_avg - early_avg) / np.where(denom > 0, denom, 1) * 100, np.nan)
    df["momentum"] = np.round(momentum, 0)
    df["momentum_label"] = np.select(
        [np.isnan(momentum), momentum >= 25, momentum <= -25],
        ["too new", "growing", "declining"], default="steady")

    since = df["months_since_last_spend"]
    df["recency_state"] = np.select(
        [df["tenure_months"] <= rec["new_account_max_tenure"],
         since >= rec["lapsed_months_without_spend"],
         since >= rec["cooling_months_without_spend"]],
        ["new", "lapsed", "cooling"], default="active")

    # Value
    rr = df["gmv_runrate"].clip(lower=0)
    df["value_tier"] = np.select(
        [rr >= val["key_account_runrate"], rr >= val["mid_account_runrate"]], ["key", "mid"], default="long_tail")
    df["value_score"] = (np.log10(rr + 1) / np.log10(val["runrate_cap_for_score"] + 1) * 100).clip(0, 100).round(0)
    df["avg_order_value"] = (df["gmv_total_6m"] / df["orders_6m"].replace(0, np.nan)).round(0).fillna(0)

    # Digital engagement (absolute scale so a re-run never re-scores old rows)
    app, pdp, offers = df["app_active_days_6m"], df["pdp_views_6m"], df["make_an_offer_6m"]
    df["engagement_score"] = (
        np.minimum(app / 30, 1) * 40 + np.minimum(pdp / 300, 1) * 40 + np.minimum(offers / 10, 1) * 20
    ).round(0)
    low = seg["low_digital"]
    df["low_digital"] = (app <= low["app_active_days_max"]) & (pdp <= low["pdp_views_max"]) & (offers <= low["offers_max"])
    ss = seg["self_serving"]
    df["self_serving_signals"] = (
        (app >= ss["app_active_days_min"]).astype(int)
        + (pdp >= ss["pdp_views_min"]).astype(int)
        + (df["self_serve_orders"] >= ss["self_serve_orders_min"]).astype(int)
    )
    df["views_per_order"] = (pdp / df["orders_6m"].clip(lower=1)).round(0)

    # Product mix
    known_mix = ~df.get("product_mix_unknown", pd.Series(False, index=df.index))
    df["handpick_only"] = known_mix & (df["handpick_orders"] > 0) & (df["bundle_gmv_share_pct"] == 0)
    df["bundle_heavy"] = known_mix & (df["bundle_gmv_share_pct"] >= rules["plays"]["growth"]["bundle_heavy_share_pct"])

    # Health from Fleek's point of view: valuable, cheap to serve, consistent, growing, engaged
    momentum_component = np.nan_to_num((momentum + 100) / 2, nan=50.0)
    df["health_score"] = (
        df["value_score"] * 0.35
        + (100 - df["broker_reliance_pct"]) * 0.25
        + df["spend_consistency"] * 100 * 0.20
        + momentum_component * 0.10
        + df["engagement_score"] * 0.10
    ).round(0)
    lapsed_penalty = np.select([df["recency_state"] == "lapsed", df["recency_state"] == "cooling"], [25, 10], 0)
    df["health_score"] = (df["health_score"] - lapsed_penalty).clip(0, 100)

    # Migration readiness for broker-reliant customers: how likely they are to
    # cope buying for themselves (some app use, offers, standard product, remote-comfortable)
    df["migration_readiness"] = (
        np.minimum(app / 10, 1) * 30
        + np.minimum(pdp / 50, 1) * 20
        + np.minimum(offers / 2, 1) * 15
        + (df["bundle_gmv_share_pct"] / 100) * 15
        + (df["buyer_persona"] == "Reseller").astype(int) * 10
        + np.minimum(df["video_call_requests"] / 3, 1) * 10
    ).round(0)
    return df
