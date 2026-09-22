"""Focused regressions for the formerly disconnected symbol-only path."""
import copy
from dataclasses import replace
from datetime import timedelta
from judgment.public_facts import financial_table, revision_table
from investment_app.automatic_assessment import prepare_automatic, apply_qualitative
from investment_app.models import InputError, time_value
from investment_app.uat_service import demo, bundle_from_input, run_all
import pytest

class Store:
    def save_group(self,pending): self.pending=pending


def test_public_facts_reach_cards_preflight_confidence_and_decision():
    raw,meta=demo();meta['assessments']=[];meta['preflight_review']={};meta['evidence_quality']={}
    meta.pop('latest_financial',None);meta.pop('earnings_at',None);meta['macro']={}
    # Controlled fixture, explicitly not real-company observations.
    fref='demo-financial';forecast={'period':'2027年3月期','sales':97000,'operating':12500,'ordinary':12600,'net':7700,'eps':725.67,'operating_yoy':23.7}
    financial=dict(latest_confirmed=True,period='2027年3月期第1四半期',evidence_ids=[fref],going_concern_no_issue=True,
      current={'eps':293.7,'operating_margin':18.60,'operating_yoy':196.9,'sales':27501,'operating':5117},previous={'eps':102.81,'operating_margin':9.04,'operating_yoy':62.8,'sales_yoy':8.6,'net_yoy':61.7,'sales':19046,'operating':1723},forecast=forecast)
    b=bundle_from_input(raw,meta,meta['symbol'],meta['as_of']);base=run_all(copy.deepcopy(b),Store())
    price='public-daily-fixture';market=b.evidence[b.metadata['market_evidence_id']]
    b.evidence[price]=replace(market,evidence_id=price,source_type='public',source_uri='https://example.invalid/verified-daily')
    b.metadata.update(automatic={'notices':[],'price_evidence_id':price},public_facts={'financial':financial,'revision':{'period':forecast['period'],'previous':[84000,11000,11000,6700,631.42],'current':[97000,12500,12600,7700,725.67],'evidence_ids':[fref]}})
    b.metadata['evidence_quality'][fref]={'valid_until':(time_value(b.as_of)+timedelta(days=1)).isoformat(),'source_quality':'original_verified','unresolved_conflict':False}
    benchmark='public-daily-benchmark-fixture'
    b.evidence[benchmark]=replace(b.evidence[price],evidence_id=benchmark,source_uri='https://example.invalid/benchmark')
    b.metadata['public_facts']['benchmark']={'bars':[dict(row,open=100,high=101,low=99,close=100,volume=1000) for row in b.bars],'evidence_ids':[benchmark],'purpose':'架空比較系列'}
    prepare_automatic(b);apply_qualitative(b,None);out=run_all(b,Store())
    assert {r['criterion_id'] for r in b.metadata['assessments']}=={'SW-A3','ML-A','ML-D'}
    for h,r in out.items():
        s=next(iter(r['scores'].values()));before=next(iter(base[h]['scores'].values()))
        assert len(s['missing'])<len(before['missing'])
        codes={f['code'] for f in r['findings']}
        assert 'unchecked_liquidity' not in codes and 'unchecked_thesis' not in codes
        assert 'unchecked_negative_news' in codes
        assert r['confidence']['value']>base[h]['confidence']['value']
        assert s['investment'] is None and s['context'] is None
        assert not any(v['label'] in ('買い','強気買い') for v in r['decisions'].values())
        assert r['metadata']['automatic']['card_gaps']
    sw=next(iter(out['swing']['scores'].values()))
    assert sw['items']['SW-D3']['score'] in (1,4,6,8,10)
    assert sw['items']['SW-A3']['score']==8 and 'SW-A1' in sw['missing']
    assert next(x for x in out['swing']['confidence']['items'] if x['criterion_id']=='SW-A3')['S']==1
    ml=next(iter(out['midlong']['scores'].values()))
    assert ml['items']['ML-A']['score']==8 and ml['items']['ML-I']['score'] is not None
    # Existing bridge rejects attempts to let AI create structured scores.
    class BadProvider:
        def assess(self,*args): return [{'criterion_id':'SW-A1','anchor_id':'8','evidence_ids':[price],'reason':'x','counter_reason':'y'}]
    with pytest.raises(InputError): apply_qualitative(b,BadProvider())


