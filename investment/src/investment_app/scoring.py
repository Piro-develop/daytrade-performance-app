"""Fixed card anchors and objective interpolation; no autonomous numeric guesses."""
from __future__ import annotations
import json
import math
import numpy as np
from .config import PROJECT
from .models import Bundle, EntryPlan, EvaluationStatus, ScoreResult

def catalog():
    return json.loads((PROJECT / "config/scoring_cards.json").read_text(encoding="utf-8"))["cards"]

def interpolate(x, knots):
    return float(np.interp(float(x), [p[0] for p in knots], [p[1] for p in knots]))

def checked_manual(bundle: Bundle, cards=None) -> dict:
    cards = catalog() if cards is None else cards
    result = {}
    seen=set()
    for item in bundle.metadata.get("assessments", []):
        code = item.get("criterion_id")
        if code not in cards:
            continue
        refs = item.get("evidence_ids", [])
        valid = (item.get("anchor") in [1,4,6,8,10] and not isinstance(item.get("anchor"),bool)
                 and refs and all(r in bundle.evidence for r in refs)
                 and bool(str(item.get("reason","")).strip())
                 and bool(str(item.get("counter_reason","")).strip())
                 and item.get("rule_version") == "cards-1.0.0")
        if code in seen:
            valid = False
        seen.add(code)
        result[code] = {"score":float(item["anchor"]) if valid else None,
            "reason":item.get("reason",""),"counter_reason":item.get("counter_reason",""),
            "evidence_ids":refs if valid else [],"evaluator":item.get("evaluator","human"),
            "rule_version":item.get("rule_version"),"purpose":cards[code]["label"],
            "error":None if valid else "アンカー・根拠・理由・規則版を確認してください"}
    return result

def macro_chain(bundle: Bundle) -> dict:
    macro = bundle.metadata.get("macro", {})
    required = ["sector","sector_condition","drivers","company_sensitivity","specific_factors","dominant_force"]
    valid = (all(macro.get(k) for k in required) and macro.get("evidence_ids")
             and all(r in bundle.evidence for r in macro.get("evidence_ids",[])))
    return dict(macro, valid=bool(valid))

def investment_items(bundle: Bundle, technical: dict, cfg: dict) -> dict:
    items = {k:v for k,v in checked_manual(bundle).items() if not k.startswith("SE-")}
    from .automatic_assessment import technical_assessments
    for code,item in technical_assessments(bundle,technical,cfg,"swing").items():
        items.setdefault(code,item)
    tid = technical["technical_evidence_id"]
    def computed(code, score, reason):
        items[code]={"score":score,"reason":reason,"counter_reason":"数値は比較補助。材料・反証は別のカードとPreflightで確認",
                     "evidence_ids":[tid],"evaluator":"program"}
    # Weekly direction is enforced from weekly data, never inferred from a daily bounce.
    if technical["weekly_count"] >= cfg["weekly_min"]:
        trend = technical["weekly_trend"]
        weekly = technical["weekly"]
        persistent = []
        for offset in (1,2,3):
            row, previous = weekly.iloc[-offset],weekly.iloc[-offset-cfg["slope_periods"]]
            persistent.append(row.ma13>row.ma26>row.ma52 and all(row[f"ma{p}"]>previous[f"ma{p}"] for p in cfg["weekly_ma"]))
        row, old = weekly.iloc[-1], weekly.iloc[-1-cfg["slope_periods"]]
        slopes=[row[f"ma{p}"]-old[f"ma{p}"] for p in cfg["weekly_ma"]]
        down_all=row.ma13<row.ma26<row.ma52 and all(x<0 for x in slopes)
        value=10 if all(persistent) else 1 if down_all else 8 if sum(x>0 for x in slopes)>=2 else 4 if sum(x<0 for x in slopes)>=2 else 6
        computed("SW-D1",value,f"確定週足{technical['weekly_count']}本、13/26/52週線の大局={trend}")
    else:
        computed("SW-D1",None,"52週線・傾き・継続確認に必要な58週の履歴が不足")
    ps=technical["pivots"].get("1w",[])
    highs=[p["price"] for p in ps if p["kind"]=="high"]
    lows=[p["price"] for p in ps if p["kind"]=="low"]
    if len(highs)>=2 and len(lows)>=2:
        up=highs[-1]>highs[-2] and lows[-1]>lows[-2]
        down=highs[-1]<highs[-2] and lows[-1]<lows[-2]
        repeated_up=up and len(highs)>=3 and len(lows)>=3 and highs[-2]>highs[-3] and lows[-2]>lows[-3]
        repeated_down=down and len(highs)>=3 and len(lows)>=3 and highs[-2]<highs[-3] and lows[-2]<lows[-3]
        computed("SW-D2",10 if repeated_up else 1 if repeated_down else 8 if up else 4 if down else 6,
                 f"確定週足の直近高値{highs[-2:]}、安値{lows[-2:]}を比較")
    else:
        computed("SW-D2",None,"週足の確定高安比較に必要なpivotが不足")
    # P02: missing event evidence invalidates its cards, not unrelated components.
    from .application import earnings_info
    if earnings_info(bundle,"unspecified")["state"]=="unknown":
        computed("SW-H",None,"次回決算予定が未確認のため、イベント合理性は未評価")
    if not macro_chain(bundle)["valid"]:
        computed("SW-F",None,"セクター→ドライバー→企業感応度→個別比較のEvidenceが不足")
        computed("SC-4",None,"支配関係の解釈に必要なマクロ経路が不足")
    return items

