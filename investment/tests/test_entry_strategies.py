"""Focused checks for independent supports; no network or account data."""
from decimal import Decimal
from types import SimpleNamespace
from investment_app.models import Band
from investment_app.config import load_config
from investment_app.entry_exit import plans_for,rr_bucket,make_plan


def inputs():
    cfg=load_config()
    bundle=SimpleNamespace(as_of="2026-09-24T16:00:00+09:00",
        metadata={"tick_size":1,"tick_evidence_id":"tick"})
    def band(key,low,high,basis):
        return Band(key,low,high,10,("price_structure","moving_average"),("price",),True,2,basis)
    bands=[band("s1",950,960,("25日線","日足安値・反発帯")),
           band("s2",880,900,("13週線","週足主要安値・反発帯")),
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
    assert (current.entry,current.stop1,current.stop2,current.target1,current.target2)==(1000,948,878,1099,1199)
    assert [p.kind for p in (current,first,second)]==["現値","第1押し目","第2押し目"]
    assert (first.entry,first.stop1,first.target1)==(960,948,1099)
    assert (second.entry,second.stop1,second.target1)==(900,878,949)
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
    assert len(plans)==1 and plans[0].entry==900 and plans[0].target1==949
    assert plans[0].eligible is True
    # A lone MA is not automatically a pullback support, even with an admitted strength.
    t["bands"]=[Band("ma",950,950,10,("moving_average",),("price",),True,0,("13週線",)),
                Band("r",1100,1100,10,("price_structure",),("price",),True,1)]
    assert [p.kind for p in plans_for(b,t,c)]==["現値"]
    assert rr_bucket(Decimal("1.2999"),c)=="Entry改善待ち"
    assert rr_bucket(Decimal("1.3"),c)=="最低限／要確認"
    assert rr_bucket(Decimal("1.5"),c)=="許容"
    assert rr_bucket(Decimal("2"),c)=="良好"

def test_live_quote_is_current_price_but_never_invents_closed_bar_trigger():
    b,t,c=inputs()
    b.metadata["automatic"]={"entry_source":"public_quote"}
    current=plans_for(b,t,c,specified_entry=1050)[0]
    assert current.kind=="現値" and current.entry==1050 and not current.trigger_confirmed
    b.metadata["automatic"]["entry_source"]="user"
    specified=plans_for(b,t,c,specified_entry=1050)[0]
    assert specified.kind=="指定価格"
    assert (current.entry,current.stop1,current.target1,current.rr)==(specified.entry,specified.stop1,specified.target1,specified.rr)


def test_minimum_upside_A_B_and_inclusive_boundary():
    a=make_plan(1000,1001,999)
    assert a.first_target_upside_pct==Decimal("0.1") and not a.eligible
    assert not make_plan(1000,1001,Decimal("999.5")).eligible # RR 2 alone cannot qualify.
    b=make_plan(1000,1060,970)
    assert b.first_target_upside_pct==6 and b.rr==2 and b.eligible
    assert make_plan(1000,1050,990).eligible
    assert not make_plan(1000,Decimal("1049.9"),990).eligible
    assert not make_plan(1000,1060,900).eligible


def test_first_strong_resistance_C_and_independent_pullback_D():
    b,t,c=inputs()
    t["bands"]=[Band("support",970,980,10,("price_structure",),("price",),True,2),
                Band("r1",1031,1040,10,("price_structure",),("price",),True,2),
                Band("r2",1081,1090,10,("price_structure",),("price",),True,2)]
    current,pullback=plans_for(b,t,c)
    assert current.target1==1030 and current.target2==1080
    assert current.first_target_upside_pct==3 and not current.eligible
    assert pullback.entry==980 and pullback.target1==1030 and pullback.stop1==968
    assert pullback.first_target_upside_pct>5 and pullback.rr>=Decimal("1.3") and pullback.eligible
    assert "未満" in current.entry_reason


def test_pullback_range_stops_before_deep_high_rr_supports():
    b,t,c=inputs()
    t["latest"]=3000
    t["bands"]=[Band("near",2940,2950,10,("price_structure",),("price",),True,2),
                Band("middle",2840,2850,10,("price_structure",),("price",),True,2),
                Band("deep",2590,2600,10,("price_structure",),("price",),True,2),
                Band("target",3031,3040,10,("price_structure",),("price",),True,2)]
    plans=plans_for(b,t,c)
    # Near and middle fail the first resistance; no search below 2700 is allowed.
    assert not any(p.kind.startswith("第") for p in plans)
    assert not any(p.support_id=="deep" for p in plans)
    # With the nearer obstructing band absent, middle is independently valid.
    t["bands"]=[b for b in t["bands"] if b.band_id!="near"]
    pull=[p for p in plans_for(b,t,c) if p.kind.startswith("第")]
    assert len(pull)==1 and pull[0].entry==2850 and pull[0].target1==3030
    assert pull[0].eligible and pull[0].entry>=2700
    # Explicit quote controls the range, even if the previous daily close differs.
    b.metadata["current_quote"]={"price":3300}
    assert not any(p.kind.startswith("第") for p in plans_for(b,t,c))
