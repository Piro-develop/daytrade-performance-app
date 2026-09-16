import copy
from dataclasses import replace
from decimal import Decimal
import pytest
from investment_app.uat_service import demo,bundle_from_input,run_all,save_group
from investment_app.horizons import settings,all_cards,horizon_technical,score_horizon,analyze_horizon
from investment_app.config import load_config
from investment_app.models import EvaluationStatus,Finding,Severity,InputError,canonical
from investment_app.entry_exit import make_plan,rr
from investment_app.decision import decide
from investment_app.ai_bridge import export_request,import_response
from investment_app.storage import History

@pytest.fixture(scope="module")
def source():
    csv,m=demo()
    return bundle_from_input(csv,m,m["symbol"],m["as_of"])

def test_spec_weights_and_rr():
    h=settings()
    assert list(h["midlong"]["investment_weights"].values())==[25,15,13,12,10,8,7,6,2,2]
    assert h["active_horizons"]==["swing","midlong"]
    assert len(all_cards())==55
    assert rr(1000,1100,950)==Decimal(2)

def test_midlong_stress_missing_and_separation(source):
    cfg=load_config();b=copy.deepcopy(source);t=horizon_technical(b,cfg,"midlong")
    p=make_plan(1000,1100,950,evidence_ids=(t["technical_evidence_id"],),trigger_confirmed=True)
    first=score_horizon(b,t,p,cfg,"midlong")
    second=score_horizon(b,t,replace(p,entry=Decimal(990),rr=rr(990,1100,950)),cfg,"midlong")
    assert first.investment==second.investment==8
    assert first.entry!=second.entry
    b.metadata["assessments"]=[a for a in b.metadata["assessments"] if a["criterion_id"]!="ME-E-STRESS"]
    missing=score_horizon(b,t,p,cfg,"midlong")
    assert missing.entry is None and missing.items["ME-E"]["score"] is None
    assert len(t["monthly"])==0
    assert all(l["timeframe"] in ("1w","1mo") for l in t["levels"])


def test_two_horizon_atomic_storage_and_unchanged_stops(source,tmp_path):
    db=History(tmp_path/"runs.sqlite")
    results=run_all(source,db)
    assert len(db.list_runs())==2
    for r in results.values():
        restored=db.get(r["run_id"])
        assert canonical(restored)==canonical(r)
        if len(r["plans"])>1:
            a,b=r["plans"][:2]
            assert a["stop1"]==b["stop1"] and a["target1"]==b["target1"]
        for d in r["decisions"].values():
            assert set(d["evidence_ids"]).issubset(r["evidence"])
    with pytest.raises(Exception):
        with db.connect() as conn:
            conn.execute("INSERT INTO failures VALUES ('rollback','now','test')")
            raise RuntimeError("interrupted")
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM failures WHERE failure_id='rollback'").fetchone()[0]==0

def test_ai_cannot_change_numeric_or_invent_evidence(source):
    from investment_app.models import plain
    evidence=plain(source.evidence)
    req=export_request(source.symbol,source.as_of,evidence,["demo-financial"])
    row={"criterion_id":"MC-1","anchor_id":"8","evidence_ids":["demo-financial"],"reason":"根拠の解釈","counter_reason":"反証"}
    payload={"request_id":req["request_id"],"assessments":[row]}
    assert import_response(payload,req)[0]["anchor"]==8
    for invalid in ({**row,"target":2000},{**row,"anchor_id":"8.3"},{**row,"evidence_ids":["invented"]},{**row,"criterion_id":"ML-A"}):
        with pytest.raises(InputError): import_response({**payload,"assessments":[invalid]},req)

def test_valuation_formula_and_red_earnings_rejected(source):
    from investment_app.valuation import valuation_bands
    b=copy.deepcopy(source)
    b.metadata["valuation_plan"]={"eps":"100","multiple_first":"12","multiple_final":"15","currency":"JPY",
        "formula":"EPS*PE","period":"2028","assumptions":"根拠付きの利益・業種適合倍率","sector_suitable_confirmed":True,
        "evidence_ids":["demo-financial"]}
    bands=valuation_bands(b,7)
    assert [x.low for x in bands]==[1200,1500]
    assert all(ref in b.evidence for x in bands for ref in x.evidence_ids)
    b.metadata["valuation_plan"]["eps"]="-100"
    with pytest.raises(InputError): valuation_bands(b,7)


def test_manual_evidence_hash_stable_and_ai_numbers_rejected(source):
    from investment_app.manual_input import build_metadata
    from investment_app.validation_ui import evidence_seed
    from investment_app.models import plain
    m=source.metadata
    first=build_metadata(m,evidence_seed(m),[])
    second=build_metadata(first,evidence_seed(first),[])
    assert first["evidence"]==second["evidence"]
    req=export_request(source.symbol,source.as_of,plain(source.evidence),["demo-financial"])
    with pytest.raises(InputError):
        import_response({"request_id":req["request_id"],"assessments":[{"criterion_id":"MC-1","anchor_id":"8",
            "evidence_ids":["demo-financial"],"reason":"EPSを999999と推測","counter_reason":"反証"}]},req)
