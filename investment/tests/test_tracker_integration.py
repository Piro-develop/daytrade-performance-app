"""Only safety-critical integration regressions: stale buys and data exposure."""
import copy
from datetime import datetime, timezone
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import uat_server
from uat_server import public_path
from investment_app.integration_ui import selected_result
from investment_app.uat_service import demo,bundle_from_input,run_all
from investment_app.storage import History

def test_private_files_are_never_served(tmp_path,monkeypatch):
    monkeypatch.setattr(uat_server,"ROOT",tmp_path)
    (tmp_path/"index.html").write_text("public")
    (tmp_path/"assets/icons").mkdir(parents=True)
    (tmp_path/"assets/icons/icon.png").write_bytes(b"public icon")
    (tmp_path/".runtime").mkdir()
    (tmp_path/".runtime/private.png").write_bytes(b"private screenshot")
    assert public_path("index.html").name=="index.html"
    assert public_path("assets/icons/icon.png").name=="icon.png"
    for value in (".git/config",".runtime/uat-access.html","investment/data/demo_evidence.json",
                  "investment/app.py","../AGENTS.md","assets/icons/../../.git/config",
                  "assets/icons/../../.runtime/private.png"):
        assert public_path(value) is None

def test_summary_never_promotes_stale_or_critical_buy(tmp_path):
    csv,meta=demo()
    results=run_all(bundle_from_input(csv,meta,meta["symbol"],meta["as_of"]),History(tmp_path/"history.sqlite"))
    result=copy.deepcopy(results["swing"])
    key=next(k for k in result["decisions"] if k.startswith("現値:"))
    decision=result["decisions"][key]
    decision.update(label="買い",status="評価可能",approval_required=False,findings=[])
    plans=[p for p in result["plans"] if p["kind"]=="現値"]
    assert plans
    plans[0]["expires_at"]="2026-09-10T15:30:00+09:00"
    bundle={"swing":result}
    before=datetime(2026,9,9,tzinfo=timezone.utc)
    assert selected_result(bundle,"swing",key,now=before)["can_recommend"]
    assert not selected_result(bundle,"swing",key,now=before,stale=True)["can_recommend"]
    assert not selected_result(bundle,"swing",key,now=datetime(2026,9,11,tzinfo=timezone.utc))["can_recommend"]
    decision["approval_required"]=True
    assert not selected_result(bundle,"swing",key,now=before)["can_recommend"]
    decision["findings"]=[{"severity":"Critical","reason":"必須情報不足"}]
    view=selected_result(bundle,"swing",key,now=before)
    assert view["label"]=="評価不能" and not view["can_recommend"]
    assert view["concern"]=="必須情報不足"
