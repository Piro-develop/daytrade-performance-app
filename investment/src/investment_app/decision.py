"""Final decisions are gated by evidence, scenario, warnings and user approval."""
from __future__ import annotations
from decimal import Decimal
from .models import Bundle, Decision, EntryPlan, EvaluationStatus, Finding, ScoreResult, Severity

def dominant_material(bundle: Bundle) -> dict | None:
    factor=bundle.metadata.get("dominant_factor",{})
    refs=factor.get("evidence_ids",[])
    valid=(factor.get("direction") in {"positive","negative"} and factor.get("reason")
           and factor.get("why_score_is_insufficient") and factor.get("invalidation")
           and refs and all(x in bundle.evidence for x in refs))
    return factor if valid else None

def decide(bundle: Bundle, scores: ScoreResult, plan: EntryPlan | None, findings: list[Finding],
           cfg: dict, earnings_scenario: str, horizon: str = 'swing') -> Decision:
    refs=sorted({r for item in scores.items.values() for r in item.get("evidence_ids",[])})
    buy=[item["reason"] for code,item in scores.items.items()
         if code in {"SW-A1","SW-B","SW-C","ML-A","ML-C","ML-E","DT-A","DT-C","DT-E"} and item.get("score") is not None and item["score"]>=7][:3]
    waits=[]
    critical=any(f.severity==Severity.CRITICAL for f in findings)
    severe=[f for f in findings if f.severity==Severity.SEVERE]
    if critical or plan is None:
        return Decision(None,EvaluationStatus.UNAVAILABLE,None,buy,
            ["必須の根拠・価格プランを確認して再評価してください。"],findings,[],refs)
    # Scope-qualified severe conditions remain visible, including while scores are incomplete.
    if scores.investment is None or scores.entry is None:
        return Decision("Severe警告付き条件判断" if severe else None,EvaluationStatus.PROVISIONAL,None,buy,
            ["投資妙味またはEntryの評価済み配点が60%未満です。成立している側のスコアは保持しています。"],findings,[],refs,bool(severe),False)
    provisional=(scores.status!=EvaluationStatus.EVALUABLE or scores.entry_status!=EvaluationStatus.EVALUABLE
        or any(f.code in ("stale_prices","evidence_freshness","earnings_missing") or f.code.startswith("unchecked_") for f in findings))
    status=EvaluationStatus.PROVISIONAL if provisional else EvaluationStatus.EVALUABLE
    inv,entry=scores.investment,scores.entry
    overrides=[]
    material=dominant_material(bundle)
    positive=bool(material and material["direction"]=="positive")
    reasons=[]
    candidate="買い" if inv>=7 and entry>=7 else "条件付き買い" if inv>=5 and entry>=7 else "打診買い" if inv>=5 and entry>=5 else "押し目待ち" if inv>=7 else "見送り"
    base_decision=candidate
    if inv<5:
        reasons.append("投資妙味の根拠が弱く、現在の投資前提を再検討")
    elif inv>=7 and entry<5:
        reasons.append("保有する価値は高い一方、現在のEntry品質が不足")
        candidate="押し目待ち"
    if plan.kind!="現値":
        candidate="押し目待ち"
        reasons.append("想定価格の到達と反転・出来高の確認が必要")
    low_rr=plan.rr < Decimal(str(cfg["rr_conditional"]))
    conditional_rr=Decimal(str(cfg["rr_conditional"])) <= plan.rr < Decimal(str(cfg["rr_good"]))
    under7=horizon=="swing" and (plan.target1-plan.entry)/plan.entry < Decimal(str(cfg["under7"]))
    rr_ok_reason=bool(positive and material.get("rr_rationale") and material.get("alternative_entry_reason"))
    if low_rr:
        candidate="押し目待ち"
        reasons.append("RR1.5未満。損切を動かさずEntry改善を検討")
        if positive and rr_ok_reason and plan.kind=="現値":
            candidate="条件付き買い"
            overrides.append({"kind":"low_rr","reason":material["reason"],"rr_rationale":material["rr_rationale"],
                "evidence_ids":material["evidence_ids"],"plan_id":plan.plan_id})
    elif conditional_rr and candidate in {"買い","強気買い","打診買い"}:
        candidate="条件付き買い"
        reasons.append("RR1.5以上2.0未満。損失条件と待つ代替を確認")
    if under7:
        candidate="押し目待ち"
        reasons.append("第1利確まで7%未満。原則として押し目を待つ")
        if positive and rr_ok_reason and plan.kind=="現値":
            candidate="条件付き買い"
            overrides.append({"kind":"under7","reason":material["reason"],"rr_rationale":material["rr_rationale"],
                "evidence_ids":material["evidence_ids"],"plan_id":plan.plan_id})
    if not under7 and not low_rr and positive and inv>=5 and plan.trigger_confirmed and plan.kind=="現値":
        candidate="条件付き買い"
        overrides.append({"kind":"dominant","reason":material["reason"],
            "why_score_is_insufficient":material["why_score_is_insufficient"],
            "evidence_ids":material["evidence_ids"],"plan_id":plan.plan_id})
    if candidate in {"買い","強気買い","条件付き買い","打診買い"} and not plan.trigger_confirmed:
        candidate="反転確認"
        reasons.append("確定足のEntryトリガーを待つ")
    if material and material["direction"]=="negative":
        candidate="見送り"
        overrides.append({"kind":"dominant","direction":"negative","reason":material["reason"],
            "why_score_is_insufficient":material["why_score_is_insufficient"],
            "evidence_ids":material["evidence_ids"],"plan_id":plan.plan_id})
        reasons.insert(0,"支配的な悪材料により投資前提を再評価："+material["reason"])
    if any(f.severity==Severity.WARNING for f in findings) and candidate in {"買い","強気買い","打診買い"}:
        candidate="条件付き買い"
        reasons.append("Warningの確認・解消条件を満たすことが必要")
    if provisional:
        if candidate in {"買い","強気買い","打診買い"}: candidate="条件付き買い"
        reasons.insert(0,"暫定評価。coverage・未確認情報・鮮度の制約を確認してください。")
    for override in overrides:
        override.update({"direction":material["direction"],"base_decision":base_decision,
            "candidate_decision":candidate,"scope":horizon+":"+earnings_scenario,
            "why_score_is_insufficient":material["why_score_is_insufficient"],
            "invalidation":material["invalidation"],
            "alternative_entry_reason":material.get("alternative_entry_reason")})
    if earnings_scenario=="avoid" and bundle.metadata.get("earnings_at"):
        reasons.append("決算跨ぎ回避：発表前にプランを再評価（注文は行わない）")
    if earnings_scenario=="allow":
        reasons.append("決算跨ぎ想定：ギャップと前提変化を確認")
    waits=(reasons+[f.reason for f in findings if f.severity!=Severity.CRITICAL])[:3]
    if not waits:
        waits=["支持割れ・材料失効時は再評価"]
    refs=sorted(set(refs+[r for o in overrides for r in o["evidence_ids"]]+[r for f in findings for r in f.evidence_ids]))
    if severe:
        approvals=bundle.metadata.get("severe_conditions",{})
        complete=all(approvals.get(f.code,{}).get("reason") and approvals.get(f.code,{}).get("remaining_risk")
                     and approvals.get(f.code,{}).get("evidence_ids")
                     and all(r in bundle.evidence for r in approvals[f.code]["evidence_ids"]) for f in severe)
        for finding in severe:
            condition=approvals.get(finding.code,{})
            condition_refs=[r for r in condition.get("evidence_ids",[]) if r in bundle.evidence]
            refs=sorted(set(refs+condition_refs))
            overrides.append({"kind":"severe_condition","finding_code":finding.code,
                "reason":condition.get("reason"),"remaining_risk":condition.get("remaining_risk"),
                "resolution":condition.get("resolution",finding.resolution),"evidence_ids":condition_refs,
                "base_decision":base_decision,"candidate_decision":candidate,"plan_id":plan.plan_id,
                "scope":horizon+":"+earnings_scenario})
        eligible=complete and candidate in {"買い","条件付き買い","打診買い"}
        return Decision("Severe警告付き条件判断",status,candidate,buy,waits,findings,overrides,refs,True,eligible)
    return Decision(candidate,status,candidate,buy,waits,findings,overrides,refs)
