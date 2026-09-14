"""Stateless Firestore REST adapter, authenticated by the requesting Firebase user."""
from __future__ import annotations
import base64
from dataclasses import replace
from datetime import datetime,timezone
import gzip
import hashlib
import json
import re
import uuid
from urllib.parse import quote
import zlib
import requests
from investment_app.models import InputError,canonical,plain,time_value
from investment_app.storage import validate_approval

CHUNK=450_000
MAX_COMMIT=8_500_000
MAX_RAW=32_000_000

def fields(values):
    out={}
    for key,value in values.items():
        kind="booleanValue" if isinstance(value,bool) else "integerValue" if isinstance(value,int) else "bytesValue" if isinstance(value,bytes) else "stringValue"
        out[key]={kind:base64.b64encode(value).decode() if kind=="bytesValue" else str(value) if kind=="integerValue" else value}
    return out

def unpack(document):
    out={}
    for key,value in document.get("fields",{}).items():
        if "bytesValue" in value: out[key]=base64.b64decode(value["bytesValue"],validate=True)
        elif "integerValue" in value: out[key]=int(value["integerValue"])
        elif "booleanValue" in value: out[key]=value["booleanValue"]
        else: out[key]=value.get("stringValue")
    return out

class FirestoreHistory:
    def __init__(self,project,uid,token,transport=None):
        if not re.fullmatch(r"[a-z][a-z0-9-]{4,62}",project): raise InputError("Firebaseプロジェクトが不正です。")
        if not uid or "/" in uid: raise InputError("本人情報が不正です。")
        self.uid=uid
        self.root="projects/"+project+"/databases/(default)/documents"
        self.owner="users/"+uid
        self.token=token
        self.transport=transport or requests
    def _request(self,method,path="",payload=None,params=None):
        url="https://firestore.googleapis.com/v1/"+self.root
        url+=path if path.startswith(":") else "/"+quote(path,safe="/") if path else ""
        try:
            response=self.transport.request(method,url,headers={"Authorization":"Bearer "+self.token},
                json=payload,params=params,timeout=30,allow_redirects=False)
        except requests.RequestException as exc:
            raise InputError("Firestoreへ接続できません。保存完了は確認できていません。履歴を確認してから再操作してください。") from exc
        if response.status_code==404: raise InputError("分析履歴が見つかりません。")
        if response.status_code in (401,403): raise InputError("Firestoreへの保存権限を確認できません。再ログインしてお試しください。")
        if response.status_code==429: raise InputError("Firestoreの利用上限に達しました。時間をおいて再操作してください。")
        if not 200<=response.status_code<300:
            raise InputError("Firestore処理を完了できません（HTTP "+str(response.status_code)+"）。履歴を確認してください。")
        return response.json()
    def _write(self,path,data,create=True):
        out={"update":{"name":self.root+"/"+path,"fields":fields(data)}}
        if create: out["currentDocument"]={"exists":False}
        return out
    def _commit(self,writes):
        payload={"writes":writes}
        if len(writes)>400 or len(json.dumps(payload).encode())>MAX_COMMIT:
            raise InputError("保存内容が大きすぎます。画像や株価データの量を減らしてください。")
        self._request("POST",":commit",payload)
    def _blob_writes(self,path,raw,metadata):
        if len(raw)>MAX_RAW: raise InputError("保存する分析が大きすぎます。")
        compressed=gzip.compress(raw,mtime=0)
        chunks=[compressed[i:i+CHUNK] for i in range(0,len(compressed),CHUNK)]
        header={**metadata,"schema_version":1,"codec":"gzip","chunks":len(chunks),
                "sha256":hashlib.sha256(raw).hexdigest(),"raw_size":len(raw)}
        return [self._write(path,header)]+[self._write(path+"/chunks/"+str(i),{"data":chunk}) for i,chunk in enumerate(chunks)]
    def _read_blob(self,path,header=None):
        header=header or unpack(self._request("GET",path))
        count=header.get("chunks",0);size=header.get("raw_size",0)
        if header.get("schema_version")!=1 or header.get("codec")!="gzip" or not 1<=count<=64 or not 0<size<=MAX_RAW:
            raise InputError("保存形式またはサイズが不正です。")
        # Each request goes to the verified user's document path; no caller-supplied path is accepted.
        compressed=b"".join(unpack(self._request("GET",path+"/chunks/"+str(i)))["data"] for i in range(count))
        try:
            inflater=zlib.decompressobj(16+zlib.MAX_WBITS)
            raw=inflater.decompress(compressed,size+1)
            if len(raw)!=size or not inflater.eof or inflater.unused_data or hashlib.sha256(raw).hexdigest()!=header["sha256"]: raise ValueError()
        except (ValueError,zlib.error,KeyError) as exc: raise InputError("保存データの整合性を確認できません。") from exc
        return raw
    def _run_path(self,run_id):
        try: parsed=str(uuid.UUID(run_id))
        except (ValueError,TypeError,AttributeError) as exc: raise InputError("分析IDが不正です。") from exc
        return self.owner+"/judgmentRuns/"+parsed
    def save_group(self,pending):
        stamp=datetime.now(timezone.utc).isoformat();writes=[]
        for result,bundle,cfg in pending:
            refs={ref for p in result.plans for ref in p.evidence_ids}
            refs|={ref for d in result.decisions.values() for ref in d.evidence_ids}
            if not refs.issubset(result.evidence): raise InputError("保存対象のEvidence参照が欠落")
            data=canonical({"result":result,"snapshot":bundle,"config":cfg}).encode()
            writes+=self._blob_writes(self._run_path(result.run_id),data,{
                "run_id":result.run_id,"symbol":result.symbol,"name":result.name,"as_of":result.as_of,
                "created_at":stamp,"horizon":result.metadata.get("horizon","swing"),"is_demo":bool(result.metadata.get("is_demo"))})
        # Firestore commit is atomic: all three horizon snapshots are committed together.
        self._commit(writes)
    def list_runs(self,limit=20):
        docs=self._request("GET",self.owner+"/judgmentRuns",params={"pageSize":min(limit,20),"orderBy":"created_at desc"}).get("documents",[])
        return [{k:v for k,v in unpack(doc).items() if k in {"run_id","symbol","name","as_of","horizon","is_demo"}} for doc in docs]
    def get(self,run_id):
        return json.loads(self._read_blob(self._run_path(run_id)))["result"]
    def approval(self,run_id,scenario,action,target_hash,current_hash,now,user_id=None):
        if user_id!=self.uid: raise InputError("本人情報が一致しません。")
        result=self.get(run_id)
        validate_approval(result,scenario,action,target_hash,current_hash,now)
        scenario_id=hashlib.sha256(scenario.encode()).hexdigest()
        record={"status":action,"scenario":scenario,"target_hash":target_hash,"uid":self.uid,"decided_at":now}
        root=self._run_path(run_id)
        self._commit([self._write(root+"/approvals/"+uuid.uuid4().hex,record),
                      self._write(root+"/approvalState/"+scenario_id,record,create=False)])
        return action
    def approval_state(self,run_id,scenario,current_hash,now):
        result=self.get(run_id);decision=result["decisions"].get(scenario,{})
        if not decision.get("approval_required") or not decision.get("approval_eligible"): return "not_requested"
        plan=next((p for p in result["plans"] if p["kind"]==scenario.split(":")[0]),None)
        if current_hash!=result["approval_hash"] or plan is None or time_value(now)>time_value(plan["expires_at"]): return "expired"
        path=self._run_path(run_id)+"/approvalState/"+hashlib.sha256(scenario.encode()).hexdigest()
        try: record=unpack(self._request("GET",path))
        except InputError as exc:
            if str(exc)=="分析履歴が見つかりません。": return "pending"
            raise
        return record["status"] if record.get("target_hash")==current_hash else "expired"
    def save_image(self,raw,evidence,kind):
        if len(raw)>6_000_000: raise InputError("Firestoreに保存する画像は6MB以内にしてください。")
        path=self.owner+"/judgmentImages/"+uuid.uuid4().hex
        saved=replace(evidence,source_uri="firestore:"+path)
        self._commit(self._blob_writes(path,raw,{"created_at":datetime.now(timezone.utc).isoformat(),
                     "mime":"image/png" if kind=="PNG" else "image/jpeg","evidence":canonical(saved)}))
        return plain(saved)
    def get_image(self,image_id):
        if not re.fullmatch(r"[a-f0-9]{32}",image_id): raise InputError("画像IDが不正です。")
        path=self.owner+"/judgmentImages/"+image_id
        header=unpack(self._request("GET",path))
        if header.get("mime") not in {"image/png","image/jpeg"}: raise InputError("画像形式が不正です。")
        return {"mime":header["mime"],"data":base64.b64encode(self._read_blob(path,header)).decode()}
