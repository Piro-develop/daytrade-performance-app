"""Reproducible first-pass screening; never a final investment or trade decision."""
from dataclasses import replace
from decimal import Decimal
from .models import Decision, EvaluationStatus, Finding, Severity, digest
from .scoring import weighted_available, catalog
from .horizons import horizon_cards
from .preflight import confidence

VERSION="screening-1.1.0"
# Original card weights, restricted to the explicitly defined objective universe.
WEIGHTS={
    "swing":{"SW-A3":4,"SW-D1":4.9,"SW-D2":4.2,"SW-D3":2.8,"SW-D4":2.1,
             "SW-E1":3.5,"SW-E2":3.5,"SW-E4":1.5},
    "midlong":{"ML-A":25,"ML-D":12,"ML-I":2}}


def daily_state(rows, periods=4):
    if len(rows)<=periods: return "不明"
    now,old=rows[-1],rows[-1-periods]
    keys=["ma13","ma25","ma50","ma75"]
    if any(now.get(k) is None or old.get(k) is None for k in keys): return "不明"
    up=all(now[a]>now[b] for a,b in zip(keys,keys[1:])) and all(now[k]>old[k] for k in keys)
    down=all(now[a]<now[b] for a,b in zip(keys,keys[1:])) and all(now[k]<old[k] for k in keys)
    return "上昇" if up else "下降" if down else "混在"


def objective_summary(bundle):
    facts=bundle.metadata.get("public_facts",{});f=facts.get("financial",{});out=[]
    cur=f.get("current",{});forecast=f.get("forecast",{}) or {}
    for key,label in (("sales","売上高"),("operating","営業利益"),("net","純利益"),("eps","EPS"),("operating_margin","営業利益率")):
        if cur.get(key) is not None: out.append(f"{f.get('period','')} {label}: {cur[key]:,.2f} {'円' if key=='eps' else '%' if key=='operating_margin' else '百万円'}")
    for key,label in (("sales","売上高"),("operating","営業利益"),("eps","EPS")):
        if forecast.get(key) is not None: out.append(f"会社予想 {forecast.get('period','')} {label}: {forecast[key]:,.2f} {'円' if key=='eps' else '百万円'}")
    revision=facts.get("revision",{})
    if revision:
        for key,a,b in zip(("売上高","営業利益","経常利益","純利益","EPS"),revision['previous'],revision['current']):
            out.append(f"会社予想修正 {revision['period']} {key}: {a:,.2f} → {b:,.2f}")
    credit=facts.get("credit",{})
    for key,label in (("buy","信用買残"),("sell","信用売残")):
        if credit.get(key) is not None: out.append(f"{label}: {credit[key]:,}株 / 前週比 {credit[key+'_change']:+,}株 / 公表対象日 {credit[key+'_observed_at'][:10]}")
    for key,value in facts.get("valuation",{}).get("values",{}).items():
        out.append(f"公開指標 {value.get('label') or key}: {value['value']:,.2f}{value.get('unit','')} / 対象 {value.get('period_or_observed_at') or '日時未確認'}")
    disclosure=facts.get('disclosures',{}).get('items',[])
    if disclosure: out.append(f"公式開示一覧: {len(disclosure)}件確認 / 最新公表 {disclosure[0]['published_at']}。材料の意味は未評価。")
    report=facts.get('official_financial',{})
    if report: out.append(f"公式決算 {report['period']}を取得。数値表の自動変換は未対応。")
    return out


def followup(bundle):
    # Only accepted, dated assessments count as completed qualitative work, never a headline or raw metric.
    from .scoring import checked_manual
    from .horizons import all_cards
    accepted=checked_manual(bundle,all_cards())
    groups=[("最新材料・ニュースの意味と重大リスク",()),("カタリストの強弱・持続性",("SW-C",)),
      ("業績上振れ余地",("SW-A1",)),("市場期待・織り込み度",("SW-B","ML-E")),
      ("競争優位",("SW-G","ML-C")),("同業比較",("SW-J","ML-J")),
      ("セクターから企業へのマクロ影響",("SW-F","ML-G")),("将来の成長ストーリーと反証",("ML-B",))]
    todo=[label for label,codes in groups if not codes or any(accepted.get(c,{}).get('score') is None for c in codes)]
    if bundle.metadata.get('preflight_review',{}).get('negative_news',{}).get('reviewed'):
        refs=bundle.metadata['preflight_review']['negative_news'].get('evidence_ids',[])
        if refs and all(r in bundle.evidence for r in refs): todo.remove(groups[0][0])
    if not bundle.metadata.get('public_facts',{}).get('financial'): todo.append("最新公式決算の売上・利益・CF・財務状況を確認")
    if not bundle.metadata.get("public_facts",{}).get("cash_flow"): todo.append("CF・負債・利益品質の確認")
    todo.append("チャートを目視し、最終的な投資妙味・売買可否を判断")
    return todo


