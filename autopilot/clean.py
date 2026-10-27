"""Clean a raw portfolio batch and log every fix.

Everything is vectorised (no per-row Python loops) so a 30k-row book cleans in
well under a second. Each rule appends to a data-quality log that is written
out with every run, so a person can see exactly what was changed and why.
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

_NULL_TOKENS = {"", "na", "n/a", "nan", "none", "null", "-", "--", "?", "#n/a"}


class IssueLog:
    """Collects data-quality findings as rows of a DataFrame."""

    def __init__(self) -> None:
        self._frames: list[pd.DataFrame] = []

    def add(self, df: pd.DataFrame, mask: pd.Series, field: str, issue: str, action: str,
            original: pd.Series | None = None, fixed: pd.Series | None = None,
            severity: str = "info") -> None:
        mask = mask.fillna(False).astype(bool)
        if not mask.any():
            return
        frame = pd.DataFrame({
            "account_id": df.loc[mask, "account_id"].astype(str).values,
            "field": field,
            "issue": issue,
            "action": action,
            "severity": severity,
            "original": (original[mask].astype(str).values if original is not None else ""),
            "fixed": (fixed[mask].astype(str).values if fixed is not None else ""),
        })
        self._frames.append(frame)

    def frame(self) -> pd.DataFrame:
        cols = ["account_id", "field", "issue", "action", "severity", "original", "fixed"]
        if not self._frames:
            return pd.DataFrame(columns=cols)
        return pd.concat(self._frames, ignore_index=True)[cols]


def _clean_text(s: pd.Series) -> pd.Series:
    out = s.astype("string").str.strip().str.replace(r"\s+", " ", regex=True)
    return out.mask(out.str.lower().isin(_NULL_TOKENS))


def _to_number(s: pd.Series) -> pd.Series:
    if pd.api.types.is_numeric_dtype(s):
        return pd.to_numeric(s, errors="coerce").astype(float)
    text = s.astype("string").str.strip()
    text = text.mask(text.str.lower().isin(_NULL_TOKENS))
    text = text.str.replace(r"[£$€,%\s]", "", regex=True)
    text = text.str.replace(r"^\((.*)\)$", r"-\1", regex=True)  # (123) accounting negatives
    return pd.to_numeric(text, errors="coerce").astype(float)


def _map_values(s: pd.Series, mapping: dict[str, str]) -> pd.Series:
    lookup = {k.lower(): v for k, v in mapping.items()}
    canon = {v.lower(): v for v in mapping.values()}
    lower = s.str.lower()
    mapped = lower.map(lookup)
    mapped = mapped.fillna(lower.map(canon))
    # Unknown values are title-cased rather than dropped
    return mapped.fillna(s.str.title()).where(s.notna())


def clean(raw: pd.DataFrame, rules: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    cfg = rules["data"]
    tol = rules["cleaning"]
    months = cfg["months"]
    log = IssueLog()
    df = raw.copy()

    # ---- account ids -------------------------------------------------------
    df["account_id"] = _clean_text(df["account_id"]).str.upper()
    no_id = df["account_id"].isna()
    if no_id.any():
        log.add(df.assign(account_id="(blank)"), no_id, "account_id", "row has no account id",
                "dropped row", severity="warn")
        df = df[~no_id].copy()

    dup = df.duplicated("account_id", keep="last")
    if dup.any():
        log.add(df, dup, "account_id", "account appears more than once in the batch",
                "kept the last row (treated as most recent)", severity="warn")
        df = df[~dup].copy()

    # ---- text fields -------------------------------------------------------
    for col in cfg["text"]:
        if col == "account_id":
            continue
        before = df[col].astype("string")
        cleaned = _clean_text(df[col])
        if col in cfg["value_maps"]:
            cleaned = _map_values(cleaned, cfg["value_maps"][col])
        changed = before.notna() & cleaned.notna() & (before != cleaned)
        log.add(df, changed, col, "inconsistent spelling or spacing", "standardised",
                before, cleaned)
        df[col] = cleaned

    # ---- numbers -----------------------------------------------------------
    for col in cfg["numeric"]:
        original = df[col]
        num = _to_number(original)
        bad = original.notna() & num.isna() & ~original.astype("string").str.strip().str.lower().isin(_NULL_TOKENS)
        log.add(df, bad, col, "value is not a number", "treated as blank", original, num, "warn")
        neg = num < 0
        if col != "gmv_trend_pct":
            log.add(df, neg, col, "negative value", "set to 0", num, num.clip(lower=0), "warn")
            num = num.clip(lower=0)
        if col in cfg["percent"]:
            over = num > 100
            log.add(df, over, col, "percentage above 100", "capped at 100", num, num.clip(upper=100), "warn")
            num = num.clip(upper=100)
        df[col] = num

    # Activity counts: blank means nothing was recorded
    activity = ["manual_orders", "self_serve_orders", "app_active_days_6m", "pdp_views_6m",
                "make_an_offer_6m", "chat_threads", "video_call_requests", "handpick_orders",
                "bundle_orders"]
    for col in activity + months:
        blank = df[col].isna()
        log.add(df, blank, col, "blank activity value", "treated as 0")
        df[col] = df[col].fillna(0)

    # ---- orders reconcile --------------------------------------------------
    parts = df["manual_orders"] + df["self_serve_orders"]
    orders_blank = df["orders_6m"].isna()
    log.add(df, orders_blank, "orders_6m", "blank", "rebuilt from manual + self-serve orders",
            df["orders_6m"], parts)
    df["orders_6m"] = df["orders_6m"].fillna(parts)
    mismatch = (df["orders_6m"] != parts)
    log.add(df, mismatch, "orders_6m", "does not equal manual + self-serve orders",
            "kept the larger figure", df["orders_6m"], np.maximum(df["orders_6m"], parts), "warn")
    df["orders_6m"] = np.maximum(df["orders_6m"], parts)

    # ---- GMV reconcile -----------------------------------------------------
    month_sum = df[months].sum(axis=1)
    total = df["gmv_total_6m"]
    has_split = month_sum > 0
    gap = (total - month_sum).abs()
    rounding = has_split & total.notna() & (gap > 0) & (gap <= tol["gmv_total_tolerance_gbp"])
    log.add(df, rounding, "gmv_total_6m", "total differs from the monthly figures by a rounding amount",
            "set to the sum of months", total, month_sum)
    material = has_split & total.notna() & (gap > tol["gmv_total_tolerance_gbp"])
    log.add(df, material, "gmv_total_6m", "total does not match the monthly figures",
            "set to the sum of months (monthly data is the granular source)", total, month_sum, "warn")
    no_split = ~has_split & (total.fillna(0) > 0)
    log.add(df, no_split, "gmv_sep..gmv_feb", "monthly split missing", "kept the 6-month total; trend unknown",
            severity="warn")
    df["gmv_total_6m"] = np.where(has_split, month_sum, total.fillna(0))
    df["monthly_split_missing"] = no_split

    # ---- broker reliance ---------------------------------------------------
    counts_pct = (df["manual_orders"] / parts.replace(0, np.nan) * 100).round()
    pct_blank = df["broker_reliance_pct"].isna()
    log.add(df, pct_blank, "broker_reliance_pct", "blank", "rebuilt from order counts",
            df["broker_reliance_pct"], counts_pct.fillna(0))
    df["broker_reliance_pct"] = df["broker_reliance_pct"].fillna(counts_pct).fillna(0)
    df["broker_pct_from_counts"] = counts_pct
    disagree = (df["broker_reliance_pct"] - counts_pct).abs() > tol["broker_pct_mismatch_flag_pts"]
    log.add(df, disagree, "broker_reliance_pct", "reported % disagrees with the order counts",
            "kept the reported %; flagged for review", df["broker_reliance_pct"], counts_pct)

    # ---- trend -------------------------------------------------------------
    trend_blank = df["gmv_trend_pct"].isna() & (df["gmv_sep"] == 0) & has_split
    log.add(df, trend_blank, "gmv_trend_pct", "blank because there was no September spend (divide by zero)",
            "replaced by a momentum measure over months on book")

    # ---- status ------------------------------------------------------------
    status_blank = df["account_status"].isna()
    log.add(df, status_blank, "account_status", "blank", "set to 'Unset' (activity decides if live)")
    df["account_status"] = df["account_status"].fillna("Unset")
    df["is_duplicate_record"] = df["account_status"].eq("Duplicate")
    log.add(df, df["is_duplicate_record"], "account_status", "CRM marks this record as a duplicate",
            "kept the spend, held back from outreach, CRM merge task raised", severity="warn")

    # ---- ownership ---------------------------------------------------------
    own_blank = df["ownership"].isna()
    inferred = pd.Series(np.where(df["broker_reliance_pct"] > 0, "Account Managed", "Self Serve"), index=df.index)
    log.add(df, own_blank, "ownership", "blank", "inferred from broker reliance", df["ownership"], inferred, "warn")
    df["ownership"] = df["ownership"].fillna(inferred)
    odd_own = ~df["ownership"].isin(["Account Managed", "Self Serve"])
    log.add(df, odd_own, "ownership", "unrecognised value", "inferred from broker reliance",
            df["ownership"], inferred, "warn")
    df.loc[odd_own, "ownership"] = inferred[odd_own]
    ss_broker = df["ownership"].eq("Self Serve") & (df["manual_orders"] > 0)
    log.add(df, ss_broker, "ownership", "labelled self-serve but an AM placed orders",
            "kept label; segmentation uses behaviour", severity="warn")

    persona_ok = set(cfg["value_maps"]["buyer_persona"].values())
    odd_persona = df["buyer_persona"].notna() & ~df["buyer_persona"].isin(persona_ok)
    log.add(df, odd_persona, "buyer_persona", "unrecognised value", "set to 'Unknown'",
            df["buyer_persona"], pd.Series("Unknown", index=df.index), "warn")
    df["buyer_persona"] = df["buyer_persona"].where(~odd_persona).fillna("Unknown")

    # ---- region ------------------------------------------------------------
    c2r = cfg["country_to_region"]
    europe = set(cfg["europe_countries"])
    country = df["country"]
    explicit = country.map({k: v for k, v in c2r.items() if not k.startswith("_")})
    fallback = pd.Series(np.where(country.isin(europe), c2r["_default_europe"], c2r["_default"]), index=df.index)
    expected = explicit.fillna(fallback).where(country.notna())
    region = df["region"]
    region_blank = region.isna() & expected.notna()
    log.add(df, region_blank, "region", "blank", "derived from country", region, expected)
    clash = region.notna() & expected.notna() & (region != expected)
    log.add(df, clash, "region", "does not match the shipping country", "derived from country",
            region, expected, "warn")
    df["region"] = expected.fillna(region).fillna("Unknown")
    df["country"] = country.fillna("Unknown")

    # ---- tenure ------------------------------------------------------------
    spend_flags = df[months].gt(0).to_numpy()
    first_idx = np.where(spend_flags.any(axis=1), spend_flags.argmax(axis=1), len(months) - 1)
    min_tenure = len(months) - first_idx  # months since first spend inside the window
    ten_blank = df["tenure_months"].isna()
    log.add(df, ten_blank, "tenure_months", "blank", "inferred from first month with spend",
            df["tenure_months"], pd.Series(min_tenure, index=df.index), "warn")
    df["tenure_months"] = df["tenure_months"].fillna(pd.Series(min_tenure, index=df.index))
    short = df["tenure_months"] < pd.Series(min_tenure, index=df.index)
    log.add(df, short, "tenure_months", "shorter than the months with recorded spend",
            "raised to match the spend history", df["tenure_months"], pd.Series(min_tenure, index=df.index), "warn")
    df["tenure_months"] = np.maximum(df["tenure_months"], min_tenure)

    # ---- tracking gaps (flag only) ----------------------------------------
    gap_app = (df["self_serve_orders"] > 0) & (df["app_active_days_6m"] == 0) & (df["pdp_views_6m"] == 0)
    log.add(df, gap_app, "app_active_days_6m", "self-serve orders but no app activity recorded",
            "flagged: likely web orders or a tracking gap")
    gap_offer = (df["make_an_offer_6m"] > 0) & (df["pdp_views_6m"] == 0)
    log.add(df, gap_offer, "pdp_views_6m", "offers made but no product views recorded",
            "flagged: likely a tracking gap")
    df["tracking_gap"] = gap_app | gap_offer
    mix_unknown = (df["orders_6m"] > 0) & (df["handpick_orders"] + df["bundle_orders"] == 0)
    log.add(df, mix_unknown, "handpick_orders/bundle_orders", "orders with no product mix recorded",
            "flagged: product nudges skipped")
    df["product_mix_unknown"] = mix_unknown
    df["bundle_gmv_share_pct"] = df["bundle_gmv_share_pct"].fillna(
        (df["bundle_orders"] / (df["handpick_orders"] + df["bundle_orders"]).replace(0, np.nan) * 100).round()
    ).fillna(0)

    int_cols = [c for c in cfg["numeric"] if c not in ("gmv_trend_pct",)]
    df[int_cols] = df[int_cols].round().astype("int64")
    return df.reset_index(drop=True), log.frame()
