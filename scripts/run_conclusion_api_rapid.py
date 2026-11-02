import json,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from agent.core import run_investigation,DataStore
from agent.evaluation import citations_are_verifiable
base=ROOT/'data/eval/conclusion_holdout'; gold=json.loads((base/'gold_answers.json').read_text()); rows=[]
for cid,g in gold.items():
 os.environ['AGENT_DATA_DIR']=str(base/f'{cid}_bundle'); b=base/f'{cid}_bundle';b.mkdir(exist_ok=True)
 for name in ['cases','records','evidence']:(b/f'{name}.json').write_text((base/f'{cid}_{name}.json').read_text())
 os.environ['AGENT_DATA_DIR']=str(b); store=DataStore(); goal=f"在 {g['pre_cutoff']} 截点前判断 {cid} 是否存在可支持的安全缺陷线索，提出最可能机制、替代解释和下一步核查。不能使用截点后材料。"
 s=run_investigation(cid,goal,cutoff_date=g['pre_cutoff'],mode='api',focus='counterevidence',dynamic_scenario='competing_hypotheses'); cv=citations_are_verifiable(s.get('evidence_ledger',[]),store,cid,g['pre_cutoff']); rows.append({'case_id':cid,'status':s['status'],'passed':cv,'completion_note':s.get('completion_note'),'hypotheses':s.get('hypotheses'),'claims':s.get('claims'),'evidence_ids':[x.get('evidence_id') for x in s.get('evidence_ledger',[])],'errors':s.get('errors',[]),'gold':g})
out={'suite':'rapid_conclusion_holdout_api','task_count':len(rows),'rows':rows};p=ROOT/'outputs/evaluations/rapid-conclusion-holdout-api.json';p.write_text(json.dumps(out,ensure_ascii=False,indent=2));print(json.dumps({'output':str(p),'rows':rows},ensure_ascii=False))