def strategy_summary(plans,cfg):
    current=next((p for p in plans if p.kind in ("現値","指定価格")),None)
    pullbacks=[p for p in plans if p.kind in ("第1押し目","第2押し目")]
    minimum=Decimal(str(cfg.get("rr_minimum",1.3)))
    if current is None:
        return "現値Entryは未成立。" + ("押し目到達時の価格戦略を確認してください。" if pullbacks else "有効な価格戦略がありません。")
    label="現値" if current.kind=="現値" else "指定価格"
    text=f"{label}RR {current.rr:.2f}。"
    improved=[p for p in pullbacks if p.rr>current.rr]
    if current.rr<minimum:
        if improved: text+=" ".join(f"{p.kind} Entry {p.entry:,.2f}ではRR {p.rr:.2f}。" for p in improved)
        if not any(p.rr>=minimum for p in pullbacks):
            text+="RR1.3以上の押し目は該当なし。現時点では価格戦略上の妙味が乏しく、追加確認が必要です。"
        else: text+="到達・反転確認を待つ候補です。"
    else:
        from .entry_exit import rr_bucket
        text+=rr_bucket(current.rr,cfg)+"。価格条件とトリガーを確認してください。"
    return text


def classify(tech, plans, scores, findings, earnings, facts, cfg):
    hard=[f.reason for f in findings if f.severity==Severity.CRITICAL]
    cur=facts.get('financial',{}).get('current',{})
    deteriorating=((cur.get('sales_yoy') is not None and cur.get('operating_yoy') is not None
        and cur['sales_yoy']<0 and cur['operating_yoy']<0) or
        (cur.get('operating') is not None and cur.get('net') is not None and cur['operating']<0 and cur['net']<0))
    if deteriorating and facts.get('financial',{}).get('latest_confirmed'): hard.append("公式業績で売上・営業利益の双方減少、または営業・純利益の赤字を確認")
    daily=daily_state(tech.get('daily',[]),cfg['slope_periods']);weekly=tech.get('weekly_trend','不明')
    if weekly=='下降' and daily=='下降': hard.append("週足・日足とも下降配列と下向きを確認")
    lows=[x['price'] for x in tech.get('pivots',{}).get('1w',[]) if x['kind']=='low' and x.get('major')]
    last=(tech.get('daily') or [{}])[-1].get('close')
    if lows and last is not None and last<lows[-1] and weekly=='下降': hard.append("確定週足の主要安値を下回り、週足下降構造を確認")
    if any(f.severity==Severity.SEVERE and 'liquid' in f.code for f in findings): hard.append("確認された重大な流動性制約")
    if hard: return "非通過",list(dict.fromkeys(hard)),daily
    review=[f.reason for f in findings if f.severity in (Severity.WARNING,Severity.SEVERE)]
    current=scores.get('現値') or next(iter(scores.values()))
    if current.coverage<cfg['coverage_normal']: review.append("一次定量評価のcoverageが80%未満")
    if not plans: review.append("価格戦略に必要な情報を追加確認")
    else:
        immediate=next((p for p in plans if p.kind in ("現値","指定価格")),None)
        if immediate is None or immediate.rr<Decimal(str(cfg['rr_conditional'])):
            review.append(strategy_summary(plans,cfg))
    if current.entry is None or current.entry_coverage<cfg['coverage_normal']: review.append("Entryの確認範囲が限定的")
    if weekly!='上昇' or daily!='上昇': review.append("週足・日足の方向が混在、またはトレンドの追加確認が必要")
    if not any(p.kind=='現値' and p.trigger_confirmed and p.rr>=Decimal(str(cfg.get('rr_minimum',1.3))) for p in plans): review.append("Entryトリガーまたは改善Entryの到達を確認")
    if earnings['state']=='unknown': review.append("決算予定未確認")
    if review: return "要確認",list(dict.fromkeys(review)),daily
    return "通過",["客観条件上、詳しく調べる候補。買い判断ではありません。"],daily


