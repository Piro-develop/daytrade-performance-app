from __future__ import annotations
from datetime import datetime, time
from .models import Bundle, Finding, Severity, time_value, JST

def preflight(bundle: Bundle, weekly_count: int | None = None) -> list[Finding]:
    findings = list(bundle.findings)
    meta = bundle.metadata
    market = (meta["market_evidence_id"],)
    if weekly_count is not None and weekly_count < 2:
        findings.append(Finding("weekly_missing", Severity.CRITICAL, "investment",
            "週足の大局を確認する履歴が不足しています。", market, "十分な確定日足・週足を入力"))
    review = meta.get("preflight_review", {})
    for key, label in [("negative_news", "重大悪材料"), ("thesis", "投資前提"), ("liquidity", "流動性")]:
        check = review.get(key, {})
        refs = tuple(check.get("evidence_ids", []))
        if not check.get("reviewed") or not refs or any(x not in bundle.evidence for x in refs):
            findings.append(Finding("unchecked_" + key, Severity.WARNING, "decision",
                label + "の独立確認が完了していません。", resolution="根拠付き確認を入力"))
    financial=meta.get("latest_financial",{})
    refs=tuple(financial.get("evidence_ids",[]))
    if not financial.get("latest_confirmed") or not financial.get("period") or not refs or any(r not in bundle.evidence for r in refs):
        findings.append(Finding("financial_missing",Severity.CRITICAL,"investment",
            "最新の公式業績根拠（対象期・Evidence付き）を確認できません。Entryは独立評価します。"))
    for item in meta.get("warnings", []):
        refs = tuple(item.get("evidence_ids", []))
        if not refs or any(x not in bundle.evidence for x in refs) or not item.get("reason"):
            findings.append(Finding("warning_unverified", Severity.CRITICAL, "decision",
                "警告の根拠・理由が不足しています。", resolution="警告Evidenceを確認"))
            continue
        try:
            severity = Severity(item["severity"])
        except (ValueError, KeyError):
            findings.append(Finding("warning_severity", Severity.CRITICAL, "decision",
                                    "警告の重大度が不正です。"))
            continue
        scope = item.get("scope", "decision")
        if scope not in {"all", "investment", "entry", "decision"}:
            scope = "decision"
        findings.append(Finding(item.get("code", "manual_warning"), severity, scope,
                                item["reason"], refs, item.get("resolution", "再評価")))
    age = (time_value(bundle.as_of) - time_value(bundle.bars[-1]["timestamp"])).total_seconds() / 3600
    sessions = meta.get("calendar", [])
    if sessions:
        day = time_value(bundle.bars[-1]["timestamp"]).astimezone(JST).date().isoformat()
        asday = time_value(bundle.as_of).astimezone(JST).date().isoformat()
        stale = any(day < session <= asday and
            datetime.combine(datetime.fromisoformat(session).date(),time(15,30),JST) <= time_value(bundle.as_of)
            for session in sessions)
    else:
        stale = age > 72
        findings.append(Finding("calendar_missing", Severity.WARNING, "decision",
            "取引カレンダー未設定。営業日数は未算出、価格鮮度は経過時間の暫定判定です。", market))
    if stale:
        findings.append(Finding("stale_prices", Severity.WARNING, "all",
            "価格が直近取引セッションより古い可能性があります。暫定評価です。", market))
    return findings

def confidence(bundle: Bundle, findings: list[Finding], items: dict, required_cards=None) -> dict:
    """Equal-weight required card evidence checks; unknown quality earns no assumed credit."""
    from .scoring import catalog
    stale = any(f.code == "stale_prices" for f in findings)
    conflict = any(f.code == "conflicting_prices" for f in findings)
    checks=bundle.metadata.get("evidence_quality",{})
    rows=[]
    market=bundle.metadata["market_evidence_id"]
    def quality(ref, visited=()):
        if ref in visited or ref not in bundle.evidence:
            return (0.0,0.0,0.0)
        ev=bundle.evidence[ref]
        if ev.derived_from:
            parents=[quality(r,visited+(ref,)) for r in ev.derived_from]
            return tuple(min(x[i] for x in parents) for i in range(3))
        if ref==market:
            return (0.0 if stale else 1.0,0.5,0.0 if conflict else 0.5)
        check=checks.get(ref,{})
        valid_until=check.get("valid_until")
        fresh=0.0
        if valid_until and time_value(valid_until)>=time_value(bundle.as_of):
            fresh=0.5 if check.get("constrained") else 1.0
        source={"original_verified":1.0,"secondary_verified":0.5,"image_verified":0.5}.get(check.get("source_quality"),0.0)
        independent=check.get("independent_evidence_ids",[])
        matched=bool(check.get("match_reason") and independent and
            all(r in bundle.evidence and r!=ref and
                bundle.evidence[r].source_uri!=ev.source_uri and
                r not in ev.derived_from and ref not in bundle.evidence[r].derived_from for r in independent))
        cross=0.0 if check.get("unresolved_conflict") else 1.0 if matched else 0.5
        return fresh,source,cross
    for code in (catalog() if required_cards is None else required_cards):
        if code.startswith(("SC-","MC-")): continue # Optional context is not required coverage or confidence.
        item=items.get(code,{})
        refs=item.get("evidence_ids",[])
        present=bool(item.get("score") is not None and refs and all(r in bundle.evidence for r in refs))
        metrics=[quality(r) for r in refs] if present else []
        values=tuple(min(x[i] for x in metrics) for i in range(3)) if metrics else (0.0,0.0,0.0)
        rows.append({"criterion_id":code,"evidence_ids":refs,"present":present,
            "F":values[0],"S":values[1],"X":values[2]})
    n=len(rows)
    averages={key:sum(row[key] for row in rows)/n for key in ("F","S","X")}
    averages["C"]=sum(row["present"] for row in rows)/n
    weights={"F":35,"C":25,"S":25,"X":15}
    components={key:weights[key]*averages[key] for key in weights}
    return {"value":round(sum(components.values()),1),"components":components,"ratios":averages,"items":rows,
        "note":"必須Evidenceは各カードの併用資料を一組として等重み。未確認の鮮度・出所は0、未照合は0.5。投資得点とは別です。"}
