"""Independent horizon scoring and structural price plans."""
from __future__ import annotations
import copy
import json
import uuid
from dataclasses import replace
from datetime import datetime, time
import pandas as pd
from .config import PROJECT
from .models import *
from .technical import compute, indicators, pivots, cluster_levels, number
from .entry_exit import plans_for
from .scoring import checked_manual, interpolate, macro_chain
from .preflight import preflight, confidence
from .decision import decide
from .application import earnings_info

def settings():
    return json.loads((PROJECT/"config/horizons.json").read_text(encoding="utf-8"))

def all_cards():
    return json.loads((PROJECT/"config/all_scoring_cards.json").read_text(encoding="utf-8"))["cards"]

def horizon_cards(horizon):
    h=settings()[horizon]
    prefixes=(h["prefix"]+"-",h["entry_prefix"]+"-",h["context_prefix"]+"-")
    return {k:v for k,v in all_cards().items() if k.startswith(prefixes)}

def valid_refs(bundle, refs):
    return isinstance(refs,list) and bool(refs) and all(r in bundle.evidence for r in refs)

def monthly_bars(daily, as_of):
    monthly=daily.resample("ME").agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum"}).dropna()
    cutoff=time_value(as_of).astimezone(JST)
    # Only months strictly before the current month are complete without an exchange calendar.
    return monthly.loc[(monthly.index.year*12+monthly.index.month)<cutoff.year*12+cutoff.month]

def structure_levels(frame, interval, ref, cfg):
    return [{"id":digest([interval,p])[:16],"low":p["price"],"high":p["price"],
             "timeframe":interval,"family":"price_structure",
             "source":"major_pivot" if p["major"] else "pivot","evidence_ids":[ref]}
            for p in pivots(frame,cfg["pivot_span"],cfg["major_span"])]