def apply_screening(result,bundle,cfg):
    horizon=result.metadata['horizon'];weights=WEIGHTS[horizon]
    cards=catalog() if horizon=='swing' else horizon_cards(horizon)
    objective=set(weights)
    # Missing research is routed to ChatGPT, not to a final-investment gate.
    result.findings=[f for f in result.findings if f.code not in ('unchecked_negative_news','unchecked_thesis')]
    missing_codes={'financial_missing','weekly_missing','tick_missing','warning_unverified','warning_severity'}
    if result.technical.get('weekly_count',0)<cfg['weekly_min'] or any(f.code=='tick_missing' for f in result.findings): missing_codes.add('plan_missing')
    result.findings=[replace(f,severity=Severity.WARNING) if f.code in missing_codes else f for f in result.findings]
    result.findings=[replace(f,reason="採用資料に期限外・鮮度未確認の根拠があります。更新時点を追加確認してください。")
        if f.code=='evidence_freshness' else f for f in result.findings]
    entry_prefix='SE-' if horizon=='swing' else 'ME-'
    for score in result.scores.values():
        score.items={k:v for k,v in score.items.items() if k in objective or k.startswith(entry_prefix)}
        value,coverage,gaps=weighted_available(score.items,weights)
        score.structured=score.investment=value;score.context=None;score.coverage=coverage
        blocked=any(f.severity==Severity.CRITICAL and f.scope in ('all','investment') for f in result.findings)
        if blocked: score.structured=score.investment=None
        constrained=any(f.code in ('stale_prices','evidence_freshness') for f in result.findings)
        score.status=EvaluationStatus.UNAVAILABLE if value is None or blocked else EvaluationStatus.EVALUABLE if coverage>=cfg['coverage_normal'] and not constrained else EvaluationStatus.PROVISIONAL
        score.missing=gaps+[c for c in score.missing if c.startswith(entry_prefix)]
    first=result.scores.get('現値') or next(iter(result.scores.values()))
    result.confidence=confidence(bundle,result.findings,first.items,{k:v for k,v in cards.items() if k in objective or k.startswith(entry_prefix)})
    if first.coverage<cfg['coverage_normal']:
        result.findings.append(Finding('screening_coverage',Severity.WARNING,'screening',f'一次定量評価coverage {first.coverage:.1%}。欠損は点を付けず除外しています。'))
    facts=bundle.metadata.get('public_facts',{})
    if not facts.get('financial'):
        result.findings.append(Finding('financial_numbers_missing',Severity.WARNING,'screening','公式業績の数値比較は未確認。チャート主体の一次定量評価です。'))
    label,reasons,daily=classify(result.technical,result.plans,result.scores,result.findings,result.earnings,facts,cfg)
    severe=[f for f in result.findings if f.severity==Severity.SEVERE]
    conditions=bundle.metadata.get('severe_conditions',{})
    complete=all(conditions.get(f.code,{}).get('reason') and conditions.get(f.code,{}).get('remaining_risk')
        and conditions.get(f.code,{}).get('evidence_ids') and all(r in bundle.evidence for r in conditions[f.code]['evidence_ids']) for f in severe)
    for scenario in result.decisions:
        kind=scenario.split(':')[0];plan=next((p for p in result.plans if p.kind==kind),None)
        refs=sorted({r for item in result.scores[kind].items.values() for r in item.get('evidence_ids',[])})
        state=EvaluationStatus.UNAVAILABLE if any(f.severity==Severity.CRITICAL for f in result.findings) else EvaluationStatus.PROVISIONAL if label=='要確認' else EvaluationStatus.EVALUABLE
        result.decisions[scenario]=Decision(label,state,None,[],reasons,result.findings,[],refs,bool(severe),
            bool(severe and complete and plan and result.scores[kind].entry is not None and label!='非通過' and state!=EvaluationStatus.UNAVAILABLE))
    result.metadata.update(evaluation_policy=VERSION,screening={'version':VERSION,'label':label,'reasons':reasons,
        'daily_state':daily,'strategy_summary':strategy_summary(result.plans,cfg),'facts':objective_summary(bundle),'chatgpt_checks':followup(bundle),
        'weights':weights,'meaning':'詳しく調べる価値の一次判定。最終投資妙味・買い判断ではありません。'})
    cfg['screening_policy']={'version':VERSION,'weights':WEIGHTS}
    result.config_version+=':'+VERSION;result.config_hash=digest(cfg)