def weighted_available(items, weights):
    available={code:weight for code,weight in weights.items() if items.get(code,{}).get("score") is not None}
    covered=sum(available.values());total=sum(weights.values())
    value=sum(items[code]["score"]*weight for code,weight in available.items())/covered if covered else None
    return value,covered/total if total else 0.0,[code for code in weights if code not in available]


def coverage_status(value,coverage,cfg):
    return EvaluationStatus.EVALUABLE if value is not None and coverage>=cfg["coverage_normal"] else EvaluationStatus.PROVISIONAL


def aggregate_investment(items: dict, cfg: dict):
    # Flatten subcard weights: a 20%-axis / 25%-subcard retains 5% of the original total.
    weights={}
    for axis,weight in cfg["investment_weights"].items():
        if axis in cfg["subweights"]:
            weights.update({f"SW-{axis}{i}":weight*sub/100 for i,sub in enumerate(cfg["subweights"][axis],1)})
        else: weights[f"SW-{axis}"]=weight
    structured,coverage,missing=weighted_available(items,weights)
    context,_,_=weighted_available(items,{f"SC-{i}":1 for i in range(1,7)})
    investment=structured if coverage+1e-12>=cfg["coverage_min"] else None
    return structured,context,investment,missing,coverage


def entry_items(bundle: Bundle, tech: dict, plan: EntryPlan, cfg: dict, manual: dict) -> dict:
    tid=tech["technical_evidence_id"]
    out={k:v for k,v in manual.items() if k.startswith("SE-")}
    def set_score(code,score,reason):
        out[code]={"score":score,"reason":reason,"counter_reason":"価格構造は将来の約定を保証しない",
                   "evidence_ids":list(plan.evidence_ids),"evaluator":"program"}
    from .application import earnings_info
    if earnings_info(bundle,"unspecified")["state"]=="unknown":
        set_score("SE-G",None,"次回決算予定が未確認のため、直近タイミングは未評価")
    upside=float((plan.target1-plan.entry)/plan.entry*100)
    set_score("SE-A",interpolate(upside,cfg["upside_knots"]),f"第1利確までの余地 {upside:.4f}%")
    set_score("SE-C",interpolate(plan.rr,cfg["rr_knots"]),f"第1利確・第1損切によるRR {plan.rr}")
    band=next((b for b in tech["bands"] if b.band_id==plan.support_id),None)
    atr=tech["atr"]
    if band and atr:
        distance=float(plan.entry-plan.stop1)/atr
        tight, medium, wide=cfg["support_distance_atr"]
        value=10 if band.primary and len(band.families)>=2 and distance<=tight else 8 if distance<=medium else 6 if distance<=wide else 4
        set_score("SE-B",value,f"支持帯強度{band.strength:.2f}、損切距離/ATR={distance:.3f}")
    else:
        set_score("SE-B",None,"支持帯またはATRの根拠不足")
    if plan.kind!="現値":
        set_score("SE-D",6,"価格到達・反転は未確認。候補価格の評価であり現値の買い指示ではない")
    else:
        value=8 if plan.trigger_confirmed else 6
        if tech["rsi"] is not None and tech["rsi"]>=cfg.get("rsi_overheated",75):
            value=min(value,4)
        set_score("SE-D",value,f"確定日足トリガー={plan.trigger_confirmed}、RSI={tech['rsi']}")
    weekly_prices=[x["low"] for x in tech["levels"] if x["timeframe"]=="1w"]
    if weekly_prices and atr:
        supports=[x for x in weekly_prices if x<float(plan.entry)]
        resistances=[x for x in weekly_prices if x>float(plan.entry)]
        near_support=bool(supports and float(plan.entry)-max(supports)<=2*atr)
        near_resistance=bool(resistances and min(resistances)-float(plan.entry)<=2*atr)
        set_score("SE-E",4 if near_resistance else 10 if near_support and tech["weekly_trend"]=="上昇" and band and band.primary else 8 if near_support else 6,
                  f"週足上の位置：支持近接={near_support}、抵抗近接={near_resistance}。方向得点とは別")
    else:
        set_score("SE-E",None,"週足上の位置を確認できません")
    ratio=tech["volume_ratio"]
    if plan.kind=="現値" and ratio is not None:
        set_score("SE-F",8 if plan.trigger_confirmed and ratio>=cfg["volume_trigger_ratio"] else 6 if ratio>=1 else 4,
                  f"直前20日平均に対する確定日足出来高={ratio:.3f}倍")
    else:
        # Conditional future setups cannot pretend volume has already confirmed.
        set_score("SE-F",None,"候補Entry時の出来高は未確認")
    return out

def score(bundle: Bundle, tech: dict, plan: EntryPlan | None, cfg: dict) -> ScoreResult:
    items=investment_items(bundle,tech,cfg)
    structured,context,total,missing,coverage=aggregate_investment(items,cfg)
    entry=None;entry_coverage=0.0
    if plan is not None:
        entries=entry_items(bundle,tech,plan,cfg,checked_manual(bundle))
        items.update(entries)
        value,entry_coverage,emissing=weighted_available(entries,{f"SE-{k}":w for k,w in cfg["entry_weights"].items()})
        if entry_coverage+1e-12>=cfg["coverage_min"]: entry=value
        missing+=emissing
    else:
        missing += [f"SE-{k}" for k in cfg["entry_weights"]]
    return ScoreResult(structured,context,total,entry,
        coverage_status(total,coverage,cfg),coverage_status(entry,entry_coverage,cfg),items,missing,coverage,entry_coverage)
