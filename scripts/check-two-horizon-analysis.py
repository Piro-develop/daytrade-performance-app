"""Read-only live engine verification. No Firebase or personal data is touched."""
from pathlib import Path
import json,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'investment/src'))
from judgment.service import JudgmentService
from decimal import Decimal

class MemoryStore:
    uid='verification'
    def save_group(self,pending):self.pending=pending

for code in ('4461','7203'):
    memory=MemoryStore();out=JudgmentService(store=memory).automatic('verification',{'symbol':code})
    assert out['saved'] and set(out['results'])=={'swing','midlong'}
    assert not any('5分' in x or 'デイトレ' in x for x in out['missing'])
    for horizon,r in out['results'].items():
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
        evaluated=[k for k,v in first['items'].items() if v.get('score') is not None]
        if code=='4461':
            assert 'unchecked_liquidity' not in {f['code'] for f in r['findings']}
            assert ('SW-E4' if horizon=='swing' else 'ML-I') in evaluated
            assert any(x['present'] and x['S']>0 and x['F']>0 for x in r['confidence']['items'])
        print(json.dumps({'symbol':code,'horizon':horizon,'evaluated':evaluated,'missing':first['missing'],
            'preflight':[f['code'] for f in r['findings']],'daily':len(r['technical']['daily']),
            'weekly':r['technical']['weekly_count'],'confidence':r['confidence']['value'],
            'scores':{k:{s:v[s] for s in ('investment','entry')} for k,v in r['scores'].items()},
            'plans':[{k:p[k] for k in ('entry','target1','target2','alert','stop1','stop2','rr')} for p in r['plans']],
            'missing_plan':not bool(r['plans'])},ensure_ascii=True),flush=True)
