from autopilot.clean import clean

from .conftest import make_raw


def test_spellings_currency_and_region(rules):
    raw = make_raw(
        {"account_id": " acc-1 ", "ownership": "self-serve", "buyer_persona": "reseller ", "country": "UK",
         "region": "EU", "gmv_total_6m": "£600", "broker_reliance_pct": "0%"},
    )
    df, issues = clean(raw, rules)
    r = df.iloc[0]
    assert r.account_id == "ACC-1"
    assert r.ownership == "Self Serve"
    assert r.buyer_persona == "Reseller"
    assert r.country == "United Kingdom"
    assert r.region == "United Kingdom"           # derived from country, not the wrong "EU"
    assert r.gmv_total_6m == 600
    assert set(issues["field"]) >= {"ownership", "country", "region"}


def test_duplicates_blank_ids_and_status(rules):
    raw = make_raw(
        {"account_id": "ACC-1", "gmv_feb": 100},
        {"account_id": "ACC-1", "gmv_feb": 200, "gmv_total_6m": 700},   # later row wins
        {"account_id": None},
        {"account_id": "ACC-2", "account_status": None},
        {"account_id": "ACC-3", "account_status": "dupe"},
    )
    df, issues = clean(raw, rules)
    assert sorted(df.account_id) == ["ACC-1", "ACC-2", "ACC-3"]
    assert df.set_index("account_id").loc["ACC-1", "gmv_feb"] == 200
    assert df.set_index("account_id").loc["ACC-2", "account_status"] == "Unset"
    assert bool(df.set_index("account_id").loc["ACC-3", "is_duplicate_record"])
    assert "row has no account id" in set(issues["issue"])


def test_numbers_reconciled_and_bounded(rules):
    raw = make_raw(
        {"account_id": "A", "gmv_total_6m": 602},                        # rounding gap vs months (600)
        {"account_id": "B", "bundle_gmv_share_pct": 140, "chat_threads": -3, "app_active_days_6m": "n/a"},
        {"account_id": "C", "tenure_months": None, "gmv_sep": 0, "gmv_oct": 0, "gmv_nov": 0,
         "gmv_dec": 0, "gmv_jan": 300, "gmv_feb": 300, "gmv_total_6m": 600},
        {"account_id": "D", "orders_6m": None, "broker_reliance_pct": None, "manual_orders": 3,
         "self_serve_orders": 1},
    )
    df, issues = clean(raw, rules)
    d = df.set_index("account_id")
    assert d.loc["A", "gmv_total_6m"] == 600
    assert d.loc["B", "bundle_gmv_share_pct"] == 100
    assert d.loc["B", "chat_threads"] == 0
    assert d.loc["B", "app_active_days_6m"] == 0
    assert d.loc["C", "tenure_months"] == 2                              # first spend in January
    assert d.loc["D", "orders_6m"] == 4
    assert d.loc["D", "broker_reliance_pct"] == 75


def test_real_file_issues_are_found(rules):
    from autopilot.ingest import read_portfolio
    from .conftest import XLSX
    df, issues = clean(read_portfolio(XLSX, "Accounts", rules), rules)
    assert len(df) == 300
    found = set(issues["issue"])
    assert "CRM marks this record as a duplicate" in found
    assert "total differs from the monthly figures by a rounding amount" in found
    assert "blank because there was no September spend (divide by zero)" in found
    assert df["account_status"].isin(["Active", "Unset", "Duplicate"]).all()
