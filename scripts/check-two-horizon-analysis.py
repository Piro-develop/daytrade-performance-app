"""Read-only live engine verification. No Firebase or personal data is touched."""
from pathlib import Path
import json,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'investment/src'))
from judgment.automatic import acquire
from app_server import create_app
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'investment/tests'))
from test_firestore_judgment import FakeFirestore, store
from test_production_judgment import call, TestIdentity
from decimal import Decimal

for code in ('4461','7203'):
    acquired=acquire(code)
    db=FakeFirestore()
    app=create_app(identity=TestIdentity(),store_factory=lambda uid,token:store(db,uid))
    with patch('judgment.automatic.acquire',return_value=acquired):
        status,out=call(app,'/api/judgment/automatic','POST','alice',{'symbol':code})
    assert status==200 and db.commits==1
    assert out['saved'] and set(out['results'])=={'swing','midlong'}
    assert not any('5分' in x or 'デイトレ' in x for x in out['missing'])
    for horizon,r in out['results'].items():
        saved=store(db).get(r['run_id'])
        assert all(saved[k]==v for k,v in r.items() if k!='presentation')
        assert r['technical']['weekly_count']>=58
        assert 0<=r['confidence']['value']<=100
        assert all(not row['criterion_id'].startswith(('DT-','DE-','DC-')) for row in r['confidence']['items'])
        assert not any('intraday' in f['code'] for f in r['findings'])
        for p in r['plans']:
            entry,stop,target=map(Decimal,(str(p['entry']),str(p['stop1']),str(p['target1'])))
            assert stop<entry<target
            assert abs(Decimal(str(p['rr']))-(target-entry)/(entry-stop))<Decimal('.000001')
            assert all(k in p for k in ('target2','alert','stop2'))
            if p['target2'] is not None: assert Decimal(str(p['target2']))>=target
            if p['stop2'] is not None: assert Decimal(str(p['stop2']))<stop
        first=next(iter(r['scores'].values()))
        assert first['entry'] is not None if horizon=='swing' else True
        assert first['investment'] is not None if first['coverage']>=.6 and not any(f['severity']=='Critical' and f['scope'] in ('all','investment') for f in r['findings']) else first['investment'] is None
        assert all(f['severity']=='Warning' for f in r['findings'] if f['code'].startswith('unchecked_'))
        assert not any(c.startswith(('SC-','MC-')) for c in first['missing'])
        evaluated=[k for k,v in first['items'].items() if v.get('score') is not None]
        if code=='4461':
            assert 'unchecked_liquidity' not in {f['code'] for f in r['findings']}
            assert ('SW-E4' if horizon=='swing' else 'ML-I') in evaluated
            assert any(x['present'] and x['S']>0 and x['F']>0 for x in r['confidence']['items'])
        print(json.dumps({'symbol':code,'horizon':horizon,'evaluated':evaluated,'missing':first['missing'],
            'preflight':r['findings'],'daily':len(r['technical']['daily']),
             'weekly':r['technical']['weekly_count'],'confidence':r['confidence']['value'],
            'confidence_components':r['confidence']['components'],
            'evidence_quality':[v for v in r['confidence']['items'] if v['present']],
            'qualitative_provider':r['metadata']['automatic']['qualitative_provider'],
            'earnings':acquired['metadata'].get('public_facts',{}).get('earnings',{}),
            'score_gaps':r['metadata']['automatic']['card_gaps'],
            'decisions':{k:{s:v[s] for s in ('label','status','wait_reasons')} for k,v in r['decisions'].items()},
            'scores':{k:{s:v[s] for s in ('structured','context','investment','entry','coverage','entry_coverage','status','entry_status')} for k,v in r['scores'].items()},
            'plans':[{k:p[k] for k in ('entry','target1','target2','alert','stop1','stop2','rr')} for p in r['plans']],
            'missing_plan':not bool(r['plans'])},ensure_ascii=True),flush=True)