def horizon_technical(bundle,cfg,horizon):
    tech=compute(bundle,cfg)
    tid=tech["technical_evidence_id"]
    if horizon=="midlong":
        monthly=monthly_bars(tech["daily"],bundle.as_of)
        tech["monthly"]=monthly
        # Weekly/monthly actual structure controls exits. Daily indicators remain timing only.
        levels=[x for x in tech["levels"] if x["timeframe"]=="1w" and x["family"]=="price_structure"]
        levels+=structure_levels(monthly.tail(60),"1mo",tid,cfg)
        tech["atr"]=number(tech["weekly"].iloc[-1].atr) if len(tech["weekly"]) else None
        tech["levels"]=levels
        config=copy.deepcopy(cfg);config["timeframe_weights"]["1mo"]=4
        tech["bands"]=cluster_levels(levels,tech["weekly"],tech["atr"],float(bundle.metadata.get("tick_size") or 1),config) if tech["tick_valid"] else []
    else:
        rows=bundle.metadata.get("intraday_bars",[])
        ref=bundle.metadata.get("intraday_evidence_id")
        if not rows or ref not in bundle.evidence:
            tech["intraday_count"]=0;tech["bands"]=[];return tech
        frame=pd.DataFrame(rows)
        required={"timestamp","open","high","low","close","volume"}
        if not required.issubset(frame.columns): raise InputError("分足OHLCVの列が不足しています。")
        times=[time_value(str(x)) for x in frame.timestamp]
        if len(set(times))!=len(times) or any(t>time_value(bundle.as_of) for t in times):
            raise InputError("分足に重複日時または未来の足があります。")
        for col in ("open","high","low","close","volume"):
            frame[col]=pd.to_numeric(frame[col],errors="coerce")
        import numpy as np
        if not np.isfinite(frame[list(required-{"timestamp"})]).all().all():
            raise InputError("分足の欠損・非数値は補完できません。")
        if (frame[["open","high","low","close"]]<=0).any().any() or (frame.volume<0).any() or (frame.high<frame[["open","low","close"]].max(axis=1)).any() or (frame.low>frame[["open","high","close"]].min(axis=1)).any():
            raise InputError("分足の価格関係が不正です。")
        if not bundle.metadata.get("intraday_closed_confirmed") or bundle.metadata.get("intraday_interval")!="5m":
            raise InputError("分足は足の終了時刻を持つ確定5分足を指定してください。")
        local_times=[t.astimezone(JST) for t in times]
        if any(t.minute%5 or t.second or not (time(9,5)<=t.time()<=time(11,30) or time(12,35)<=t.time()<=time(15,30)) for t in local_times):
            raise InputError("5分足の終了時刻が取引時間・5分区切りに一致しません。")
        frame.index=pd.DatetimeIndex(times).tz_convert("Asia/Tokyo")
        frame=frame.sort_index()
        today=time_value(bundle.as_of).astimezone(JST).date()
        frame=frame.loc[[t.date()==today for t in frame.index]]
        tech["intraday_count"]=len(frame)
        if frame.empty: tech["bands"]=[];return tech
        frame=indicators(frame,cfg["daily_ma"],cfg)
        newtid="technical-day-"+digest({"bars":rows,"cfg":cfg})[:16]
        bundle.evidence[newtid]=Evidence(newtid,"確定5分足計算","local:intraday",frame.index[-1].isoformat(),frame.index[-1].isoformat(),bundle.as_of,
            "当日の確定5分足のみから価格構造を計算",digest(rows),"calculation",1,(ref,))
        tech["technical_evidence_id"]=newtid
        tech["daily"]=frame;tech["latest"]=float(frame.iloc[-1].close)
        tech["atr"]=number(frame.iloc[-1].atr);tech["rsi"]=number(frame.iloc[-1].rsi)
        tech["volume_ratio"]=None # Never compare current cumulative volume with a full day.
        tech["intraday_age_minutes"]=(time_value(bundle.as_of)-frame.index[-1].to_pydatetime()).total_seconds()/60
        levels=structure_levels(frame,"5m",newtid,cfg)
        # Yesterday's daily structure is a separate source of intraday resistance.
        levels += [x for x in tech["levels"] if x["timeframe"]=="1d" and x["family"] in ("price_structure","volume_profile")]
        for col,family,source in [(f"ma{p}","moving_average","ma") for p in cfg["daily_ma"]]+[("bb_upper","volatility_band","bb"),("bb_lower","volatility_band","bb")]:
            value=number(frame.iloc[-1][col])
            if value and value>0:
                levels.append({"id":digest([newtid,col,value])[:16],"low":value,"high":value,"timeframe":"5m",
                    "family":family,"source":source,"evidence_ids":[newtid]})
        conf=copy.deepcopy(cfg);conf["timeframe_weights"]["5m"]=1
        tech["levels"]=levels
        tech["bands"]=cluster_levels(levels,frame,tech["atr"],float(bundle.metadata.get("tick_size") or 1),conf) if tech["tick_valid"] else []
    return tech

