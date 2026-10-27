from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from autopilot.config import load_plays, load_rules  # noqa: E402
from autopilot.state import Store  # noqa: E402

XLSX = ROOT / "data" / "raw" / "Fleek - Retention Case Study - Portfolio Data.xlsx"


@pytest.fixture(scope="session")
def rules():
    return load_rules()


@pytest.fixture(scope="session")
def plays():
    return load_plays()


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "test.db")
    yield s
    s.close()


BASE_ROW = {
    "account_id": "ACC-T1", "ownership": "Account Managed", "buyer_persona": "Reseller",
    "region": "United Kingdom", "country": "United Kingdom", "account_status": "Active",
    "tenure_months": 12, "gmv_total_6m": 600, "orders_6m": 6,
    "gmv_sep": 100, "gmv_oct": 100, "gmv_nov": 100, "gmv_dec": 100, "gmv_jan": 100, "gmv_feb": 100,
    "gmv_trend_pct": 0, "broker_reliance_pct": 0, "manual_orders": 0, "self_serve_orders": 6,
    "app_active_days_6m": 10, "pdp_views_6m": 50, "make_an_offer_6m": 1, "chat_threads": 0,
    "video_call_requests": 0, "handpick_orders": 3, "bundle_orders": 3, "bundle_gmv_share_pct": 50,
}


def make_raw(*rows: dict) -> pd.DataFrame:
    """Raw rows as ingest would produce them (object dtype, every column present)."""
    return pd.DataFrame([{**BASE_ROW, **r} for r in rows]).astype(object)
