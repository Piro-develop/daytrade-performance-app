"""Evidence-backed fixed anchors for the automatic route, never missing-value imputation."""
from dataclasses import replace
from datetime import timedelta
from .models import Evidence, digest, time_value


def assessment(code, value, refs, reason, counter):
    return dict(criterion_id=code,anchor=value,evidence_ids=list(refs),reason=reason,counter_reason=counter,
                rule_version='cards-1.0.0',evaluator='program:public-facts-v1')


def prepare_automatic(bundle):
    meta=bundle.metadata
    if not meta.get('automatic'): return
    quality=meta.setdefault('evidence_quality',{})
    for eid,ev in bundle.evidence.items():
        if eid in quality: continue
        if eid.startswith('public-daily-'):
            quality[eid]=dict(valid_until=(time_value(ev.observed_at)+timedelta(hours=72)).isoformat(),source_quality='secondary_verified',unresolved_conflict=False)
        elif eid.startswith('jpx-company-'):
            quality[eid]=dict(valid_until=(time_value(ev.observed_at)+timedelta(days=35)).isoformat(),source_quality='original_verified',unresolved_conflict=False)
        elif eid.startswith('jpx-tick-'):
            quality[eid]=dict(valid_until=(time_value(ev.fetched_at)+timedelta(days=1)).isoformat(),source_quality='original_verified',unresolved_conflict=False)
    source=meta.get('automatic',{}).get('price_evidence_id')
    if source in bundle.evidence:
        market=meta['market_evidence_id']
        bundle.evidence[market]=replace(bundle.evidence[market],derived_from=(source,))
    from .config import load_config
    count=load_config()['comparison_days'];sample=bundle.bars[-count:]
    if len(sample)==count and all(r['volume']>0 for r in sample):
        gaps=[abs(float(b['open'])-float(a['close'])) for a,b in zip(sample,sample[1:])]
        lower=min(float(r['low'])*float(r['volume']) for r in sample)
        upper=max(float(r['high'])*float(r['volume']) for r in sample)
        reason=f'{count}確定日すべて出来高あり。日足から算出した売買代金の下限/上限={lower:.0f}/{upper:.0f}円（実売買代金ではない）。最大寄付ギャップ={max(gaps):.2f}円。継続売買と価格飛びの制約を確認。'
        meta.setdefault('preflight_review',{})['liquidity']=dict(reviewed=True,anchor=6,evidence_ids=[meta['market_evidence_id']],reason=reason)
    facts=meta.get('public_facts',{});f=facts.get('financial',{});rev=facts.get('revision',{})
    report=facts.get('official_financial',{})
    if report.get('latest_confirmed') and all(r in bundle.evidence for r in report.get('evidence_ids',[])):
        meta['latest_financial']=report.copy()
    rows=meta.setdefault('assessments',[]);used={r['criterion_id'] for r in rows}
    def put(code,value,refs,reason,counter):
        if code not in used and refs and all(r in bundle.evidence for r in refs):
            rows.append(assessment(code,value,refs,reason,counter));used.add(code)
    if f.get('latest_confirmed'):
        meta['latest_financial']={k:f[k] for k in ('period','latest_confirmed','evidence_ids')}
        cur,prev,forecast=f['current'],f['previous'],f.get('forecast')
        refs=f['evidence_ids']
        if (cur.get('eps') is not None and prev.get('eps') is not None and cur['operating_margin'] is not None and prev['operating_margin'] is not None):
            if cur['eps']<prev['eps'] or cur['operating_margin']<prev['operating_margin']:
                put('SW-A3',4,refs,'同一連結範囲・前年同期比でEPSまたは営業利益率が悪化。','赤字・一過性要因・通期予想を別途確認。')
            elif (cur['eps']>prev['eps'] and cur['operating_margin']>prev['operating_margin'] and prev.get('operating_yoy') is not None and prev.get('sales_yoy') is not None and prev['operating_yoy']>prev['sales_yoy'] and prev.get('net_yoy',-1)>0):
                put('SW-A3',8,refs,f"EPS {prev['eps']}→{cur['eps']}、営業利益率 {prev['operating_margin']:.2f}%→{cur['operating_margin']:.2f}%。前年の比較期も増益・利益率改善で継続改善を確認。",'期中の一時的需要や製品構成の影響が持続する保証はない。')
        if all(cur.get(k) is not None and prev.get(k) is not None for k in ('sales','operating','operating_margin')) and cur['sales']>prev['sales']>0 and cur['operating_margin']>prev['operating_margin']>0:
            sales_effect=(cur['sales']-prev['sales'])*prev['operating_margin']/100
            margin_effect=cur['sales']*(cur['operating_margin']-prev['operating_margin'])/100
            put('ML-D',8,refs,f'前年同期比の営業増益を分解：売上高増の寄与{sales_effect:.1f}百万円、利益率改善の寄与{margin_effect:.1f}百万円。率の改善が利益へ接続。','算術分解であり数量・単価・構成の因果を分離したものではない。一時要因と持続性は別途確認。')
        if forecast and rev and rev.get('period')==forecast['period']:
            changes=[b-a for a,b in zip(rev['previous'],rev['current'])]
            if all(x>0 for x in changes) and cur['operating_yoy'] is not None and cur['operating_yoy']>0 and forecast.get('operating_yoy') is not None and forecast['operating_yoy']>0:
                put('ML-A',8,refs+rev['evidence_ids'],'同一通期計画の売上・利益・EPS引上げと直近実績の増益が将来利益成長を支持。','会社計画は保証ではなく、一時的需要と来期以降の持続性は未確認。複数独立ドライバーの10は付けない。')
                # A realized forecast increase does not prove further upside to the revised plan (SW-A1).
            if all(x<0 for x in changes):
                put('SW-A1',4,refs+rev['evidence_ids'],'同期間の売上・利益・EPS予想を下方修正。','減益要因が一時的か持続的かは追加確認が必要。')
        earnings=facts.get('earnings',{})
        if f.get('going_concern_no_issue') and forecast and forecast['operating']>0 and forecast['net']>0:
            meta.setdefault('preflight_review',{})['thesis']=dict(reviewed=True,evidence_ids=refs,reason='最新公式決算で継続企業注記は該当なし。黒字会社計画の継続を確認。競争優位等の投資仮説は未確認。')
            meta['exit_conditions']=['会社が採用した通期利益計画を撤回、または継続企業の前提に重要な疑義を公表した場合は、通常損切とは別に投資前提を再評価する。']
    earnings=facts.get('earnings',{})
    if earnings.get('scheduled_at'):
        meta.update(earnings_at=earnings['scheduled_at'],earnings_evidence_ids=earnings['evidence_ids'])
    # A list of headlines is not independent confirmation of the absence of bad news.
    meta.setdefault('preflight_review',{}).setdefault('negative_news',dict(reviewed=False,evidence_ids=facts.get('disclosures',{}).get('evidence_ids',[]),reason='開示一覧は取得済み。原文全体・社外材料の重大性確認は未完了。'))
    meta['automatic']['assessment_provider']='program:public-facts-v1'
    meta['automatic']['qualitative_provider']='unconfigured'