def score_horizon(bundle,tech,plan,cfg,horizon):
    h=settings()[horizon];cards=horizon_cards(horizon)
    items=checked_manual(bundle,cards)
    def put(code,value,reason,refs):
        items[code]={"score":value,"reason":reason,"counter_reason":"主要な反証・価格構造を別途確認","evidence_ids":list(refs),
                     "evaluator":"program","rule_version":"cards-1.0.0","purpose":cards[code]["label"]}
    macro=macro_chain(bundle)
    if not macro["valid"]:
        for code in (("ML-G",) if horizon=="midlong" else ("DT-D","DC-3")):
            put(code,None,"セクター→地合い→ドライバー→企業感応度→個別比較の根拠不足",[])
    if horizon=="midlong":
        if not bundle.metadata.get("earnings_at"):
            put("ME-G",None,"直近の決算予定が未確認",[])
        if len(tech["monthly"])<settings()["monthly_min"] or tech["weekly_count"]<cfg["weekly_min"]:
            for code in ("ML-I","ME-A"):
                put(code,None,"長期構造に必要な確定週足58本・月足24本が不足",[])
        if plan:
            stress=items.get("ME-E-STRESS",{}).get("score")
            refs=list(plan.evidence_ids)+items.get("ME-E-STRESS",{}).get("evidence_ids",[])
            put("ME-E",None if stress is None else (interpolate(plan.rr,cfg["rr_knots"])+stress)/2,
                f"RR={plan.rr}の補間とストレス評価={stress}を等重み集約",refs)
    else:
        if plan: put("DE-C",interpolate(plan.rr,cfg["rr_knots"]),f"RR={plan.rr}：第1水準による計算",plan.evidence_ids)
        # High execution anchors require direct time-stamped execution evidence.
        if items.get("DE-E",{}).get("score",0) in (8,10) and not valid_refs(bundle,bundle.metadata.get("execution_evidence_ids")):
            put("DE-E",None,"8/10には時刻付き約定環境の直接根拠が必要",[])
        if not valid_refs(bundle,bundle.metadata.get("same_time_volume_evidence_ids")):
            put("DT-B",None,"累積出来高の同時刻比較根拠が不足",[])
    if plan is None:
        for k in h["entry_weights"]: put(h["entry_prefix"]+"-"+k,None,"有効な価格プランが未算出",[])
    elif plan.kind!="現値":
        for k in h["entry_weights"]: put(h["entry_prefix"]+"-"+k,None,"候補到達時の価格・トリガー・イベント条件は未確認",[])
    ip=h["prefix"]+"-";ep=h["entry_prefix"]+"-"
    ic=[ip+k for k in h["investment_weights"]]
    ec=[ep+k for k in h["entry_weights"]]
    cc=[h["context_prefix"]+"-"+str(i) for i in range(1,h["context_count"]+1)]
    def average(codes,weights):
        values=[items.get(c,{}).get("score") for c in codes]
        return None if any(v is None for v in values) else sum(v*w for v,w in zip(values,weights))/sum(weights)
    structured=average(ic,h["investment_weights"].values())
    context=average(cc,[1]*len(cc))
    investment=None if structured is None or context is None else .7*structured+.3*context
    entry=average(ec,h["entry_weights"].values())
    missing=[c for c in ic+cc+ec if items.get(c,{}).get("score") is None]
    return ScoreResult(structured,context,investment,entry,
        EvaluationStatus.EVALUABLE if investment is not None else EvaluationStatus.PROVISIONAL,
        EvaluationStatus.EVALUABLE if entry is not None else EvaluationStatus.PROVISIONAL,items,missing,
        sum(w for c,w in zip(ic,h["investment_weights"].values()) if items.get(c,{}).get("score") is not None)/100)

