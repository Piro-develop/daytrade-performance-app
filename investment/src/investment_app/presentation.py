"""Shared result presentation guards; no UI framework dependency."""
from datetime import datetime,timezone
from .models import time_value

def selected_result(results,horizon,scenario,now=None,stale=False):
    now=now or datetime.now(timezone.utc)
    result=results[horizon]
    decision=result["decisions"][scenario]
    kind=scenario.split(":")[0]
    score=result["scores"][kind]
    plan=next((p for p in result["plans"] if p["kind"]==kind),None)
    expired=bool(plan and time_value(plan["expires_at"])<now)
    findings=sorted(decision["findings"],key=lambda f:{"Critical":0,"Severe":1,"Warning":2}[f["severity"]])
    critical=any(f["severity"]=="Critical" for f in findings)
    label=decision["label"] or "未判定"
    if critical: label="評価不能"
    if stale: label+="（入力変更前の結果）"
    elif expired: label+="（期限切れ・履歴）"
    daily=result["technical"].get("daily") or [{}]
    return {
      "analysis_id":result["run_id"], "label":label,"status":decision["status"],
      "investment":score["investment"],"entry_quality":score["entry"],
      "current":result["technical"].get("latest",daily[-1].get("close")),
      "plan":plan,"findings":findings,"expired":expired,
      "concern":findings[0]["reason"] if findings else
          (decision["wait_reasons"][0] if decision["wait_reasons"] else "明示された重大警告なし。原資料で確認してください。"),
      "approval_required":decision["approval_required"],
      "can_recommend":not (stale or expired or critical or decision["approval_required"]) and
          decision["status"]=="評価可能" and kind=="現値" and label in ("買い","条件付き買い","打診買い")
    }