def technical_assessments(bundle, tech, cfg, horizon, plan=None):
    if not bundle.metadata.get('automatic'): return {}
    out={};ref=tech['technical_evidence_id'];refs=[ref]
    def put(code,value,reason,counter='確定した過去データの評価。将来の約定・継続は保証しない。',sources=None):
        out[code]=dict(score=value,reason=reason,counter_reason=counter,evidence_ids=sources or refs,evaluator='program',rule_version='cards-1.0.0')
    def participation(frame,window):
        if len(frame)<window+1: return None
        changes=frame.close.diff();sample=frame.tail(window);direction=changes.tail(window)
        up=sample.loc[direction>0,'volume'];down=sample.loc[direction<0,'volume']
        if up.empty or down.empty: return None
        a,b=float(up.mean()),float(down.mean())
        return (8 if a>b else 4 if a<b else 6),f'上昇足平均出来高={a:.0f}、下落足平均出来高={b:.0f}（直近{window}本、同値足は方向比較外）'
    daily,weekly=tech['daily'],tech['weekly']
    if horizon=='swing':
        relative=relative_strength(bundle,tech,cfg)
        if relative: put('SW-D3',**relative)
        for code,frame in (('SW-D4',weekly),('SW-E1',daily)):
            result=participation(frame,cfg['comparison_days'])
            if result: put(code,*result)
        check=bundle.metadata.get('preflight_review',{}).get('liquidity',{})
        if check.get('reviewed') and check.get('anchor') is not None:
            put('SW-E4',check['anchor'],check['reason'],sources=check['evidence_ids'])
        credit=bundle.metadata.get('public_facts',{}).get('credit',{})
        if credit and credit.get('buy',0)>0:
            day=time_value(credit['buy_observed_at']).astimezone(daily.index.tz).date()
            p=daily.loc[[x.date()<=day for x in daily.index]]
            prior=p.loc[[x.date()<=day-timedelta(days=7) for x in p.index]]
            if len(p) and len(prior):
                change=float(p.iloc[-1].close-prior.iloc[-1].close)
                if credit['buy_change']>0 and change<0:
                    put('SW-E2',4,'同じ信用観測週で買残増加かつ株価下落。買い方の負担増を確認。','空売り意図・将来の投げ売りは推定しない。',refs+credit['evidence_ids'])
                elif credit['buy_change']<0 and change>0:
                    put('SW-E2',8,'同じ信用観測週で買残減少かつ株価上昇。整理進行を確認。','整理後の継続上昇は保証しない。',refs+credit['evidence_ids'])
    else:
        ps=tech['pivots'].get('1w',[]);highs=[p['price'] for p in ps if p['kind']=='high'];lows=[p['price'] for p in ps if p['kind']=='low']
        if tech['weekly_count']>=cfg['weekly_min'] and len(highs)>=2 and len(lows)>=2:
            up=highs[-1]>highs[-2] and lows[-1]>lows[-2];down=highs[-1]<highs[-2] and lows[-1]<lows[-2]
            persistent=len(highs)>=3 and len(lows)>=3 and highs[-2]>highs[-3] and lows[-2]>lows[-3]
            value=10 if up and persistent and tech['weekly_trend']=='上昇' else 8 if up else 4 if down or tech['weekly_trend']=='下降' else 6
            if down and tech['weekly_trend']=='下降' and float(daily.iloc[-1].close)<lows[-1]: value=1
            put('ML-I',value,f"確定週足の高安={highs[-3:]}/{lows[-3:]}、13/26/52週線の大局={tech['weekly_trend']}。月足は必須にしない。")
        if plan and plan.kind=='現値':
            band=next((b for b in tech['bands'] if b.band_id==plan.support_id),None);atr=tech['atr']
            if band and atr:
                distance=float(plan.entry-plan.stop1)/atr
                put('ME-B',8 if band.primary and distance<=cfg['support_distance_atr'][1] else 6 if distance<=cfg['support_distance_atr'][2] else 4,f'週足支持={band.low}〜{band.high}、通常無効化={plan.stop1}、週ATR比距離={distance:.3f}')
                resistance=[b for b in tech['bands'] if b.low>float(plan.entry) and b.strength>=cfg['strong_band']]
                near_resistance=bool(resistance and min(b.low for b in resistance)-float(plan.entry)<=2*atr)
                near_support=float(plan.entry)-band.high<=2*atr
                put('ME-A',4 if near_resistance else 8 if near_support else 6,f'週足上の位置：有力抵抗近接={near_resistance}、採用支持近接={near_support}。')
            put('ME-F',8 if plan.trigger_confirmed else 4 if tech['rsi'] is not None and tech['rsi']>=cfg['rsi_overheated'] else 6,f"確定日足トリガー={plan.trigger_confirmed}、RSI={tech['rsi']}。")
    return out