def test_financial_table_preserves_periods_units_and_revision_comparison():
    text='''2027年3月期 第1四半期 決算短信 日本基準 連結 百万円 売上高 営業利益 経常利益
2027年3月期第1四半期 27,501 44.4 5,117 196.9 5,228 209.5 3,116 216.5
2026年3月期第1四半期 19,046 8.6 1,723 62.8 1,689 41.4 984 61.7
2027年3月期第1四半期 293.70 －
2026年3月期第1四半期 102.81 －
通期 97,000 17.0 12,500 23.7 12,600 21.5 7,700 24.8 725.67'''
    f=financial_table([text]);assert f['current']['eps']==293.70 and f['current']['sales']==27501
    revision='''2027年3月期 通期
前 回 発 表 予 想 ( A ) 84,000 11,000 11,000 6,700 631.42
今 回 修 正 予 想 ( B ) 97,000 12,500 12,600 7,700 725.67'''
    assert revision_table(revision,f['forecast'])['previous'][1]==11000
    assert financial_table([text.replace('2026年3月期第1四半期','2026年3月期第2四半期')])=={}
    assert revision_table(revision.replace('12,500','12,600'),f['forecast'])=={}


def test_missing_event_invalidates_only_event_cards_and_saved_gaps():
    raw,meta=demo();meta['automatic']={'missing':['obsolete fixed message']}
    before=run_all(bundle_from_input(raw,meta,meta['symbol'],meta['as_of']),Store())
    meta.pop('earnings_at')
    after=run_all(bundle_from_input(raw,meta,meta['symbol'],meta['as_of']),Store())
    for horizon,event_cards in (('swing',{'SW-H','SE-G'}),('midlong',{'ME-G'})):
        r=after[horizon];score=r['scores']['現値'];old=before[horizon]['scores']['現値']
        for code in event_cards:
            assert score['items'][code]['score'] is None and code in score['missing']
        for code,item in old['items'].items():
            if code not in event_cards:
                assert {k:v for k,v in score['items'][code].items() if k!='evidence_ids'}=={k:v for k,v in item.items() if k!='evidence_ids'}
                assert all(ref in r['evidence'] for ref in score['items'][code]['evidence_ids'])
        assert score['context']==old['context']
        assert score['entry'] is not None and score['entry_coverage']==.95
        assert score['investment'] is not None
        assert score['coverage']==(.96 if horizon=='swing' else 1)
        if horizon=='midlong': assert score['investment']==old['investment']
        auto=r['metadata']['automatic']
        assert 'obsolete fixed message' not in auto['missing']
        assert set(auto['card_gaps'])==set(score['missing'])
        assert set(auto['card_gaps_by_plan'])==set(r['scores'])
        assert all(d['label'] not in ('買い','強気買い') for d in r['decisions'].values())


def test_coverage_thresholds_optional_context_and_critical_scope():
    from investment_app.config import load_config
    from investment_app.scoring import weighted_available, aggregate_investment
    from investment_app.application import earnings_info
    cfg=load_config()
    value,cov,gaps=weighted_available({'a':{'score':8},'b':{'score':None}},{'a':60,'b':40})
    assert (value,cov,gaps)==(8,.6,['b'])
    items={f'SW-{k}':{'score':8} for k in ('B','C','F','G','H','I','J')}
    items['SW-A3']={'score':4} # 20% * 20% = 4%; total covered = 60%.
    structured,context,total,missing,cov=aggregate_investment(items,cfg)
    assert cov==.6 and total==pytest.approx((56*8+4*4)/60) and context is None
    items.pop('SW-A3');assert aggregate_investment(items,cfg)[2] is None
    items.update({f'SC-{i}':{'score':10} for i in range(1,7)})
    assert aggregate_investment(items,cfg)[2] is None # AI never repairs low coverage.
    raw,meta=demo();meta['assessments']=[x for x in meta['assessments'] if not x['criterion_id'].startswith(('SC-','MC-'))]
    meta['preflight_review']={};meta.pop('earnings_at')
    b=bundle_from_input(raw,meta,meta['symbol'],meta['as_of']);out=run_all(b,Store())
    for r in out.values():
        score=r['scores']['現値']
        assert score['investment'] is not None and score['entry'] is not None and score['context'] is None
        assert all(f['severity']=='Warning' for f in r['findings'] if f['code'].startswith('unchecked_'))
        assert r['decisions']['現値:avoid']['label'] is not None
        assert r['decisions']['現値:avoid']['status']=='暫定評価'
    b.metadata.pop('latest_financial');held=run_all(b,Store())
    assert all(r['scores']['現値']['investment'] is None and r['scores']['現値']['entry'] is not None for r in held.values())
    assert earnings_info(b,'avoid')['state']=='unknown'
    b.metadata['earnings_window']={'no_earnings':True,'evidence_ids':['demo-financial'],'checked_at':b.as_of,
        'confirmed_through':(time_value(b.as_of)+timedelta(days=30)).isoformat()}
    assert earnings_info(b,'avoid')['state']=='none_within_30_days'
    b.metadata['earnings_window']['evidence_ids']=[]
    assert earnings_info(b,'avoid')['state']=='unknown'
