"""Two-horizon regression: minute data never affects scoring, confidence or holds."""
import copy
from datetime import timedelta
from decimal import Decimal
import pytest
from investment_app.config import load_config
from investment_app.horizons import all_cards,analyze_horizon,horizon_cards,horizon_technical,score_horizon
from investment_app.models import InputError,time_value
from investment_app.preflight import confidence
from investment_app.scoring import catalog
from investment_app.entry_exit import make_plan
from investment_app.uat_service import demo,bundle_from_input,run_all,recommendation


def bundle():
    raw,meta=demo()
    return bundle_from_input(raw,meta,meta['symbol'],meta['as_of'])


class MemoryStore:
    def save_group(self,pending):self.pending=pending


def test_two_horizons_ignore_legacy_minute_metadata_completely():
    original=bundle();legacy=copy.deepcopy(original)
    legacy.metadata.update(intraday_bars=[{'close':None,'timestamp':'future'}],intraday_interval='5m',intraday_closed_confirmed=False)
    first=run_all(original,MemoryStore());second=run_all(legacy,MemoryStore())
    assert set(first)==set(second)=={'swing','midlong'}
    for h in first:
        assert first[h]['confidence']['value']==second[h]['confidence']['value']
        assert first[h]['confidence']['components']==second[h]['confidence']['components']
        for kind,score in first[h]['scores'].items():
            for key in ('investment','entry','structured','context','status','entry_status','missing'):
                assert score[key]==second[h]['scores'][kind][key]
        assert [(f['code'],f['reason']) for f in first[h]['findings']]==[(f['code'],f['reason']) for f in second[h]['findings']]
        assert not any(x['criterion_id'].startswith(('DT-','DE-','DC-')) for x in first[h]['confidence']['items'])
    with pytest.raises(InputError):analyze_horizon(original,load_config(),'daytrade')
    assert recommendation({'daytrade':first['swing']})==[]


def test_monthly_is_optional_weekly_is_primary_and_weights_unchanged():
    b=bundle();cfg=load_config();t=horizon_technical(b,cfg,'midlong')
    assert t['monthly'].empty and t['weekly_count']>=cfg['weekly_min']
    assert all(level['timeframe']=='1w' for level in t['levels'])
    assert all(f'ma{x}' in t['weekly'] for x in (13,26,52))
    assert all(f'ma{x}' in t['daily'] for x in (13,25,50,75))
    plan=make_plan(1000,1100,950,evidence_ids=(t['technical_evidence_id'],),trigger_confirmed=True)
    scored=score_horizon(b,t,plan,cfg,'midlong')
    assert scored.investment==8 and scored.items['ML-I']['score']==8
    b.metadata['include_monthly']=True
    assert not horizon_technical(b,cfg,'midlong')['monthly'].empty
    assert len(all_cards())==55


def test_complete_required_evidence_can_have_high_confidence_without_minutes():
    b=bundle();ref='demo-financial'
    b.metadata['evidence_quality']={ref:{'valid_until':(time_value(b.as_of)+timedelta(days=1)).isoformat(),'source_quality':'original_verified'}}
    for cards in (catalog(),horizon_cards('midlong')):
        items={code:{'score':8,'evidence_ids':[ref]} for code in cards}
        quality=confidence(b,[],items,cards)
        assert quality['value']==92.5 and quality['ratios']['C']==1
        assert not any(row['criterion_id'].startswith(('DT-','DE-','DC-')) for row in quality['items'])
