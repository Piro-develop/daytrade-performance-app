"""UAT input assembly; prior validation and history remain independent."""
import copy
import json
import math
import pandas as pd
from .config import PROJECT,load_config
from .models import InputError, plain
from .providers import LocalCSVProvider
from .scoring import catalog
from .horizons import all_cards,analyze_horizon
from .application import analyze

def bundle_from_input(csv_data,metadata,symbol,as_of):
    meta=copy.deepcopy(metadata)
    rows=meta.get("assessments",[])
    if not isinstance(rows,list) or any(not isinstance(r,dict) or r.get("criterion_id") not in all_cards() for r in rows):
        raise InputError("採点カードの形式・IDを確認してください。")
    if len({r["criterion_id"] for r in rows})!=len(rows): raise InputError("採点カードIDが重複しています。")
    meta["assessments"]=[r for r in rows if r["criterion_id"] in catalog()]
    bundle=LocalCSVProvider(csv_data,meta).fetch(symbol,as_of)
    bundle.metadata["assessments"]=rows
    return bundle

def run_all(bundle,history,policy="unspecified",entry=None):
    cfg=load_config();results={}
    swing=copy.deepcopy(bundle)
    swing.metadata["assessments"]=[r for r in swing.metadata.get("assessments",[]) if r["criterion_id"] in catalog()]
    r=analyze(swing,cfg,entry,policy)
    r.metadata["horizon"]="swing"
    from .models import digest
    r.approval_hash=digest({k:v for k,v in plain(r).items() if k!="approval_hash"})
    pending=[(r,swing,cfg)];results["swing"]=plain(r)
    for h in ("midlong","daytrade"):
        result,b,c=analyze_horizon(bundle,cfg,h,policy,entry)
        pending.append((result,b,c));results[h]=plain(result)
    # Persist the three independent snapshots in one transaction, avoiding partial groups.
    save_group(history,pending)
    return results

def save_group(history,pending):
    from datetime import datetime,timezone
    from .models import canonical,InputError
    with history.connect() as db:
        for result,bundle,cfg in pending:
            refs={ref for p in result.plans for ref in p.evidence_ids}
            refs|={ref for d in result.decisions.values() for ref in d.evidence_ids}
            if not refs.issubset(result.evidence): raise InputError("保存対象のEvidence参照が欠落")
            db.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?)",(result.run_id,datetime.now(timezone.utc).isoformat(),
                result.symbol,result.as_of,result.config_hash,result.approval_hash,canonical(result),canonical(bundle),canonical(cfg)))
            db.executemany("INSERT INTO evidence VALUES (?,?,?)",[(result.run_id,k,canonical(v)) for k,v in result.evidence.items()])

def demo():
    meta=json.loads((PROJECT/"data/demo_evidence.json").read_text(encoding="utf-8"))
    asof="2026-09-09T14:30:00+09:00"
    meta.update(as_of=asof,name="架空・全時間軸UAT株式会社")
    for ev in meta["evidence"]:
        for key in ("observed_at","published_at","fetched_at"): ev[key]=asof
    days=pd.bdate_range(end="2026-09-08",periods=800)
    rows=[]
    for i,day in enumerate(days):
        close=800+.23*i+65*math.sin(i*2*math.pi/55)
        if i==799: close=1000
        rows.append({"symbol_code":"TEST0001","timestamp":day.strftime("%Y-%m-%d")+"T15:30:00+09:00",
            "open":round(close-2,2),"high":round(close+8,2),"low":round(close-9,2),"close":round(close,2),
            "volume":int(350000+60000*math.sin(i/9)),"adjustment_basis":"synthetic_split_adjusted"})
    meta["calendar"]=[d.strftime("%Y-%m-%d") for d in pd.bdate_range(days[0],end="2026-10-30")]
    intraday=[]
    times=list(pd.date_range("2026-09-09T09:05:00+09:00","2026-09-09T11:30:00+09:00",freq="5min"))
    times+=list(pd.date_range("2026-09-09T12:35:00+09:00","2026-09-09T14:30:00+09:00",freq="5min"))
    for i,stamp in enumerate(times):
        close=1000+12*math.sin(i*2*math.pi/9)
        intraday.append({"timestamp":stamp.isoformat(),"open":round(close-1,2),"high":round(close+3,2),
            "low":round(close-5,2),"close":round(close,2),"volume":12000+i*100})
    meta.update(intraday_bars=intraday,intraday_interval="5m",intraday_closed_confirmed=True,intraday_evidence_id="demo-structure",
        latest_financial={"latest_confirmed":True,"period":"架空2026年度","evidence_ids":["demo-financial"]},
        today_material_evidence_ids=["demo-news"],same_time_volume_evidence_ids=["demo-flow"],execution_evidence_ids=["demo-flow"])
    for code,card in all_cards().items():
        if code in catalog(): continue
        ref="demo-macro" if code in ("ML-G","DT-D","DC-3") else "demo-structure" if code.startswith(("ME-","DE-")) else "demo-financial"
        meta["assessments"].append({"criterion_id":code,"anchor":8,"evidence_ids":[ref],
            "reason":"架空設定："+card["anchors"]["8"],"counter_reason":"実在資料ではない。前提失効時に再評価。",
            "rule_version":"cards-1.0.0","evaluator":"fixture_human"})
    return pd.DataFrame(rows).to_csv(index=False).encode(),meta

def recommendation(results, now=None):
    from datetime import datetime,timezone
    from .models import time_value
    now=now or datetime.now(timezone.utc)
    # Do not compare raw scores across horizons or silently turn high scores into a buy.
    preferred=[]
    for h,r in results.items():
        current=r["decisions"].get("現値:avoid") or next(iter(r["decisions"].values()))
        plan=next((p for p in r["plans"] if p["kind"]=="現値"),None)
        if plan and time_value(plan["expires_at"])>=now and current["status"]=="評価可能" and not current["approval_required"] and current["label"] in ("買い","条件付き買い","打診買い"):
            preferred.append(h)
    return preferred
