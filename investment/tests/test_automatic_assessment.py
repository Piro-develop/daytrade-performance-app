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
      current={'eps':293.7,'operating_margin':18.60,'operating_yoy':196.9},previous={'eps':102.81,'operating_margin':9.04,'operating_yoy':62.8,'sales_yoy':8.6,'net_yoy':61.7},forecast=forecast)
    b=bundle_from_input(raw,meta,meta['symbol'],meta['as_of']);base=run_all(copy.deepcopy(b),Store())
    price='public-daily-fixture';market=b.evidence[b.metadata['market_evidence_id']]
    b.evidence[price]=replace(market,evidence_id=price,source_type='public',source_uri='https://example.invalid/verified-daily')
    b.metadata.update(automatic={'notices':[],'price_evidence_id':price},public_facts={'financial':financial,'revision':{'period':forecast['period'],'previous':[84000,11000,11000,6700,631.42],'current':[97000,12500,12600,7700,725.67],'evidence_ids':[fref]}})
    b.metadata['evidence_quality'][fref]={'valid_until':(time_value(b.as_of)+timedelta(days=1)).isoformat(),'source_quality':'original_verified','unresolved_conflict':False}
    prepare_automatic(b);apply_qualitative(b,None);out=run_all(b,Store())
    assert {r['criterion_id'] for r in b.metadata['assessments']}=={'SW-A3','ML-A'}
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
