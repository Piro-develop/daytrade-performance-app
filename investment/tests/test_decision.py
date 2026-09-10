from dataclasses import replace
from decimal import Decimal
import pytest
from investment_app.config import load_config
from investment_app.models import Bundle, Evidence, Finding, ScoreResult, EvaluationStatus, Severity
from investment_app.entry_exit import make_plan
from investment_app.decision import decide
from investment_app.scoring import aggregate_investment

ASOF="2026-09-09T16:00:00+09:00"

def inputs(inv=8,entry=3,rrstop=950,target=1100):
    ev=Evidence("e","source","local:e",ASOF,ASOF,ASOF,"reviewed","hash")
    bundle=Bundle("TEST","name",ASOF,[],{"e":ev},{"exit_conditions":["thesis"]})
    scores=ScoreResult(inv,inv,inv,entry,EvaluationStatus.EVALUABLE,EvaluationStatus.EVALUABLE,{},[],1)
    plan=make_plan(1000,target,rrstop,evidence_ids=("e",),expires_at="2026-09-10T16:00:00+09:00",trigger_confirmed=True)
    return bundle,scores,plan

def test_high_investment_low_entry_waits():
    b,s,p=inputs()
    assert decide(b,s,p,[],load_config(),"allow").label=="押し目待ち"

def test_critical_never_cancelled_by_scores():
    b,s,p=inputs(10,10)
    result=decide(b,s,p,[Finding("critical",Severity.CRITICAL,"all","invalid")],load_config(),"allow")
    assert result.status==EvaluationStatus.UNAVAILABLE
    assert result.label is None

def test_severe_not_automatic_buy_or_rejection():
    b,s,p=inputs(10,10)
    result=decide(b,s,p,[Finding("severe",Severity.SEVERE,"decision","accounting")],load_config(),"allow")
    assert result.label=="Severe警告付き条件判断"
    assert result.approval_required
    assert not result.approval_eligible

def test_missing_score_is_not_zero_or_reject():
    b,s,p=inputs()
    s.investment=None
    result=decide(b,s,p,[],load_config(),"allow")
    assert result.status==EvaluationStatus.PROVISIONAL
    assert result.label is None
    assert aggregate_investment({},load_config())[2] is None

def test_rr_between_15_and_2_can_be_conditional():
    b,s,p=inputs(8,8,950,1085)
    assert p.rr==Decimal("1.7")
    assert decide(b,s,p,[],load_config(),"allow").label=="条件付き買い"

def test_low_rr_requires_supported_dominant_material():
    b,s,p=inputs(8,8,950,1060)
    assert decide(b,s,p,[],load_config(),"allow").label=="押し目待ち"
    b.metadata["dominant_factor"]={"direction":"positive","reason":"contract",
        "why_score_is_insufficient":"single factor","rr_rationale":"defined risk",
        "alternative_entry_reason":"may miss catalyst","invalidation":"contract loss","evidence_ids":["e"]}
    result=decide(b,s,p,[],load_config(),"allow")
    assert result.label=="条件付き買い"
    assert {x["kind"] for x in result.overrides}=={"low_rr","under7"}
    assert p.stop1==950

def test_negative_dominant_material_overrides_without_rewriting_scores():
    b,s,p=inputs(9,9)
    b.metadata["dominant_factor"]={"direction":"negative","reason":"主要契約消失",
        "why_score_is_insufficient":"集計では影響が薄まる","invalidation":"成長前提消失","evidence_ids":["e"]}
    decision=decide(b,s,p,[],load_config(),"allow")
    assert decision.label=="見送り"
    assert s.investment==9
    assert decision.overrides[0]["direction"]=="negative"

def test_warning_cannot_remain_unconditional_buy():
    b,s,p=inputs(9,9)
    warning=Finding("earnings",Severity.WARNING,"decision","決算接近",("e",),"シナリオ確認")
    out=decide(b,s,p,[warning],load_config(),"allow")
    assert out.label=="条件付き買い"
    assert warning in out.findings

def test_override_keeps_original_and_final_reason_chain():
    b,s,p=inputs(8,8,950,1060)
    b.metadata["dominant_factor"]={"direction":"positive","reason":"契約",
        "why_score_is_insufficient":"作用時期が重要","rr_rationale":"損失幅を説明",
        "alternative_entry_reason":"待つと発表を逃す","invalidation":"契約取消","evidence_ids":["e"]}
    out=decide(b,s,p,[],load_config(),"allow")
    for override in out.overrides:
        assert override["base_decision"]=="買い"
        assert override["candidate_decision"]=="条件付き買い"
        assert override["invalidation"]=="契約取消"
        assert override["why_score_is_insufficient"]
