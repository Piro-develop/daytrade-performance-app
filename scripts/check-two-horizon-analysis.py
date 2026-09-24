"""Read-only live engine verification. No Firebase or personal data is touched."""
from pathlib import Path
import json,sys,argparse,copy,subprocess,types
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'investment/src'))
from judgment.automatic import acquire
from app_server import create_app
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'investment/tests'))
from test_firestore_judgment import FakeFirestore, store
from test_production_judgment import call, TestIdentity
from decimal import Decimal

parser=argparse.ArgumentParser()
parser.add_argument("symbols",nargs="*",default=["4461","7203"])
parser.add_argument("--compare-entry-base")
args=parser.parse_args()
baseline=None
if args.compare_entry_base:
    source=subprocess.check_output(["git","show",args.compare_entry_base+":investment/src/investment_app/entry_exit.py"],text=True)
    baseline=types.ModuleType("investment_app._entry_baseline")
    exec(compile(source,"baseline_entry_exit.py","exec"),baseline.__dict__)

for code in args.symbols:
    acquired=acquire(code)
    db=FakeFirestore()
    app=create_app(identity=TestIdentity(),store_factory=lambda uid,token:store(db,uid))
    with patch('judgment.automatic.acquire',side_effect=lambda _:copy.deepcopy(acquired)):
        status,out=call(app,'/api/judgment/automatic','POST','alice',{'symbol':code})
    assert status==200 and db.commits==1
    assert out['saved'] and set(out['results'])=={'swing','midlong'}
    assert not any('5分' in x or 'デイトレ' in x for x in out['missing'])
    previous=None
    if baseline:
        olddb=FakeFirestore()
        oldapp=create_app(identity=TestIdentity(),store_factory=lambda uid,token:store(olddb,uid))
        with patch('judgment.automatic.acquire',side_effect=lambda _:copy.deepcopy(acquired)), \
             patch('investment_app.application.plans_for',baseline.plans_for), \
             patch('investment_app.horizons.plans_for',baseline.plans_for):
            oldstatus,previous=call(oldapp,'/api/judgment/automatic','POST','alice',{'symbol':code})
        assert oldstatus==200
    for horizon,r in out['results'].items():
        if previous:
            prior=previous['results'][horizon]
            old_current=next((p for p in prior['plans'] if p['kind'] in ('現値','指定価格')),None)
            new_current=next((p for p in r['plans'] if p['kind'] in ('現値','指定価格')),None)
            assert bool(old_current)==bool(new_current)
            if old_current:
                fields=('entry','target1','target2','stop1','stop2','alert','rr','trigger_confirmed')
                assert {k:old_current[k] for k in fields}=={k:new_current[k] for k in fields}
            print(json.dumps({'current_plan_unchanged':True,'symbol':code,'horizon':horizon,'as_of':r['as_of']},ensure_ascii=True),flush=True)
        assert len(r['plans'])<=3
        pullbacks=[p for p in r['plans'] if p['kind'] in ('第1押し目','第2押し目')]
        assert len({p['support_id'] for p in pullbacks})==len(pullbacks)
        for p in pullbacks:
            assert p['support_basis'] and Decimal(str(p['stop1']))<Decimal(str(p['support_low']))
            assert Decimal(str(p['entry']))<Decimal(str(r['plans'][0]['entry'])) if r['plans'][0]['kind']=='現値' else True
        if len(pullbacks)==2: assert Decimal(str(pullbacks[1]['entry']))<Decimal(str(pullbacks[0]['entry']))

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
        assert first['entry'] is not None and first['entry_coverage']>=.6
        assert first['investment'] is not None and 0<first['coverage']<=1
        assert r['metadata']['screening']['label'] in ('通過','要確認','非通過')
        assert r['metadata']['screening']['chatgpt_checks']
        assert not any('AI' in f['reason'] for f in r['findings'])
        assert all(f['severity']=='Warning' for f in r['findings'] if f['code'].startswith('unchecked_'))
        assert not any(c.startswith(('SC-','MC-')) for c in first['missing'])
        evaluated=[k for k,v in first['items'].items() if v.get('score') is not None]
        if code=='4461':
            assert 'unchecked_liquidity' not in {f['code'] for f in r['findings']}
            assert ('SW-E4' if horizon=='swing' else 'ML-I') in evaluated
            assert any(x['present'] and x['S']>0 and x['F']>0 for x in r['confidence']['items'])
        print(json.dumps({'symbol':code,'horizon':horizon,'screening':r['metadata']['screening'],'evaluated':evaluated,'missing':first['missing'],
            'preflight':r['findings'],'daily':len(r['technical']['daily']),
             'weekly':r['technical']['weekly_count'],'confidence':r['confidence']['value'],
            'confidence_components':r['confidence']['components'],
            'evidence_quality':[v for v in r['confidence']['items'] if v['present']],
            'qualitative_provider':r['metadata']['automatic']['qualitative_provider'],
            'earnings':acquired['metadata'].get('public_facts',{}).get('earnings',{}),
            'score_gaps':r['metadata']['automatic']['card_gaps'],
            'decisions':{k:{s:v[s] for s in ('label','status','wait_reasons')} for k,v in r['decisions'].items()},
            'scores':{k:{s:v[s] for s in ('structured','context','investment','entry','coverage','entry_coverage','status','entry_status')} for k,v in r['scores'].items()},
            'plans':[{k:p.get(k) for k in ('kind','entry','target1','target2','alert','stop1','stop2','rr','support_low','support_high','support_basis','rr_evaluation')} for p in r['plans']],
            'missing_plan':not bool(r['plans'])},ensure_ascii=True),flush=True)
