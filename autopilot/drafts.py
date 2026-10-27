"""Turn each chosen play into something a person or agent can act on.

Templates live in config/plays.yaml. Rendering is a plain loop over rows:
about 30k drafts a second, so it is not a bottleneck at book sizes we expect.
"""
from __future__ import annotations

import math
import re
from typing import Any

import pandas as pd

MONTH_NAMES = ["September", "October", "November", "December", "January", "February"]


class _SafeDict(dict):
    def __missing__(self, key: str) -> str:  # unknown placeholder -> leave it visible
        return "{" + key + "}"


_NEW_LINE_START = re.compile(r"^(-|\d+\.\s|[A-Z][A-Za-z0-9' ]{1,30}:)")
_ENDS_WITH_URL = re.compile(r"https?://\S+$")


def reflow(text: str) -> str:
    """Join hard-wrapped template lines into paragraphs, keeping lists,
    'Label:' lines, sign-offs and links on their own lines."""
    paragraphs = []
    for para in text.strip().split("\n\n"):
        lines: list[str] = []
        for raw in para.split("\n"):
            line = raw.strip()
            if not line:
                continue
            keep_break = (
                not lines
                or _NEW_LINE_START.match(line)
                or lines[-1].endswith(":")
                or (lines[-1].endswith(",") and len(lines[-1]) <= 25)  # "Hi there," / "Speak soon,"
                or _ENDS_WITH_URL.search(lines[-1])
            )
            if keep_break:
                lines.append(line)
            else:
                lines[-1] = f"{lines[-1]} {line}"
        paragraphs.append("\n".join(lines))
    return "\n\n".join(paragraphs)


def _n(count: Any, one: str, many: str) -> str:
    count = int(count)
    return f"{count:,} {one if count == 1 else many}"


def _month_from_offset(offset: Any, months: list[str]) -> str:
    if offset is None or (isinstance(offset, float) and math.isnan(offset)):
        return "recently"
    idx = len(months) - 1 - int(offset)
    return MONTH_NAMES[idx] if 0 <= idx < len(MONTH_NAMES) else "recently"


def _first_month(row: dict, months: list[str]) -> str:
    for i, m in enumerate(months):
        if row[m] > 0:
            return MONTH_NAMES[i]
    return "recently"


def _product_phrase(row: dict) -> str:
    if row["bundle_heavy"]:
        return "bundles"
    if row["handpick_only"]:
        return "handpicked pieces"
    return "stock"


def _persona_phrase(row: dict) -> str:
    return {"Reseller": "your resale business", "Retailer": "the shop"}.get(row["buyer_persona"], "your business")


def _why(row: dict, v: dict) -> str:
    p = row["play"]
    gmv = f"£{v['gmv_6m']}"
    if p == "fix_crm_duplicate":
        return f"CRM flags this record as a duplicate; {gmv} of spend sits on it. Merge before anyone reaches out."
    if p == "rescue_key_account":
        return (f"{row['segment_label']} account worth {gmv} in 6 months has not bought since "
                f"{v['last_order_month']}. Revenue at risk, so retention comes before migration.")
    if p == "migrate_partial":
        return (f"Top account ({gmv}); the AM placed {v['manual_orders']} of {v['orders']} orders and "
                f"migration readiness is low ({int(row['migration_readiness'])}/100). Move routine reorders first.")
    if p == "migrate_assisted":
        return (f"Key account ({gmv}) with {v['broker_pct']}% of orders placed by the AM, but readiness "
                f"{int(row['migration_readiness'])}/100 says they can self-serve with help.")
    if p == "migrate_guided":
        return f"Mid-value account ({gmv}), {v['broker_pct']}% brokered. Big enough for a personal note, small enough to scale."
    if p == "migrate_auto":
        return f"Small account ({gmv}) but {v['broker_pct']}% brokered: AM time costs more than it earns. Automate."
    if p == "welcome_second_order":
        return "New customer with one order. The second order is the one that predicts they stick."
    if p == "winback":
        return f"Bought for themselves ({gmv}) but nothing since {v['last_order_month']}."
    if p == "reactivate":
        return f"Small account, nothing since {v['last_order_month']}. Cheap automated touch only."
    if p == "nudge_video_call":
        return (f"Spending ~£{v['runrate']}/month at ~£{v['avg_order']} per order and has never used a video call. "
                f"A live sourcing session is the lever for bigger baskets.")
    if p == "nudge_chat":
        return (f"High intent, low conversion: {v['pdp_views_n']} and {v['offers_n']} for "
                f"{v['orders_n']}, and almost no chat. Something is stopping them buying.")
    if p == "nudge_bundles":
        return "Only buys handpicks. Bundles add volume per order without more effort."
    if p == "nudge_build_a_bundle":
        return f"Bundle buyer ({int(row['bundle_gmv_share_pct'])}% of spend) who browses a lot: let them choose the mix."
    return ("Bought recently and no nudge clearly beats leaving them alone. "
            "No outreach; re-checked whenever their data changes.")


def render_drafts(df: pd.DataFrame, rules: dict, plays: dict) -> pd.DataFrame:
    months = rules["data"]["months"]
    settings = plays["settings"]
    catalogue = plays["plays"]
    out = {k: [] for k in ["action_title", "channel", "goal", "why", "draft_subject", "draft_message", "call_note"]}

    # Plain dicts are ~10x faster to read than DataFrame rows
    for row in df.to_dict("records"):
        play = catalogue[row["play"]]
        v = _SafeDict(
            name=settings.get("customer_name_fallback", "there"),
            sender=settings.get("sender", "Fleek"),
            account_id=row["account_id"],
            gmv_6m=f"{int(row['gmv_total_6m']):,}",
            orders=int(row["orders_6m"]),
            manual_orders=int(row["manual_orders"]),
            broker_pct=int(row["broker_reliance_pct"]),
            runrate=f"{int(row['gmv_runrate']):,}",
            avg_order=f"{int(row['avg_order_value']):,}",
            last_order_month=_month_from_offset(row["months_since_last_spend"], months),
            first_order_month=_first_month(row, months),
            country=row["country"],
            persona_phrase=_persona_phrase(row),
            product_phrase=_product_phrase(row),
            chat_threads=int(row["chat_threads"]),
            video_calls=int(row["video_call_requests"]),
            pdp_views=f"{int(row['pdp_views_6m']):,}",
            offers=int(row["make_an_offer_6m"]),
            readiness=int(row["migration_readiness"]),
            orders_n=_n(row["orders_6m"], "order", "orders"),
            offers_n=_n(row["make_an_offer_6m"], "offer", "offers"),
            pdp_views_n=_n(row["pdp_views_6m"], "product view", "product views"),
            video_calls_n=_n(row["video_call_requests"], "video call request", "video call requests"),
            chat_threads_n=_n(row["chat_threads"], "chat thread", "chat threads"),
            app_link=settings["links"]["app"],
            chat_link=settings["links"]["chat"],
            video_link=settings["links"]["video"],
            perk=settings.get("perk", ""),
        )
        out["action_title"].append(play["title"])
        out["channel"].append(play.get("channel", ""))
        out["goal"].append(play.get("goal", ""))
        out["why"].append(_why(row, v))
        out["draft_subject"].append(play.get("message_subject", "").format_map(v))
        out["draft_message"].append(reflow(play.get("message", "").format_map(v)))
        out["call_note"].append(reflow(play.get("call_note", "").format_map(v)))

    for k, vals in out.items():
        df[k] = vals
    return df
