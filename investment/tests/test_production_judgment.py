"""Small integration regression set: identity, atomic history, and canonical rules."""
import asyncio
import base64
import hashlib
import json
from pathlib import Path
import sys
import time
import pytest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from app_server import create_app,present
from judgment.auth import FirebaseIdentity,AuthenticationError
from judgment.service import JudgmentService
from investment_app.models import InputError
from investment_app.uat_service import demo

def call(app,path,method="GET",token=None,payload=None):
    async def run():
        body=json.dumps(payload).encode() if payload is not None else b""
        sent=[]
        headers=[(b"content-type",b"application/json")]
        if token is not None: headers.append((b"authorization",("Bearer "+token).encode()))
        scope={"type":"http","asgi":{"version":"3.0"},"http_version":"1.1","method":method,
               "scheme":"http","path":path,"raw_path":path.encode(),"query_string":b"",
               "headers":headers,"client":("127.0.0.1",1),"server":("test",80)}
        async def receive(): return {"type":"http.request","body":body,"more_body":False}
        async def send(event): sent.append(event)
        await app(scope,receive,send)
        status=next(e["status"] for e in sent if e["type"]=="http.response.start")
        raw=b"".join(e.get("body",b"") for e in sent if e["type"]=="http.response.body")
        return status,json.loads(raw) if raw.startswith((b"{",b"[",b'"')) else raw
    return asyncio.run(run())

class TestIdentity:
    def verify(self,token):
        if token not in {"alice","bob"}: raise AuthenticationError("invalid")
        return token

@pytest.fixture(scope="module")
def analyzed(tmp_path_factory):
    service=JudgmentService(tmp_path_factory.mktemp("native"))
    raw,meta=demo()
    payload={"csv":base64.b64encode(raw).decode(),"symbol":meta["symbol"],"as_of":meta["as_of"],"metadata":meta}
    result=service.analyze("alice",payload)
    return service,payload,result

def test_unauthenticated_api_and_static_secrets(tmp_path):
    app=create_app(tmp_path,TestIdentity())
    assert call(app,"/api/judgment/history")[0]==401
    assert call(app,"/api/judgment/history",token="forged")[0]==401
    assert not (tmp_path/"users").exists()
    for path in ("/app_server.py","/.runtime/production.json","/.git/config","/investment/data/demo_evidence.json","/judgment/auth.py"):
        assert call(app,path)[0]==404
    assert call(app,"/")[0]==200

def test_two_horizons_owner_isolation_and_saved_snapshot(analyzed):
    service,payload,results=analyzed
    assert set(results)=={"swing","midlong"}
    assert len({r["run_id"] for r in results.values()})==2
    assert len(service.list_runs("alice"))==2
    assert service.list_runs("bob")==[]
    app=create_app(service.directory,TestIdentity())
    run=results["swing"]["run_id"]
    assert call(app,"/api/judgment/runs/"+run,token="alice")[0]==200
    status,data=call(app,"/api/judgment/runs/"+run,token="bob")
    assert status in (400,404) and "scores" not in data
    assert service.get("alice",run)==results["swing"]

def test_invalid_reanalysis_leaves_history_intact(analyzed):
    service,payload,results=analyzed
    before={r["run_id"]:service.get("alice",r["run_id"]) for r in results.values()}
    with pytest.raises(InputError): service.analyze("alice",dict(payload,csv=base64.b64encode(b"bad,data").decode()))
    assert len(service.list_runs("alice"))==2
    assert all(service.get("alice",run)==r for run,r in before.items())
    with service.history("alice").connect() as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0]=="ok"

def test_scores_and_stale_view_preserve_engine_results(analyzed):
    _,_,results=analyzed
    for r in results.values():
        view=present(r)
        for kind,scores in r["scores"].items():
            assert scores["investment"] is None or 0<=float(scores["investment"])<=10
            assert scores["entry"] is None or 0<=float(scores["entry"])<=10
        for p in r["plans"]:
            if p["rr"] is not None:
                expected=(float(p["target1"])-float(p["entry"]))/(float(p["entry"])-float(p["stop1"]))
                assert float(p["rr"])==pytest.approx(expected,abs=0.001)
        assert view["scores"]==r["scores"]
        assert all(not v["can_recommend"] for v in view["presentation"].values())

def test_google_validation_required_for_plausible_jwt(monkeypatch):
    identity=FirebaseIdentity(ROOT)
    claims={"aud":identity.project,"iss":"https://securetoken.google.com/"+identity.project,
            "sub":"alice","exp":time.time()+3600,"iat":time.time()}
    token="header."+base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")+".forged"
    calls=[]
    class Rejected:
        status_code=400
    def reject(*args,**kwargs): calls.append(kwargs);return Rejected()
    monkeypatch.setattr("judgment.auth.requests.post",reject)
    with pytest.raises(AuthenticationError): identity.verify(token)
    assert len(calls)==1
    assert identity.cache=={}

def test_canonical_spec_config_and_engines_unchanged():
    manifest=json.loads((ROOT/"docs/INTEGRATION_SOURCE_HASHES.json").read_text(encoding="utf-8"))
    for relative,expected in manifest["files"].items():
        # Storage/ticks, two horizons, and the explicit automatic-card hook have focused regression tests.
        if Path(relative.replace(chr(92),"/")).name in {"storage.py","uat_service.py","scoring.py","entry_exit.py","horizons.py","horizons.json","ai_bridge.py","uat_ui.py","15_FINAL_DESIGN.md"}: continue
        raw=(ROOT/relative.replace(chr(92),"/")).read_bytes()
        # Git checkout may translate CRLF/LF; only line endings may differ from the original.
        lf=raw.replace(b"\r\n",b"\n")
        variants=(raw,lf,lf.replace(b"\n",b"\r\n"))
        assert expected in {hashlib.sha256(value).hexdigest() for value in variants},relative
