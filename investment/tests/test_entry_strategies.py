"""Focused checks for independent supports; no network or account data."""
from decimal import Decimal
from types import SimpleNamespace
from investment_app.models import Band
from investment_app.config import load_config
from investment_app.entry_exit import plans_for,rr_bucket


def inputs():
    cfg=load_config()
    bundle=SimpleNamespace(as_of="2026-09-24T16:00:00+09:00",
        metadata={"tick_size":1,"tick_evidence_id":"tick"})
    def band(key,low,high,basis):
        return Band(key,low,high,10,("price_structure","moving_average"),("price",),True,2,basis)
    bands=[band("s1",950,960,("25日線","日足安値・反発帯")),
           band("s2",900,920,("13週線","週足主要安値・反発帯")),
           band("s3",800,820,("26週線","週足主要安値・反発帯")),
           band("r1",1100,1110,("週足主要高値",)),
           band("r2",1200,1210,("週足主要高値",))]
    class Daily(list):
        @property
        def iloc(self): return self
    daily=Daily([SimpleNamespace(low=995,close=1000),SimpleNamespace(low=995,close=1000)])
    tech={"tick_valid":True,"latest":1000,"bands":bands,"atr":20,"technical_evidence_id":"price","daily":daily}
    return bundle,tech,cfg


def test_independent_pullbacks_keep_current_prices_and_stop_first():
    b,t,c=inputs()
    current,first,second=plans_for(b,t,c)
    assert (current.entry,current.stop1,current.stop2,current.target1,current.target2)==(1000,948,898,1099,1199)
    assert [p.kind for p in (current,first,second)]==["現値","第1押し目","第2押し目"]
    assert (first.entry,first.stop1,first.target1)==(960,948,1099)
    assert (second.entry,second.stop1,second.target1)==(920,898,949)
    assert first.support_id!=second.support_id and second.resistance_id==first.support_id
    assert "25日線" in first.support_basis and "13週線" in second.support_basis
    for p in (current,first,second):
        assert p.rr==(p.target1-p.entry)/(p.entry-p.stop1)
        assert p.stop1<Decimal(str(p.support_low))<=Decimal(str(p.support_high))
    # Changing upside does not tighten any structural stop to make RR look better.
    t["bands"][-2]=Band("r1",1010,1020,10,("price_structure",),("price",),True,1)
    changed=plans_for(b,t,c)
    assert [p.stop1 for p in changed]==[p.stop1 for p in (current,first,second)]
    assert changed[0].rr<Decimal("1.3")


def test_missing_current_target_does_not_hide_valid_deeper_plan_or_invent_one():
    b,t,c=inputs()
    t["bands"]=t["bands"][:2]
    plans=plans_for(b,t,c)
    assert len(plans)==1 and plans[0].entry==920 and plans[0].target1==949
    # A lone MA is not automatically a pullback support, even with an admitted strength.
    t["bands"]=[Band("ma",950,950,10,("moving_average",),("price",),True,0,("13週線",)),
                Band("r",1100,1100,10,("price_structure",),("price",),True,1)]
    assert [p.kind for p in plans_for(b,t,c)]==["現値"]
    assert rr_bucket(Decimal("1.2999"),c)=="Entry改善待ち"
    assert rr_bucket(Decimal("1.3"),c)=="最低限／要確認"
    assert rr_bucket(Decimal("1.5"),c)=="許容"
    assert rr_bucket(Decimal("2"),c)=="良好"
