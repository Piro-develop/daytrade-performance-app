"""Independent horizon scoring and structural price plans."""
from __future__ import annotations
import copy
import json
import uuid
import pandas as pd
from .config import PROJECT
from .models import *
from .technical import compute, pivots, cluster_levels, number
from .entry_exit import plans_for
from .scoring import checked_manual, interpolate, macro_chain
from .preflight import preflight, confidence
from .decision import decide
from .application import earnings_info

def settings():
    return json.loads((PROJECT/"config/horizons.json").read_text(encoding="utf-8"))

def all_cards():
    return {k:v for k,v in json.loads((PROJECT/"config/all_scoring_cards.json").read_text(encoding="utf-8"))["cards"].items() if k.startswith(("SW-","SE-","SC-","ML-","ME-","MC-"))}

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
    if horizon!="midlong": raise InputError("対象はスイングと中長期のみです。")
    tech=compute(bundle,cfg)
    tid=tech["technical_evidence_id"]
    monthly=monthly_bars(tech["daily"],bundle.as_of) if bundle.metadata.get("include_monthly") else tech["daily"].iloc[:0]
    tech["monthly"]=monthly
    # Weekly/monthly actual structure controls exits. Daily indicators remain timing only.
    levels=[x for x in tech["levels"] if x["timeframe"]=="1w" and x["family"]=="price_structure"]
    levels+=structure_levels(monthly.tail(60),"1mo",tid,cfg)
    tech["atr"]=number(tech["weekly"].iloc[-1].atr) if len(tech["weekly"]) else None
    tech["levels"]=levels
    config=copy.deepcopy(cfg);config["timeframe_weights"]["1mo"]=4
    tech["bands"]=cluster_levels(levels,tech["weekly"],tech["atr"],float(bundle.metadata.get("tick_size") or 1),config) if tech["tick_valid"] else []
    return tech

def score_horizon(bundle,tech,plan,cfg,horizon):
    h=settings()[horizon];cards=horizon_cards(horizon)
    items=checked_manual(bundle,cards)
    def put(code,value,reason,refs):
        items[code]={"score":value,"reason":reason,"counter_reason":"主要な反証・価格構造を別途確認","evidence_ids":list(refs),
                     "evaluator":"program","rule_version":"cards-1.0.0","purpose":cards[code]["label"]}
    macro=macro_chain(bundle)
    if not macro["valid"]:
        for code in ("ML-G",):
            put(code,None,"セクター→地合い→ドライバー→企業感応度→個別比較の根拠不足",[])
    if not bundle.metadata.get("earnings_at"):
        put("ME-G",None,"直近の決算予定が未確認",[])
    if tech["weekly_count"]<cfg["weekly_min"]:
        for code in ("ML-I","ME-A"):
            put(code,None,"長期構造に必要な確定週足58本が不足",[])
    if plan:
        stress=items.get("ME-E-STRESS",{}).get("score")
        refs=list(plan.evidence_ids)+items.get("ME-E-STRESS",{}).get("evidence_ids",[])
        put("ME-E",None if stress is None else (interpolate(plan.rr,cfg["rr_knots"])+stress)/2,
            f"RR={plan.rr}の補間とストレス評価={stress}を等重み集約",refs)
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
    if horizon!="midlong": raise InputError("時間軸が不正です。")
    bundle=copy.deepcopy(bundle)
    cfg=copy.deepcopy(cfg);cfg["horizon"]=horizon
    cfg["horizon_rules"]=settings();cfg["all_card_hash"]=digest(all_cards())
    cfg["config_version"]=settings()["version"]+":"+horizon
    tech=horizon_technical(bundle,cfg,horizon)
    findings=preflight(bundle,tech["weekly_count"])
    def finding(code,severity,scope,reason,refs=()):
        findings.append(Finding(code,severity,scope,reason,tuple(refs)))
    financial=bundle.metadata.get("latest_financial",{})
    if not financial.get("latest_confirmed") or not financial.get("period") or not valid_refs(bundle,financial.get("evidence_ids")):
        finding("financial_missing",Severity.CRITICAL,"investment","最新の公式決算等（対象期・根拠付き）の確認が必要")
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
        if constrained or any(f.code in ("stale_prices",) for f in findings):
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
