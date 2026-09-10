"""Swing vertical slice orchestration. No external service calls."""
from __future__ import annotations
from datetime import datetime, timedelta
from decimal import Decimal
import calendar
import uuid
from .config import config_identity
from .decision import decide
from .entry_exit import plans_for
from .models import AnalysisResult, Bundle, EvaluationStatus, Finding, InputError, Severity, JST, digest, plain, time_value
from .preflight import confidence, preflight
from .scoring import score, macro_chain
from .technical import compute, number

def earnings_info(bundle: Bundle, policy: str) -> dict:
    scheduled=bundle.metadata.get("earnings_at")
    result={"scheduled_at":scheduled, "policy":policy,"business_days":None,
            "scenarios":["allow","avoid"] if policy=="unspecified" else [policy],"within_month":None}
    if not scheduled:
        return result
    event=time_value(scheduled).astimezone(JST).date()
    today=time_value(bundle.as_of).astimezone(JST).date()
    sessions=bundle.metadata.get("calendar",[])
    if sessions and min(sessions)<=today.isoformat() and max(sessions)>=event.isoformat():
        result["business_days"]=sum(today.isoformat()<day<=event.isoformat() for day in sessions)
    month=today.month%12+1
    year=today.year+(today.month==12)
    limit=today.replace(year=year,month=month,day=min(today.day,calendar.monthrange(year,month)[1]))
    result["within_month"]=today<=event<=limit
    return result

def analyze(bundle: Bundle, cfg: dict, specified_entry=None, earnings_policy="unspecified") -> AnalysisResult:
    if earnings_policy not in {"allow","avoid","unspecified"}:
        raise InputError("決算跨ぎ方針が不正です。")
    if specified_entry is not None:
        try:
            entry=Decimal(str(specified_entry))
            if not entry.is_finite() or entry<=0:
                raise ValueError()
        except Exception as exc:
            raise InputError("想定Entry価格は正の数値です。") from exc
    technical=compute(bundle,cfg)
    findings=preflight(bundle,technical["weekly_count"])
    if not technical["tick_valid"]:
        findings.append(Finding("tick_missing",Severity.CRITICAL,"entry",
            "検証済み呼値・Evidenceがないため正確な価格プランは未算出です。",
            resolution="銘柄の呼値と根拠を入力"))
    plans=plans_for(bundle,technical,cfg,specified_entry)
    if not plans:
        findings.append(Finding("plan_missing",Severity.CRITICAL,"entry",
            "実支持帯・無効化位置・現実的な第1利確が揃わず、有効なEntryプランを作れません。",
            (technical["technical_evidence_id"],),"価格構造と不足情報を再確認"))
    earnings=earnings_info(bundle,earnings_policy)
    if technical["atr"] is None:
        findings.append(Finding("atr_missing",Severity.WARNING,"entry","ATR不足。価格帯集約と損切余幅は呼値だけで計算しています。"))
    if earnings["scheduled_at"] is None:
        findings.append(Finding("earnings_missing",Severity.WARNING,"decision",
            "次回決算日が不明です。跨ぎ判断とイベント採点は未評価。"))
    elif earnings["within_month"]:
        findings.append(Finding("earnings_near",Severity.WARNING,"decision",
            "1か月以内に決算予定があります。跨ぐ／跨がない条件を確認してください。",
            tuple(bundle.metadata.get("earnings_evidence_ids",[]))))
    all_scores,decisions={},{}
    for plan in plans or [None]:
        scores=score(bundle,technical,plan,cfg)
        if earnings["scheduled_at"] is None:
            scores.entry=None
            scores.entry_status=EvaluationStatus.PROVISIONAL
            if "SE-G" not in scores.missing:
                scores.missing.append("SE-G")
            scores.investment=None
            scores.status=EvaluationStatus.PROVISIONAL
            if "SW-H" not in scores.missing:
                scores.missing.append("SW-H")
        if any(x.severity==Severity.CRITICAL and x.scope in {"all","investment"} for x in findings):
            scores.structured=scores.context=scores.investment=None
            scores.status=EvaluationStatus.UNAVAILABLE
        if any(x.severity==Severity.CRITICAL and x.scope in {"all","entry"} for x in findings):
            scores.entry=None
            scores.entry_status=EvaluationStatus.UNAVAILABLE
        quality=confidence(bundle,findings,scores.items)
        evidence_constrained=any(row["present"] and row["F"]<1 for row in quality["items"])
        if evidence_constrained and not any(x.code=="evidence_freshness" for x in findings):
            findings.append(Finding("evidence_freshness",Severity.WARNING,"decision",
                "採用資料に期限外・鮮度未確認の根拠があります。正式な買いを確定しません。",
                resolution="各Evidenceの有効期限・更新対象期を確認"))
        if evidence_constrained or any(x.code=="stale_prices" for x in findings):
            if scores.status!=EvaluationStatus.UNAVAILABLE:
                scores.status=EvaluationStatus.PROVISIONAL
            if scores.entry_status!=EvaluationStatus.UNAVAILABLE:
                scores.entry_status=EvaluationStatus.PROVISIONAL
        kind=plan.kind if plan else "未算出"
        all_scores[kind]=scores
        for scenario in earnings["scenarios"]:
            decisions[kind+":"+scenario]=decide(bundle,scores,plan,findings,cfg,scenario)
    first_score=next(iter(all_scores.values()))
    version,cfg_hash=config_identity(cfg)
    daily=technical["daily"].reset_index()
    weekly=technical["weekly"].reset_index()
    for table in (daily,weekly):
        if not table.empty:
            table[table.columns[0]]=table.iloc[:,0].astype(str)
    technical_snapshot={"weekly_trend":technical["weekly_trend"],"weekly_count":technical["weekly_count"],
        "weekly_slope":technical["weekly_slope"],"rsi":technical["rsi"],"atr":technical["atr"],
        "volume_ratio":technical["volume_ratio"],"daily":plain(daily.to_dict("records")),
        "weekly":plain(weekly.to_dict("records")),"bands":plain(technical["bands"]),
        "pivots":plain(technical["pivots"]),"fibonacci":plain(technical["fibonacci"]),
        "levels":plain(technical["levels"]),
        "macro":macro_chain(bundle),"evidence_id":technical["technical_evidence_id"]}
    result=AnalysisResult(str(uuid.uuid4()),bundle.bundle_id,bundle.as_of,bundle.symbol,bundle.name,
        version,cfg_hash,plain(bundle.evidence),technical_snapshot,plans,all_scores,decisions,earnings,
        confidence(bundle,findings,first_score.items),
        {"is_demo":bool(bundle.metadata.get("is_demo")),"exit_conditions":bundle.metadata.get("exit_conditions",[]),
         "input_digest":digest({"symbol":bundle.symbol,"as_of":bundle.as_of,"metadata":bundle.metadata,
                               "bars":bundle.bars,"specified_entry":specified_entry,"earnings_policy":earnings_policy}),
         "source_mode":"manual_csv","model_version":"manual-card-evaluation","card_version":"cards-1.0.0"},
        findings)
    result.approval_hash=digest(result)
    return result