def missing_reason(code, facts):
    if code.startswith(('SC-','MC-')): return '定性解釈・反証評価が必要。AI Provider未接続（事実の代用点は付けない）'
    if code in ('SE-G','SW-H','ME-G'): return facts.get('earnings',{}).get('description','次回決算予定を取得できない')+'／確定予定と跨ぐ・待つ影響比較が不足'
    if code in ('SW-D3','SW-J','ML-J'): return '同時点・同期間の比較対象と選定根拠が未取得'
    if code in ('SW-F','ML-G'): return 'セクター・為替値だけでは企業感応度と個別材料の支配比較を確定できない'
    if code in ('SW-I','ML-H','ME-C'): return 'PER/PBRは取得しても、業種適合・過去／同業比較・保守的評価レンジが未取得'
    if code in ('ME-E','ME-E-STRESS'): return '過去の価格飛びだけではイベント反証を含むストレス下落の妥当性を確定できない'
    if code=='SW-E3': return '公表信用残だけでは空売り意図・踏み上げ材料を確定できない'
    return '必須Evidenceの不足、または取得資料だけでは正本アンカーの成立条件を客観確定できない'


def apply_qualitative(bundle, provider):
    """AssessmentProvider may only return ai_bridge's allowed context anchors."""
    if provider is None: return
    from .ai_bridge import export_request, import_response
    from .models import plain, InputError
    selected=[k for k,e in bundle.evidence.items() if e.source_type=='public' and k.startswith(('facts-','public-','jpx-'))]
    request=export_request(bundle.symbol,bundle.as_of,plain(bundle.evidence),selected)
    values=provider.assess({k:bundle.evidence[k] for k in selected},request['cards'],bundle.as_of)
    if not isinstance(values,list): raise InputError('定性Providerは定義済みアンカーの配列だけを返してください。')
    response={'request_id':request['request_id'],'assessments':values}
    checked=import_response(response,request)
    existing={r['criterion_id'] for r in bundle.metadata.get('assessments',[])}
    if any(r['criterion_id'] in existing for r in checked): raise InputError('定性カードが重複しています。')
    bundle.metadata.setdefault('assessments',[]).extend(checked)
    bundle.metadata['automatic']['qualitative_provider']='validated:ai_bridge'


