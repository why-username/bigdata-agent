from __future__ import annotations
import json,os,statistics
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0,str(ROOT))
os.environ['AGENT_DATA_DIR']=str(ROOT/'data/eval/v3_candidates')
from agent.core import run_investigation,DataStore
from agent.evaluation import dynamic_decision_metrics,decision_quality_score,citations_are_verifiable

def main():
 wanted={c['case_id'] for c in json.loads((ROOT/'data/eval/v3_candidate_manifest.json').read_text())[:4]}
 base=json.loads((ROOT/'data/eval/research_v3_tasks.json').read_text())
 available={c['case_id'] for c in DataStore().cases()}
 tasks=[t for t in base['tasks'] if t['case_id'] in wanted and t['case_id'] in available]
 if not tasks:
  scenarios=[('empty_recovery','retrieve_evidence'),('source_conflict','link_entities'),('competing_hypotheses','retrieve_evidence'),('evidence_sufficiency','done'),('cutoff_leakage','done'),('followup_gap','create_followup')]
  cases={c['case_id']:c for c in json.loads((ROOT/'data/eval/v3_candidate_manifest.json').read_text()) if c['case_id'] in available}
  tasks=[{'task_id':f'V3-{cid}-{i:02d}','case_id':cid,'cutoff_date':c['replay_cutoff'],'goal':name,'scenario':name,'gold_next_action':gold,'focus':name} for cid,c in cases.items() for i,(name,gold) in enumerate(scenarios,1)]
 store=DataStore(); rows=[]
 for t in tasks:
  state=run_investigation(t['case_id'],t['goal'],cutoff_date=t['cutoff_date'],mode='active_eig',focus=t['scenario'],dynamic_scenario=t['scenario'])
  citation=citations_are_verifiable(state.get('evidence_ledger',[]),store,t['case_id'],t['cutoff_date'])
  rows.append({'task_id':t['task_id'],'case_id':t['case_id'],'scenario':t['scenario'],'status':state['status'],'passed':citation,'dynamic_metrics':dynamic_decision_metrics(state,t),'decision_value_v3':decision_quality_score(state,t,citation),'tool_calls':state['usage']['tool_calls'],'errors':state.get('errors',[])})
 out={'suite':'research_v3_dynamic_offline','task_count':len(rows),'passed_count':sum(r['passed'] for r in rows),'rows':rows}
 path=ROOT/'outputs/evaluations/eval-research_v3-dynamic-offline.json'; path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
 from collections import defaultdict
 by=defaultdict(list)
 for r in rows: by[r['scenario']].append(r['dynamic_metrics']['branch_correct'])
 print(json.dumps({'output':str(path),'task_count':len(rows),'passed_count':out['passed_count'],'branch_accuracy':{k:round(statistics.mean(v),3) for k,v in by.items()}},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
