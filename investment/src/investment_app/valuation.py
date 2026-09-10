"""Optional, evidence-backed mid-long valuation targets; no fitted stop prices."""
from decimal import Decimal,InvalidOperation
from .models import Evidence,Band,InputError,digest,time_value

def valuation_bands(bundle,minimum_strength):
    value=bundle.metadata.get("valuation_plan",{})
    if not value: return []
    required=("eps","multiple_first","period","assumptions","evidence_ids")
    if not isinstance(value,dict) or any(not value.get(k) for k in required) or value.get("currency")!="JPY" or value.get("formula")!="EPS*PE" or not value.get("sector_suitable_confirmed"):
        raise InputError("評価レンジにはEPS×PER、JPY、対象期、前提、業種適合確認、Evidenceが必要です。")
    refs=value["evidence_ids"]
    if not isinstance(refs,list) or not refs or any(r not in bundle.evidence for r in refs):
        raise InputError("評価レンジのEvidenceが不足しています。")
    try:
        eps=Decimal(str(value["eps"]));multiple=Decimal(str(value["multiple_first"]))
        final=Decimal(str(value["multiple_final"])) if value.get("multiple_final") else None
        if not eps.is_finite() or not multiple.is_finite() or eps<=0 or multiple<=0 or (final is not None and (not final.is_finite() or final<multiple)):
            raise ValueError()
    except (ValueError,InvalidOperation) as exc: raise InputError("EPS・PERは正数。赤字にPER式は使えません。最終倍率は第1倍率以上です。") from exc
    targets=[eps*multiple]+([eps*final] if final is not None and final>multiple else [])
    tid="valuation-"+digest(value)[:16]
    observed=max((bundle.evidence[r].observed_at for r in refs),key=time_value)
    bundle.evidence[tid]=Evidence(tid,"中長期評価レンジ計算","local:valuation",observed,observed,bundle.as_of,
        f"EPS {eps} × 適合PER {multiple} / {value['period']} / {value['assumptions']}",digest(value),"calculation",1,tuple(refs))
    # Strength here is solely admission to the fallback target list, never a support strength.
    return [Band(digest([tid,str(t)])[:16],float(t),float(t),minimum_strength,("valuation_target",),(tid,),False,0) for t in targets]