def relative_strength(bundle, tech, cfg):
    import pandas as pd
    from .technical import weekly_bars
    bench=bundle.metadata.get('public_facts',{}).get('benchmark',{})
    bars=bench.get('bars',[])
    if not bars or {r['adjustment_basis'] for r in bars}!={r['adjustment_basis'] for r in bundle.bars}: return None
    frame=pd.DataFrame(bars);frame.index=pd.to_datetime(frame.pop('timestamp'),utc=True).dt.tz_convert(tech['weekly'].index.tz)
    bw=weekly_bars(frame[['open','high','low','close','volume']],bundle.as_of,bundle.metadata.get('calendar',[]))
    sw=tech['weekly'];values=[]
    if len(sw)<16: return None
    for offset in (1,2,3):
        end=sw.index[-offset];row=[]
        for window in (4,13):
            start=sw.index[-offset-window]
            if start not in bw.index or end not in bw.index: return None
            row.append(float(100*((sw.loc[end,'close']/sw.loc[start,'close']-1)-(bw.loc[end,'close']/bw.loc[start,'close']-1))))
        values.append(row)
    current=values[0];positive=all(x>0 for x in current);negative=all(x<0 for x in current)
    persistent=all(x>0 for row in values for x in row)
    worsening=negative and all(a<b for a,b in zip(values[0],values[1]))
    improving=all(a>b>c for a,b,c in zip(*values))
    value=10 if persistent and improving and tech['weekly_trend']=='上昇' else 1 if worsening else 8 if positive else 4 if negative else 6
    return dict(value=value,reason=f"{bench['purpose']}：直近から3観測点の4週/13週差（%pt）={values}。同じ調整基準・開始日・終了日で比較。",counter='ETFの分配金・追随誤差は残る。企業価値・同業優位の証明には流用しない。',sources=[tech['technical_evidence_id']]+bench['evidence_ids'])