def analyze_horizon(bundle,cfg,horizon,earnings_policy="unspecified",specified_entry=None):
    if horizon not in ("midlong","daytrade"): raise InputError("時間軸が不正です。")
    bundle=copy.deepcopy(bundle)
    cfg=copy.deepcopy(cfg);cfg["horizon"]=horizon
    cfg["horizon_rules"]=settings();cfg["all_card_hash"]=digest(all_cards())
    cfg["config_version"]=settings()["version"]+":"+horizon
    tech=horizon_technical(bundle,cfg,horizon)
    findings=preflight(bundle,None if horizon=="daytrade" else tech["weekly_count"])
    def finding(code,severity,scope,reason,refs=()):
        findings.append(Finding(code,severity,scope,reason,tuple(refs)))
    if horizon=="midlong":
        financial=bundle.metadata.get("latest_financial",{})
        if not financial.get("latest_confirmed") or not financial.get("period") or not valid_refs(bundle,financial.get("evidence_ids")):
            finding("financial_missing",Severity.CRITICAL,"investment","最新の公式決算等（対象期・根拠付き）の確認が必要")
    else:
        if not tech.get("intraday_count"):
            finding("intraday_missing",Severity.CRITICAL,"all","当日の確定5分足がありません。前日値で正式な当日評価はしません。")
        else:
            age=tech["intraday_age_minutes"]
            if age>settings()["day_provisional_minutes"]:
                finding("intraday_stale",Severity.WARNING,"all","当日値が15分超古いため暫定評価")
            elif age>settings()["day_fresh_minutes"]:
                finding("intraday_delay",Severity.WARNING,"decision","当日値に5〜15分の遅延あり。執行前に再確認")
        material_refs=bundle.metadata.get("today_material_evidence_ids")
        if not valid_refs(bundle,material_refs) or any(time_value(bundle.evidence[r].observed_at).astimezone(JST).date()!=time_value(bundle.as_of).astimezone(JST).date() for r in material_refs):
            finding("material_missing",Severity.CRITICAL,"investment","最新当日材料の確認根拠が不足")
        local=time_value(bundle.as_of).astimezone(JST)
        if local.time()>=time(15,30) or local.time()<time(9):
            finding("outside_session",Severity.WARNING,"decision","取引時間外の振り返り表示。翌営業日のEntryには使えません。")
    if not tech["tick_valid"]: finding("tick_missing",Severity.CRITICAL,"entry","根拠付き呼値が不足")
    if horizon=="midlong":
        from .valuation import valuation_bands
        from decimal import Decimal
        price=Decimal(str(specified_entry if specified_entry is not None else tech["latest"]))
        if not any(b.strength>=cfg["strong_band"] and Decimal(str(b.low))>price for b in tech["bands"]):
            alternatives=[b for b in valuation_bands(bundle,cfg["strong_band"]) if Decimal(str(b.low))>price]
            tech["bands"]+=alternatives
            if alternatives: finding("valuation_target",Severity.WARNING,"entry","過去抵抗がないため根拠付き評価レンジを代替利確候補に使用。達成前提を確認。",tuple(r for b in alternatives for r in b.evidence_ids))
    plans=plans_for(bundle,tech,cfg,specified_entry)
    if horizon=="daytrade":
        expiry=datetime.combine(time_value(bundle.as_of).astimezone(JST).date(),time(15,30),JST).isoformat()
        plans=[replace(p,expires_at=expiry) for p in plans]
    if not plans: finding("plan_missing",Severity.CRITICAL,"entry","実支持帯と実抵抗帯による有効な価格プランが不足")
    earnings=earnings_info(bundle,earnings_policy)
    if not earnings["scheduled_at"]: finding("earnings_missing",Severity.WARNING,"decision","決算予定未確認。イベント条件を補完してください。")
    scores={};decisions={}
    for plan in plans or [None]:
        s=score_horizon(bundle,tech,plan,cfg,horizon)
        if any(f.severity==Severity.CRITICAL and f.scope in ("all","investment") for f in findings):
            s.investment=s.structured=s.context=None;s.status=EvaluationStatus.UNAVAILABLE
        if any(f.severity==Severity.CRITICAL and f.scope in ("all","entry") for f in findings):
            s.entry=None;s.entry_status=EvaluationStatus.UNAVAILABLE
        quality=confidence(bundle,findings,s.items,horizon_cards(horizon))
        constrained=any(x["present"] and x["F"]<1 for x in quality["items"])
        if constrained and not any(f.code=="evidence_freshness" for f in findings):
            finding("evidence_freshness",Severity.WARNING,"decision","期限外または鮮度未確認のEvidenceあり")
        if constrained or any(f.code in ("stale_prices","intraday_stale","outside_session") for f in findings):
            if s.status!=EvaluationStatus.UNAVAILABLE: s.status=EvaluationStatus.PROVISIONAL
            if s.entry_status!=EvaluationStatus.UNAVAILABLE: s.entry_status=EvaluationStatus.PROVISIONAL
        kind=plan.kind if plan else "未算出";scores[kind]=s
        for scenario in earnings["scenarios"]:
            decisions[kind+":"+scenario]=decide(bundle,s,plan,findings,cfg,scenario,horizon)
    snapshot={}
    for k,v in tech.items():
        if isinstance(v,pd.DataFrame):
            table=v.reset_index();table[table.columns[0]]=table.iloc[:,0].astype(str)
            snapshot[k]=plain(table.to_dict("records"))
        else: snapshot[k]=plain(v)
    snapshot["macro"]=macro_chain(bundle)
    r=AnalysisResult(str(uuid.uuid4()),bundle.bundle_id,bundle.as_of,bundle.symbol,bundle.name,
        cfg["config_version"],digest(cfg),plain(bundle.evidence),snapshot,plans,scores,decisions,earnings,
        confidence(bundle,findings,next(iter(scores.values())).items,horizon_cards(horizon)),
        {"horizon":horizon,"is_demo":bool(bundle.metadata.get("is_demo")),"exit_conditions":bundle.metadata.get("exit_conditions",[]),
         "input_digest":digest(bundle),"source_mode":bundle.metadata.get("price_source","manual"),
         "model_version":"evidence-card-evaluation","card_version":"cards-1.0.0"},findings)
    r.approval_hash=digest(r)
    return r,bundle,cfg
