from dataclasses import replace
import pytest
from investment_app.models import AnalysisResult,InputError,Finding,Severity,digest,plain
from investment_app.config import load_config
from investment_app.decision import decide
from investment_app.storage import History
from test_decision import inputs,ASOF

def saved(tmp_path):
    bundle,scores,plan=inputs(8,8)
    bundle.metadata["severe_conditions"]={"material":{"reason":"価格と反証を比較した条件判断",
        "remaining_risk":"ギャップリスク","resolution":"一次資料の追加確認","evidence_ids":["e"]}}
    findings=[Finding("material",Severity.SEVERE,"decision","重要材料",("e",),"一次資料の追加確認")]
    decision=decide(bundle,scores,plan,findings,load_config(),"allow")
    assert decision.approval_eligible
    result=AnalysisResult("r",bundle.bundle_id,ASOF,"TEST","Test","v","cfg",plain(bundle.evidence),{},
        [plan],{"現値":scores},{"現値:allow":decision},{},{},{},findings)
    result.approval_hash=digest(result)
    db=History(tmp_path/"approval.sqlite")
    db.save(result,bundle,load_config())
    return db,result

def test_explicit_approval_separate_from_original_decision(tmp_path):
    db,out=saved(tmp_path)
    before=db.get("r")
    assert db.approval_state("r","現値:allow",out.approval_hash,ASOF)=="pending"
    db.approval("r","現値:allow","approved",out.approval_hash,out.approval_hash,ASOF)
    assert db.approval_state("r","現値:allow",out.approval_hash,ASOF)=="approved"
    assert db.get("r")==before
    assert db.get("r")["decisions"]["現値:allow"]["label"]=="Severe警告付き条件判断"

def test_approval_reject_expiry_and_input_change(tmp_path):
    db,out=saved(tmp_path)
    db.approval("r","現値:allow","rejected",out.approval_hash,out.approval_hash,ASOF)
    assert db.approval_state("r","現値:allow",out.approval_hash,ASOF)=="rejected"
    assert db.approval_state("r","現値:allow","changed",ASOF)=="expired"
    with pytest.raises(InputError):
        db.approval("r","現値:allow","approved",out.approval_hash,"changed",ASOF)
    later="2026-09-11T16:00:00+09:00"
    assert db.approval_state("r","現値:allow",out.approval_hash,later)=="expired"
    with pytest.raises(InputError):
        db.approval("r","現値:allow","approved",out.approval_hash,out.approval_hash,later)

def test_no_implicit_or_cross_scenario_approval(tmp_path):
    db,out=saved(tmp_path)
    with pytest.raises(InputError):
        db.approval("r","現値:allow","pending",out.approval_hash,out.approval_hash,ASOF)
    with pytest.raises(InputError):
        db.approval("r","現値:avoid","approved",out.approval_hash,out.approval_hash,ASOF)
    assert db.approval_state("r","現値:avoid",out.approval_hash,ASOF)=="not_requested"
