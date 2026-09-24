from decimal import Decimal
import numpy as np
import pandas as pd
from investment_app.config import load_config
from investment_app.entry_exit import rr, make_plan, rr_bucket
from investment_app.technical import indicators, weekly_bars, pivots, cluster_levels

def frame(n=100):
    idx=pd.date_range("2025-01-01",periods=n,freq="B",tz="Asia/Tokyo")+pd.Timedelta(hours=15,minutes=30)
    return pd.DataFrame({"open":np.arange(n)+100.,"high":np.arange(n)+102.,
        "low":np.arange(n)+99.,"close":np.arange(n)+101.,"volume":1000.},index=idx)

def test_indicators_use_real_periods():
    out=indicators(frame(),[13,25,50,75],load_config())
    assert out.iloc[-1].ma13 == out.close.tail(13).mean()
    assert np.isclose(out.iloc[-1].atr,3)
    assert out.iloc[-1].rsi == 100
    assert out.iloc[-1].bb_upper > out.iloc[-1].bb_mid
    assert pd.isna(out.iloc[5].ma13)

def test_partial_week_excluded():
    data=frame(7)
    weekly=weekly_bars(data,data.index[-1].isoformat(),[])
    assert all(x.date() < data.index[-1].date() for x in weekly.index)

def test_pivot_cannot_look_into_future():
    data=frame(10)
    data.loc[data.index[7],"high"]=1000
    assert not any(p["index"]==7 for p in pivots(data.iloc[:9],2,13))
    assert any(p["index"]==7 for p in pivots(data,2,13))

def test_rr_formula_and_improvement_fixed_stop():
    first=make_plan(1000,1060,950)
    better=make_plan(980,1060,950)
    assert first.rr==Decimal("1.2")
    assert better.rr>2
    assert first.stop1==better.stop1==950
    assert first.target1==better.target1==1060
    assert rr(950,1060,950) is None

def test_rr_boundaries_not_hard_cutoff():
    cfg=load_config()
    assert rr_bucket(Decimal("1.4999"),cfg)=="最低限／要確認"
    assert rr_bucket(Decimal("1.5"),cfg)=="許容"
    assert rr_bucket(Decimal("1.9999"),cfg)=="許容"
    assert rr_bucket(Decimal("2"),cfg)=="良好"

def test_same_family_not_inflated():
    cfg=load_config()
    level={"id":"a","low":105,"high":105,"timeframe":"1w","family":"moving_average","source":"ma","label":"13週線","evidence_ids":["e"]}
    one=cluster_levels([level],frame(10),1,1,cfg)[0]
    many=cluster_levels([dict(level,id=str(n)) for n in range(10)],frame(10),1,1,cfg)[0]
    assert one.strength==many.strength
    assert one.basis==many.basis==("13週線",)

def test_friday_close_is_a_complete_week():
    data=frame(8)
    weekly=weekly_bars(data,data.index[-1].isoformat(),[])
    assert weekly.index[-1].date()==data.index[-1].date()
