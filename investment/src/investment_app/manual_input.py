"""Manual CSV and evidence forms. No market retrieval or free score generation."""
from io import StringIO
from datetime import datetime
import json
import pandas as pd
from .models import InputError, digest, time_value
from .scoring import catalog

AUTO_CARDS={"SW-D1","SW-D2",*[f"SE-{c}" for c in "ABCDEF"]}
ALIASES={"銘柄コード":"symbol_code","日時":"timestamp","始値":"open","高値":"high","安値":"low",
         "終値":"close","出来高":"volume","価格調整基準":"adjustment_basis","日付":"date"}

def normalize_csv(raw: bytes, symbol: str, adjustment: str, confirmed=False, close_time=None) -> tuple[bytes,dict]:
    if len(raw)>10_000_000:
        raise InputError("CSVは10MB以内です。")
    decoded=None
    for encoding in ("utf-8-sig","cp932"):
        try:
            decoded=raw.decode(encoding);break
        except UnicodeDecodeError:
            continue
    if decoded is None:
        raise InputError("UTF-8またはCP932のCSVを指定してください。")
    try:
        frame=pd.read_csv(StringIO(decoded),dtype=str,keep_default_na=False)
    except Exception as exc:
        raise InputError("CSVを読み取れません。") from exc
    frame.columns=[str(c).strip() for c in frame.columns]
    renamed=[ALIASES.get(c,c) for c in frame.columns]
    if len(set(renamed))!=len(renamed):
        raise InputError("同じ項目に対応する列が重複しています。")
    frame.columns=renamed
    changes=[]
    if "symbol_code" not in frame:
        if not confirmed or not symbol.strip():
            raise InputError("銘柄列がない場合は、選択銘柄との一致確認が必要です。")
        frame["symbol_code"]=symbol
        changes.append("銘柄列を確認済み手入力から追加")
    if "adjustment_basis" not in frame:
        if not confirmed or not adjustment.strip():
            raise InputError("価格調整基準を確認して入力してください。")
        frame["adjustment_basis"]=adjustment
        changes.append("価格調整基準を確認済み手入力から追加")
    if "timestamp" not in frame:
        if "date" not in frame or not confirmed or not close_time:
            raise InputError("日時列が必要です。日付だけの場合は全期間の確定時刻を明示してください。")
        try:
            close=datetime.strptime(close_time,"%H:%M").time()
            dates=[datetime.strptime(str(d).replace("/","-"),"%Y-%m-%d").date() for d in frame["date"]]
            frame["timestamp"]=[datetime.combine(d,close).isoformat()+"+09:00" for d in dates]
        except ValueError as exc:
            raise InputError("日付はYYYY-MM-DD、確定時刻はHH:MMです。") from exc
        changes.append("全入力期間に利用者確認済みの確定時刻 "+close_time+" JSTを適用")
    # Mandatory numeric and time validation is performed by the unchanged LocalCSVProvider.
    return frame.to_csv(index=False).encode("utf-8"),{"raw_hash":digest(raw.hex()),"encoding":encoding,
        "column_map":{c:ALIASES.get(c,c) for c in ALIASES if ALIASES[c] in frame},"changes":changes}

def csv_table(raw: bytes) -> list[dict]:
    try:
        return pd.read_csv(StringIO(raw.decode("utf-8-sig")),dtype=str,keep_default_na=False).to_dict("records")
    except Exception as exc:
        raise InputError("補足表はUTF-8 CSVで指定してください。") from exc

def refs(value):
    return [x.strip() for x in str(value or "").replace("、",",").split(",") if x.strip()]

def build_metadata(base: dict, evidence_rows: list[dict], card_rows: list[dict], cards=None) -> dict:
    result=dict(base,evidence=[],assessments=[],evidence_quality={},is_demo=False)
    seen=set()
    for row in evidence_rows:
        if not str(row.get("evidence_id","")).strip():
            continue
        eid=str(row["evidence_id"]).strip()
        if eid in seen:
            raise InputError("Evidence IDが重複しています。")
        seen.add(eid)
        original=next((e for e in base.get("evidence",[]) if e["evidence_id"]==eid),{})
        ev={**original,**{key:str(row.get(key,"")).strip() for key in
            ("evidence_id","source_name","source_uri","observed_at","published_at","fetched_at","summary")}}
        ev["evidence_id"]=eid
        ev.update(source_type=original.get("source_type","manual"),fact_or_interpretation=row.get("fact_or_interpretation") or "fact",
                  confidence=0.5)
        ev["content_hash"]=digest({k:v for k,v in ev.items() if k!="content_hash"})
        result["evidence"].append(ev)
        result["evidence_quality"][eid]={**base.get("evidence_quality",{}).get(eid,{}),"valid_until":row.get("valid_until") or None,
            "source_quality":row.get("source_quality") or "unknown"}
    cards=catalog() if cards is None else cards
    for row in card_rows:
        code=row.get("criterion_id")
        if code in AUTO_CARDS or str(row.get("anchor","")).strip() in ("","None","nan","未評価"):
            continue
        if code not in cards:
            raise InputError("存在しない採点カードです。")
        try:
            value=float(row["anchor"])
            if value not in (1,4,6,8,10):
                raise ValueError()
        except (ValueError,TypeError) as exc:
            raise InputError("アンカーは未評価または1/4/6/8/10です。") from exc
        result["assessments"].append({"criterion_id":code,"anchor":int(value),"rule_version":"cards-1.0.0",
            "evidence_ids":refs(row.get("evidence_ids")),"reason":str(row.get("reason","")).strip(),
            "counter_reason":str(row.get("counter_reason","")).strip(),"evaluator":"human"})
    return result

def card_template():
    return [{"criterion_id":code,"項目":card["label"],"anchor":"未評価","evidence_ids":"","reason":"","counter_reason":""}
            for code,card in catalog().items() if code not in AUTO_CARDS]

def readiness(bundle) -> list[dict]:
    from .preflight import preflight
    from .scoring import checked_manual
    items=checked_manual(bundle)
    checks=[{"対象":f.code,"状態":f.severity,"説明":f.reason} for f in preflight(bundle)]
    for code in catalog():
        if code in AUTO_CARDS:
            continue
        good=items.get(code,{}).get("score") is not None
        checks.append({"対象":code,"状態":"入力済み" if good else "不足","説明":catalog()[code]["evidence"]})
    if not bundle.metadata.get("tick_size") or bundle.metadata.get("tick_evidence_id") not in bundle.evidence:
        checks.append({"対象":"呼値","状態":"不足","説明":"価格プランに必要な検証済み呼値とEvidence"})
    return checks
