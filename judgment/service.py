"""Native UI adapter; the canonical investment engines are reused unchanged."""
from __future__ import annotations
import base64
import copy
from datetime import datetime,timezone
import hashlib
from io import BytesIO
from pathlib import Path
import uuid
import pandas as pd
from PIL import Image
from investment_app.models import InputError,Evidence,plain,digest
from investment_app.manual_input import normalize_csv,AUTO_CARDS
from investment_app.horizons import all_cards
from investment_app.uat_service import bundle_from_input,run_all
from investment_app.storage import History
from investment_app.public_data import StooqMarketProvider,PublicContextProvider
from investment_app.ai_bridge import export_request,import_response

def decode(value,maximum=10_000_000):
    if not isinstance(value,str) or len(value)>maximum*4//3+8:
        raise InputError("ファイルは10MB以内です。")
    try: result=base64.b64decode(value,validate=True)
    except ValueError as exc: raise InputError("ファイルの形式が不正です。") from exc
    if len(result)>maximum: raise InputError("ファイルは10MB以内です。")
    return result

class JudgmentService:
    def __init__(self,directory):
        self.directory=Path(directory).resolve()
    def folder(self,uid):
        if not isinstance(uid,str) or not uid: raise InputError("本人情報がありません。")
        folder=self.directory/"users"/hashlib.sha256(uid.encode()).hexdigest()
        folder.mkdir(parents=True,exist_ok=True)
        return folder
    def history(self,uid):
        return History(self.folder(uid)/"history.sqlite")
    def catalog(self):
        return {"cards":all_cards(),"automatic_cards":sorted(AUTO_CARDS|{"ME-E","DE-C"}),
            "horizons":{"swing":"スイング","midlong":"中長期","daytrade":"デイトレ"}}
    def analyze(self,uid,payload):
        raw=decode(payload.get("csv",""))
        symbol=str(payload.get("symbol","")).strip()
        meta=copy.deepcopy(payload.get("metadata",{}))
        if not isinstance(meta,dict): raise InputError("補足情報はJSONオブジェクトです。")
        if meta.get("symbol") and str(meta["symbol"])!=symbol: raise InputError("補足情報の銘柄が一致しません。")
        csv,provenance=normalize_csv(raw,symbol,str(payload.get("adjustment","")),
                                    payload.get("confirmed") is True,payload.get("close_time"))
        meta.update(symbol=symbol,name=str(payload.get("name") or symbol),as_of=payload.get("as_of"),
                    input_normalization=provenance)
        # Never promote imported fixtures into real-stock analyses.
        meta["is_demo"]=bool(meta.get("is_demo",False))
        if payload.get("intraday_csv"):
            intraday=decode(payload["intraday_csv"])
            try: meta["intraday_bars"]=pd.read_csv(BytesIO(intraday)).to_dict("records")
            except Exception as exc: raise InputError("確定5分足CSVを確認してください。") from exc
        evidence=meta.get("evidence",[])
        if not isinstance(evidence,list): raise InputError("Evidenceは一覧で入力してください。")
        for ev in evidence:
            if not isinstance(ev,dict): raise InputError("Evidenceの形式が不正です。")
            ev.setdefault("content_hash",digest({k:v for k,v in ev.items() if k!="content_hash"}))
        policy=payload.get("policy","unspecified")
        if policy not in {"unspecified","allow","avoid"}: raise InputError("決算方針が不正です。")
        bundle=bundle_from_input(csv,meta,symbol,meta["as_of"])
        history=self.history(uid)
        return run_all(bundle,history,policy,str(payload.get("entry") or "").strip() or None)
    def list_runs(self,uid):
        history=self.history(uid)
        rows=[]
        for row in history.list_runs(50):
            result=history.get(row["run_id"])
            rows.append({**row,"name":result["name"],"horizon":result["metadata"].get("horizon","swing"),
                         "is_demo":result["metadata"].get("is_demo",False)})
        return rows
    def get(self,uid,run_id):
        return self.history(uid).get(run_id)
    def approve(self,uid,payload):
        history=self.history(uid)
        if payload.get("confirmed") is not True: raise InputError("重大警告と対象条件の確認が必要です。")
        result=history.get(str(payload.get("run_id","")))
        if result["metadata"].get("is_demo"): raise InputError("架空データは買い判断を承認できません。")
        action=payload.get("action")
        return history.approval(result["run_id"],str(payload.get("scenario","")),action,
             str(payload.get("target_hash","")),str(payload.get("current_hash","")),
             datetime.now(timezone.utc).isoformat(),user_id=uid)
    def approval_state(self,uid,run_id,scenario):
        history=self.history(uid);result=history.get(run_id)
        return history.approval_state(run_id,scenario,result["approval_hash"],datetime.now(timezone.utc).isoformat())
    def image(self,uid,payload):
        raw=decode(payload.get("image",""))
        if payload.get("confirmed") is not True: raise InputError("画像を目視確認してください。")
        try:
            pic=Image.open(BytesIO(raw))
            if pic.width*pic.height>25_000_000: raise ValueError()
            kind=pic.format
            if kind not in {"PNG","JPEG"}: raise ValueError()
            pic.verify()
        except Exception as exc: raise InputError("PNG／JPEG画像を確認してください。") from exc
        image_id=hashlib.sha256(raw).hexdigest()
        stamp=str(payload.get("observed_at",""));published=str(payload.get("published_at",""))
        asof=str(payload.get("as_of",""))
        evidence=Evidence("image-"+image_id[:20],str(payload.get("source_name","")),
            "attachment:"+image_id,stamp,published,datetime.now(timezone.utc).isoformat(),
            str(payload.get("summary","")),image_id,"image",.5)
        evidence.validate(asof)
        folder=self.folder(uid)/"attachments";folder.mkdir(exist_ok=True)
        path=folder/(image_id+(".png" if kind=="PNG" else ".jpg"))
        if not path.exists():
            temporary=folder/(uuid.uuid4().hex+".tmp")
            temporary.write_bytes(raw);temporary.replace(path)
        return plain(evidence)
    def public(self,payload):
        source=payload.get("source")
        if source=="stooq":
            out=StooqMarketProvider().fetch(str(payload.get("symbol","")),
                str(payload.get("start","")),str(payload.get("end","")))
            out["csv"]=base64.b64encode(out["csv"]).decode()
            return out
        if source not in {"ecb","fed"}: raise InputError("取得先が不正です。")
        return PublicContextProvider().fetch(source)
    def ai(self,payload):
        metadata=payload.get("metadata",{})
        evidence={e["evidence_id"]:e for e in metadata.get("evidence",[])}
        request=export_request(metadata.get("symbol",""),metadata.get("as_of",""),evidence,payload.get("selected",[]))
        if payload.get("response") is not None:
            return {"assessments":import_response(payload["response"],request)}
        return request
