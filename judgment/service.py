"""Native UI adapter; the canonical investment engines are reused unchanged."""
from __future__ import annotations
import base64
import copy
from datetime import datetime,timezone
import hashlib
from io import BytesIO
from pathlib import Path
import uuid
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
    def __init__(self,directory=None,store=None,assessment_provider=None):
        self.assessment_provider=assessment_provider
        self.directory=Path(directory).resolve() if directory is not None else None
        self.store=store
    def folder(self,uid):
        if not isinstance(uid,str) or not uid: raise InputError("本人情報がありません。")
        if self.directory is None: raise InputError("本番の保存先はFirestoreです。")
        folder=self.directory/"users"/hashlib.sha256(uid.encode()).hexdigest()
        folder.mkdir(parents=True,exist_ok=True)
        return folder
    def history(self,uid):
        if self.store is not None:
            if self.store.uid!=uid: raise InputError("本人情報が一致しません。")
            return self.store
        return History(self.folder(uid)/"history.sqlite")
    def catalog(self):
        return {"cards":all_cards(),"automatic_cards":sorted(AUTO_CARDS|{"ME-E"}),
            "horizons":{"swing":"スイング","midlong":"中長期"}}
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
    def automatic(self,uid,payload):
        from .automatic import acquire
        query=str(payload.get("symbol","")).strip()
        if not query: raise InputError("日本株の銘柄名または銘柄コードを入力してください。")
        entry=str(payload.get("entry") or "").strip()
        if entry:
            import math
            try:
                if not math.isfinite(float(entry)) or float(entry)<=0: raise ValueError()
            except ValueError as exc: raise InputError("想定Entry価格は正の数値で入力してください。") from exc
        policy=payload.get("policy","unspecified")
        if policy not in {"unspecified","allow","avoid"}: raise InputError("決算方針を確認してください。")
        acquired=acquire(query);meta=acquired["metadata"];raw=acquired["csv"]
        supplement=payload.get("supplement") or {}
        if not isinstance(supplement,dict):raise InputError("補完データの形式を確認してください。")
        if raw is None and supplement.get("csv"):
            raw,_=normalize_csv(decode(supplement["csv"]),acquired["symbol"],"",False,None)
            meta["price_source"]="利用者の補完CSV"
        notes=str(supplement.get("notes","")).strip()
        if len(notes)>20000:raise InputError("補足は2万文字以内で入力してください。")
        if notes:
            stamp=meta["as_of"];eid="user-note-"+digest(notes)[:16]
            meta["evidence"].append(plain(Evidence(eid,"利用者の補足","user:note",stamp,stamp,stamp,notes,digest(notes),"manual",.5)))
        if supplement.get("image"):
            image=self.image(uid,{"image":supplement["image"],"confirmed":supplement.get("image_confirmed"),
                "source_name":"利用者の補完画像","as_of":meta["as_of"],"observed_at":supplement.get("image_observed",""),
                "published_at":meta["as_of"],"summary":notes or "利用者が目視確認した画像。数値の自動抽出・採点には未使用。"})
            meta["evidence"].append(image)
        missing=[]
        if not meta.get("tick_size"):missing.append("最新の呼値区分")
        meta["automatic"].update(current_quote=meta.get("current_quote"),sector=meta.get("macro",{}).get("sector"),
                                  entry_source="user" if entry else "public_quote",source_mode="automatic_public")
        if not raw:
            return {"results":{},"recommended":[],"status":"要確認","symbol":acquired["symbol"],"name":acquired["name"],
                    "missing":["確定日足の株価・出来高"]+missing,"notices":acquired["notices"],"saved":False}
        bundle=bundle_from_input(raw,meta,acquired["symbol"],meta["as_of"])
        from investment_app.automatic_assessment import prepare_automatic
        prepare_automatic(bundle)
        bundle.metadata["screening"]=True
        price=entry or meta.get("current_quote",{}).get("price")
        results=run_all(bundle,self.history(uid),policy,str(price) if price else None)
        missing=list(dict.fromkeys(x for r in results.values() for x in r["metadata"]["automatic"]["missing"]))
        return {"results":results,"missing":missing,"notices":acquired["notices"],"saved":True}

    def list_runs(self,uid):
        history=self.history(uid)
        rows=[]
        for row in history.list_runs(20):
            if "name" in row:
                if row.get("horizon","swing") in ("swing","midlong"): rows.append(row)
                continue
            result=history.get(row["run_id"])
            if result["metadata"].get("horizon","swing") not in ("swing","midlong"): continue
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
        if self.store is not None:
            return self.history(uid).save_image(raw,evidence,kind)
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
