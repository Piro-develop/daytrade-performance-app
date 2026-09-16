"""Production storage checks without touching a real Firebase account."""
import base64
import copy
from io import BytesIO
import json
from urllib.parse import unquote
import pytest
from PIL import Image
from test_production_judgment import call,TestIdentity
from app_server import create_app
from judgment.firestore_store import FirestoreHistory
from judgment.service import JudgmentService
from investment_app.models import InputError
from investment_app.uat_service import demo

class Reply:
    def __init__(self,status,data): self.status_code=status;self.data=data
    def json(self): return self.data

class FakeFirestore:
    def __init__(self): self.docs={};self.commits=0;self.fail=False
    def request(self,method,url,headers,json=None,params=None,**kwargs):
        uid=headers["Authorization"].removeprefix("Bearer ")
        name=unquote(url.split("/v1/")[1])
        if method=="POST":
            assert name.endswith(":commit")
            writes=json["writes"]
            assert all("/documents/users/"+uid+"/" in w["update"]["name"] for w in writes)
            if self.fail:return Reply(503,{})
            if any(w.get("currentDocument",{}).get("exists") is False and w["update"]["name"] in self.docs for w in writes):return Reply(409,{})
            updated=copy.deepcopy(self.docs)
            for w in writes: updated[w["update"]["name"]]=copy.deepcopy(w["update"])
            self.docs=updated;self.commits+=1
            return Reply(200,{})
        assert "/documents/users/"+uid+"/" in name
        if params:
            docs=[v for k,v in self.docs.items() if k.startswith(name+"/") and "/" not in k[len(name)+1:]]
            return Reply(200,{"documents":docs[:params["pageSize"]]})
        return Reply(200,self.docs[name]) if name in self.docs else Reply(404,{})

def store(db,uid="alice"): return FirestoreHistory("daytrade-performance-app",uid,uid,db)

def payload():
    raw,meta=demo()
    return {"csv":base64.b64encode(raw).decode(),"symbol":meta["symbol"],"as_of":meta["as_of"],"metadata":meta}

def test_atomic_two_horizons_restart_and_uid_isolation():
    db=FakeFirestore()
    app=create_app(identity=TestIdentity(),store_factory=lambda uid,token:FirestoreHistory("daytrade-performance-app",uid,token,db))
    data=payload();data["uid"]="bob"
    status,out=call(app,"/api/judgment/analyze","POST","alice",data)
    assert status==200 and set(out["results"])=={"swing","midlong"}
    assert db.commits==1
    fresh=store(db)
    assert len(fresh.list_runs())==2
    run=out["results"]["swing"]["run_id"]
    assert fresh.get(run)["run_id"]==run
    assert call(app,"/api/judgment/runs/"+run,token="bob")[0]==400
    assert call(app,"/api/judgment/history",token="bob")== (200,[])
    assert call(app,"/api/judgment/history",token="forged")[0]==401
    assert all("/users/alice/judgmentRuns/" in k for k in db.docs)
    assert "Bearer " not in json.dumps(db.docs)
    before=copy.deepcopy(db.docs);db.fail=True
    with pytest.raises(InputError):JudgmentService(store=store(db)).analyze("alice",payload())
    assert db.docs==before

def test_private_image_roundtrip_and_corruption():
    db=FakeFirestore();service=JudgmentService(store=store(db))
    buf=BytesIO();Image.new("RGB",(2,2)).save(buf,format="PNG")
    raw=buf.getvalue();stamp="2026-09-09T00:00:00+00:00"
    e=service.image("alice",{"image":base64.b64encode(raw).decode(),"confirmed":True,
       "source_name":"synthetic fixture","observed_at":stamp,"published_at":stamp,"as_of":stamp,"summary":"image fixture"})
    image_id=e["source_uri"].split("/")[-1]
    assert base64.b64decode(store(db).get_image(image_id)["data"])==raw
    with pytest.raises(InputError):store(db,"bob").get_image(image_id)
    root=next(k for k in db.docs if k.endswith(image_id))
    db.docs[root]["fields"]["sha256"]={"stringValue":"corrupted"}
    with pytest.raises(InputError):store(db).get_image(image_id)
    with pytest.raises(InputError):store(db).get_image("../bob")
