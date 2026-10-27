import re

from autopilot.clean import clean
from autopilot.pipeline import score

from .conftest import XLSX, make_raw

BROKER = {"broker_reliance_pct": 70, "manual_orders": 7, "self_serve_orders": 3, "orders_6m": 10,
          "app_active_days_6m": 2, "pdp_views_6m": 5, "make_an_offer_6m": 0}
KEY_SPEND = {f"gmv_{m}": 3000 for m in ["sep", "oct", "nov", "dec", "jan", "feb"]} | {"gmv_total_6m": 18000}
LAPSED = {"gmv_dec": 0, "gmv_jan": 0, "gmv_feb": 0}


def scored(rules, plays, *rows):
    df, _ = clean(make_raw(*rows), rules)
    return score(df, rules, plays).set_index("account_id")


def test_segments_come_from_behaviour_not_label(rules, plays):
    d = scored(rules, plays,
               {"account_id": "BR", **BROKER},
               {"account_id": "HY", **BROKER, "pdp_views_6m": 400, "app_active_days_6m": 30},
               {"account_id": "SS_AM", "broker_reliance_pct": 10, "app_active_days_6m": 20, "pdp_views_6m": 200},
               {"account_id": "LT_AM", "broker_reliance_pct": 10, "app_active_days_6m": 0, "pdp_views_6m": 0,
                "self_serve_orders": 1, "orders_6m": 1},
               {"account_id": "SS", "ownership": "Self Serve"})
    assert d.loc["BR", "segment"] == "broker_reliant"
    assert d.loc["HY", "segment"] == "broker_hybrid"
    assert d.loc["SS_AM", "segment"] == "am_self_serving"
    assert d.loc["SS_AM", "label_mismatch"] == "AM label, buys for themselves"
    assert d.loc["LT_AM", "segment"] == "am_light_touch"
    assert d.loc["SS", "segment"] == "self_serve"


def test_next_best_actions(rules, plays):
    d = scored(rules, plays,
               {"account_id": "DUP", "account_status": "Duplicate", **BROKER, **KEY_SPEND},
               {"account_id": "RESCUE", **BROKER, **KEY_SPEND, **LAPSED, "gmv_total_6m": 9000},
               {"account_id": "PARTIAL", **BROKER, **KEY_SPEND},
               {"account_id": "TAIL", **BROKER},                                      # £600 in 6m: long tail
               {"account_id": "MID", **BROKER, **{f"gmv_{m}": 500 for m in ["sep", "oct", "nov", "dec", "jan", "feb"]},
                "gmv_total_6m": 3000},
               {"account_id": "BUNDLES", "ownership": "Self Serve", "handpick_orders": 4, "bundle_orders": 0,
                "bundle_gmv_share_pct": 0},
               {"account_id": "WELCOME", "ownership": "Self Serve", "tenure_months": 1, "orders_6m": 1,
                "self_serve_orders": 1, "gmv_sep": 0, "gmv_oct": 0, "gmv_nov": 0, "gmv_dec": 0, "gmv_jan": 0,
                "gmv_feb": 200, "gmv_total_6m": 200},
               {"account_id": "CHAT", "ownership": "Self Serve", "pdp_views_6m": 1200, "make_an_offer_6m": 8,
                "orders_6m": 2, "self_serve_orders": 2, "chat_threads": 0})
    assert d.loc["DUP", "play"] == "fix_crm_duplicate"
    assert d.loc["RESCUE", "play"] == "rescue_key_account" and d.loc["RESCUE", "owner"] == "human"
    assert d.loc["PARTIAL", "play"] == "migrate_partial" and d.loc["PARTIAL", "owner"] == "human"
    assert d.loc["TAIL", "play"] == "migrate_auto" and d.loc["TAIL", "owner"] == "auto"
    assert d.loc["MID", "play"] == "migrate_guided" and d.loc["MID", "owner"] == "review"
    assert d.loc["BUNDLES", "play"] == "nudge_bundles"
    assert d.loc["WELCOME", "play"] == "welcome_second_order"
    assert d.loc["CHAT", "play"] == "nudge_chat"
    # retention outranks migration for the same account value
    assert d.loc["RESCUE", "priority"] > d.loc["MID", "priority"]


def test_scoring_is_deterministic_and_drafts_complete(rules, plays):
    from autopilot.ingest import read_portfolio
    df, _ = clean(read_portfolio(XLSX, "Accounts", rules), rules)
    a, b = score(df, rules, plays), score(df, rules, plays)
    cols = ["segment", "play", "owner", "priority", "draft_message", "call_note"]
    assert a[cols].equals(b[cols])
    placeholder = re.compile(r"\{\w+\}")
    for col in ["draft_subject", "draft_message", "call_note", "why"]:
        assert not a[col].str.contains(placeholder).any(), col
    # every account with an action has something to send or say
    acted = a[a["play"] != "keep_warm"]
    assert (acted["draft_message"].ne("") | acted["call_note"].ne("")).all()
