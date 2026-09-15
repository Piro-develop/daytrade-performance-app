"""Bounded checks for acquisition failures, immutable saves and actual tick rules."""
from datetime import datetime,timezone,timedelta
from types import SimpleNamespace
import copy,json
import pytest
import pandas as pd
from judgment import automatic
from judgment.service import JudgmentService
from investment_app.models import InputError,JST
from investment_app.uat_service import demo
from investment_app.entry_exit import plans_for
from investment_app.config import load_config
from test_firestore_judgment import FakeFirestore,store

def test_completed_bars_only_and_no_zero_fill():
    now=datetime(2026,9,14,10,7,tzinfo=JST)
    stamps=[int(now.replace(hour=9,minute=m).timestamp()) for m in (0,5,10)]
    quotes={k:[100,100,None] for k in ("open","high","low","close")}
    quotes["volume"]=[1000,1000,1000]
    data={"timestamp":stamps,"indicators":{"quote":[quotes]}}
    rows,omitted=automatic.normalize_chart(data,"7203","5m",now.replace(hour=9,minute=7))
    assert len(rows)==1 and rows[0]["timestamp"].endswith("09:05:00+09:00")
    rows,omitted=automatic.normalize_chart(data,"7203","5m",now)
    assert len(rows)==2 and omitted==1
    with pytest.raises(ValueError):automatic.normalize_chart(data,"7203","1d",now)
    assert automatic.resolve("トヨタ",[{"code":"7203","name":"トヨタ自動車"}])["code"]=="7203"

def test_one_source_failure_does_not_discard_daily(monkeypatch):
    now=datetime.now(timezone.utc)
    day=now.astimezone(JST).date()-timedelta(days=4)
    data={"timestamp":[int(datetime.combine(day,datetime.min.time(),JST).timestamp())],
          "indicators":{"quote":[{"open":[100],"high":[110],"low":[90],"close":[105],"volume":[1000]}]},
          "meta":{}}
    monkeypatch.setattr(automatic,"company_reference",lambda:([{"code":"7203","name":"トヨタ"}],"hash",now.isoformat()))
    def fetch(symbol,interval):
        if interval=="5m":raise ValueError("upstream internal response")
        return data,"https://example.invalid/prices","hash"
    monkeypatch.setattr(automatic,"chart",fetch)
    monkeypatch.setattr(automatic.PublicContextProvider,"fetch",lambda *a:(_ for _ in ()).throw(InputError("internal XML error")))
    result=automatic.acquire("7203")
    assert result["csv"] and len(result["notices"])==2
    assert "internal" not in str(result["notices"])
    assert result["metadata"]["assessments"]==[]
    assert not result["metadata"].get("preflight_review")

def test_automatic_engine_firestore_roundtrip_without_fake_scores(monkeypatch):
    raw,meta=demo()
    # Technical-only input: no fake neutral anchors or completed Preflight.
    meta["assessments"]=[];meta["preflight_review"]={}
    meta["automatic"]={"notices":[]};meta["macro"]={}
    response={"symbol":meta["symbol"],"name":meta["name"],"as_of":meta["as_of"],
              "metadata":meta,"csv":raw,"notices":[]}
    monkeypatch.setattr(automatic,"acquire",lambda _:copy.deepcopy(response))
    db=FakeFirestore();service=JudgmentService(store=store(db))
    out=service.automatic("alice",{"symbol":"7203"})
    assert out["saved"] and len(out["results"])==3 and db.commits==1
    for result in out["results"].values():
        assert all(s["investment"] is None for s in result["scores"].values())
        assert all(d["label"] not in {"買い","強気買い"} for d in result["decisions"].values())
        assert store(db).get(result["run_id"])==result
        assert result["metadata"]["automatic"]["assessment_provider"] if "assessment_provider" in result["metadata"]["automatic"] else True
    before=copy.deepcopy(db.docs)
    response["csv"]=None
    held=service.automatic("alice",{"symbol":"7203"})
    assert held["status"]=="評価保留" and not held["saved"] and db.docs==before

def test_price_level_ticks_keep_rr_and_stop_first():
    cfg=load_config()
    bundle=SimpleNamespace(as_of="2026-09-14T08:00:00+00:00",metadata={
       "tick_size":.5,"tick_evidence_id":"tick","tick_schedule":[{"up_to":1000,"tick":.1},{"up_to":3000,"tick":.5},{"up_to":None,"tick":1}]})
    bands=[SimpleNamespace(low=990.1,high=992,strength=10,band_id="s",evidence_ids=["e"]),
           SimpleNamespace(low=1010.3,high=1012,strength=10,band_id="r",evidence_ids=["e"])]
    technical={"tick_valid":True,"latest":1005,"bands":bands,"atr":1,
       "technical_evidence_id":"e","daily":pd.DataFrame([{"low":999,"close":1000},{"low":999,"close":1005}])}
    plans=plans_for(bundle,technical,cfg)
    assert plans
    first=plans[0]
    assert float(first.target1)==1009.5
    assert float(first.stop1)==990.0
    assert float(first.rr)==pytest.approx((1009.5-1005)/(1005-990))
    if len(plans)>1:assert plans[1].stop1==first.stop1 and plans[1].target1==first.target1
