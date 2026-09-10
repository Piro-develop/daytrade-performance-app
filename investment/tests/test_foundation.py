import copy
import json
import pytest
from investment_app.config import load_config, validate_config
from investment_app.models import Evidence, InputError, Severity
from investment_app.providers import LocalCSVProvider
from investment_app.preflight import preflight

CSV = b"symbol_code,timestamp,open,high,low,close,volume,adjustment_basis\nTEST,2026-09-09T15:30:00+09:00,100,110,90,105,1000,split_adjusted\n"
META = {"symbol":"TEST"}
ASOF = "2026-09-09T16:00:00+09:00"

def test_config_weights_and_contract():
    cfg = load_config()
    assert sum(cfg["investment_weights"].values()) == 100
    assert sum(cfg["entry_weights"].values()) == 100
    bad = copy.deepcopy(cfg)
    bad["mix"] = [1,0]
    with pytest.raises(InputError):
        validate_config(bad)

def test_csv_missing_is_not_zero():
    with pytest.raises(InputError):
        LocalCSVProvider(CSV.replace(b",105,", b",,"), META).fetch("TEST", ASOF)

def test_symbol_preserved_and_reject_mismatch():
    bundle = LocalCSVProvider(CSV, META).fetch("TEST", ASOF)
    assert bundle.symbol == "TEST"
    with pytest.raises(InputError):
        LocalCSVProvider(CSV, META).fetch("OTHER", ASOF)

def test_future_price_and_evidence_rejected():
    with pytest.raises(InputError):
        LocalCSVProvider(CSV, META).fetch("TEST", "2026-09-08T16:00:00+09:00")
    ev = Evidence("x","source","local:x",ASOF,"2026-09-10T12:00:00+09:00",ASOF,"fact","hash")
    with pytest.raises(InputError):
        ev.validate(ASOF)

def test_conflicting_duplicates_are_critical():
    row = CSV.splitlines()[1]
    data = CSV + row.replace(b",105,", b",106,") + b"\n"
    bundle = LocalCSVProvider(data, META).fetch("TEST", ASOF)
    assert any(x.severity == Severity.CRITICAL and x.code == "conflicting_prices" for x in bundle.findings)

def test_preflight_needs_independent_review():
    bundle = LocalCSVProvider(CSV, META).fetch("TEST", ASOF)
    warnings = preflight(bundle, 0)
    assert {x.code for x in warnings} >= {"weekly_missing","unchecked_negative_news","unchecked_liquidity","unchecked_thesis"}

def test_price_adjustment_mixed_rejected():
    other = CSV.splitlines()[1].replace(b"2026-09-09",b"2026-09-08").replace(b"split_adjusted",b"raw")
    with pytest.raises(InputError):
        LocalCSVProvider(CSV + other + b"\n", META).fetch("TEST", ASOF)

def test_metadata_invalid_dates_and_shapes_are_friendly_errors():
    for extra in ({"calendar":["2026-99-01"]},{"tick_size":"NaN"},{"preflight_review":[]},
                  {"earnings_at":ASOF,"earnings_evidence_ids":["missing"]}):
        with pytest.raises(InputError):
            LocalCSVProvider(CSV,dict(META,**extra)).fetch("TEST",ASOF)

def test_previous_session_price_is_current_before_today_close():
    bundle=LocalCSVProvider(CSV,dict(META,calendar=["2026-09-09","2026-09-10"])).fetch("TEST","2026-09-10T10:00:00+09:00")
    assert not any(f.code=="stale_prices" for f in preflight(bundle,60))

def test_foreign_currency_and_incomplete_daily_bar_rejected():
    usd=CSV.replace(b"adjustment_basis\n",b"adjustment_basis,currency\n").replace(b"split_adjusted\n",b"split_adjusted,USD\n")
    unfinished=CSV.replace(b"adjustment_basis\n",b"adjustment_basis,is_closed\n").replace(b"split_adjusted\n",b"split_adjusted,false\n")
    for content in (usd,unfinished):
        with pytest.raises(InputError):
            LocalCSVProvider(content,META).fetch("TEST",ASOF)

def test_unknown_scoring_card_rejected():
    with pytest.raises(InputError):
        LocalCSVProvider(CSV,dict(META,assessments=[{"criterion_id":"FAKE"}])).fetch("TEST",ASOF)
