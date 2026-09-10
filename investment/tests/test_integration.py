import copy
from pathlib import Path
import pytest
from investment_app.config import PROJECT,load_config
from investment_app.providers import LocalCSVProvider,read_metadata
from investment_app.application import analyze
from investment_app.models import InputError,canonical,EvaluationStatus
from investment_app.storage import History

def demo():
    return LocalCSVProvider((PROJECT/"data/demo_prices.csv").read_bytes(),
        read_metadata((PROJECT/"data/demo_evidence.json").read_bytes()))

def result(entry=None,mutate=None):
    provider=demo()
    if mutate:
        mutate(provider.metadata)
    bundle=provider.fetch("TEST0001",provider.metadata["as_of"])
    cfg=load_config()
    return analyze(bundle,cfg,entry),bundle,cfg

def test_vertical_slice_complete_and_reproducible():
    first,b,cfg=result()
    second,_,_=result()
    assert first.plans
    assert first.scores["現値"].investment is not None
    assert first.scores["現値"].entry is not None
    assert first.scores["現値"].investment==second.scores["現値"].investment
    assert first.technical==second.technical
    assert first.bundle_id==second.bundle_id
    assert first.plans==second.plans

def test_entry_change_cannot_change_investment():
    first,_,_=result()
    second,_,_=result(980)
    assert next(iter(first.scores.values())).investment==next(iter(second.scores.values())).investment

def test_evidence_trace_and_sqlite_restore(tmp_path):
    out,b,cfg=result()
    db=History(tmp_path/"history.sqlite")
    db.save(out,b,cfg)
    stored=db.get(out.run_id)
    assert stored["config_hash"]==out.config_hash
    assert stored["evidence"]
    for decision in stored["decisions"].values():
        assert all(x in stored["evidence"] for x in decision["evidence_ids"])
    for plan in stored["plans"]:
        assert all(x in stored["evidence"] for x in plan["evidence_ids"])
    assert len(db.list_runs())==1

def test_missing_card_preserved_as_null():
    out,_,_=result(mutate=lambda meta:meta.update(assessments=[x for x in meta["assessments"] if x["criterion_id"]!="SW-A1"]))
    assert out.scores["現値"].investment is None
    assert "SW-A1" in out.scores["現値"].missing
    assert out.decisions["現値:allow"].label is None

def test_independent_weekly_direction_cannot_be_manual_overwritten():
    out,_,_=result()
    assert out.scores["現値"].items["SW-D1"]["evaluator"]=="program"
    assert "週足" in out.scores["現値"].items["SW-D1"]["reason"]
    assert out.technical["weekly_count"]>=58

def test_no_calendar_no_fake_business_days():
    out,_,_=result(mutate=lambda meta:meta.pop("calendar"))
    assert out.earnings["business_days"] is None
    assert any(x.code=="calendar_missing" for x in out.findings)

def test_future_entry_retains_both_exit_prices():
    out,_,_=result()
    if len(out.plans)>1:
        assert out.plans[0].stop1==out.plans[1].stop1
        assert out.plans[0].target1==out.plans[1].target1
        assert out.plans[1].rr>out.plans[0].rr
        assert out.scores[out.plans[1].kind].entry is None

def test_unknown_macro_is_not_neutral_context():
    out,_,_=result(mutate=lambda m:m.pop("macro"))
    assert out.scores["現値"].items["SW-F"]["score"] is None
    assert out.scores["現値"].items["SC-4"]["score"] is None

def test_stale_prices_stay_provisional_even_with_full_scores():
    out,_,_=result(mutate=lambda m:m.update(as_of="2026-09-10T16:00:00+09:00"))
    assert out.scores["現値"].status==EvaluationStatus.PROVISIONAL
    assert out.decisions["現値:allow"].label is None

def test_confidence_uses_required_evidence_and_no_quality_assumption():
    full,_,_=result()
    missing,_,_=result(mutate=lambda m:m.pop("evidence_quality"))
    assert set(full.confidence["components"])=={"F","C","S","X"}
    assert missing.confidence["value"]<full.confidence["value"]
    assert full.scores["現値"].investment==missing.scores["現値"].investment
