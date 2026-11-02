from __future__ import annotations
import json,statistics,collections
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
api=json.loads((ROOT/'outputs/evaluations/eval-v4-api-pilot.json').read_text())['rows']
off=json.loads((ROOT/'outputs/evaluations/eval-v4-dynamic-comparison-offline.json').read_text())['rows']
api_by={r['task_id']:r for r in api}; off_by={r['task_id']:r for r in off}
# Map V4 task IDs to the prior offline comparison IDs. Each row has the same case/scenario.
rows=[]
for ar in api:
 tid=ar['task_id']; base=off_by.get(tid)
 if not base:
  continue
 scenario=ar['scenario']
 expected={'empty_recovery':{'retrieve_evidence','search_records'},'source_conflict':{'link_entities','retrieve_evidence'},'competing_hypotheses':{'retrieve_evidence'},'evidence_sufficiency':{'done'},'cutoff_leakage':{'done'},'followup_gap':{'create_followup'}}.get(scenario,set())
 def baseline(name):
  b=base[name]; calls=b.get('tool_calls',0); first=None
  if name=='fixed': first='search_records'
  elif name=='rag': first='retrieve_evidence'
  elif name=='react': first=(b.get('dynamic') or {}).get('first_action')
  branch=int(first in expected)
  # Baselines have no model state; score only observable safe/tool evidence behavior.
  evidence_quality=min(1.0,b.get('evidence_count',0)/2) if b.get('evidence_count',0) else 0.0
  goal=branch
  nextv=int(scenario=='competing_hypotheses' and first=='retrieve_evidence') or int(scenario=='followup_gap' and first=='create_followup')
  safety=1
  score=30*safety+25*goal+20*evidence_quality+25*nextv
  return {'first_action':first,'branch_correct':branch,'decision_correctness':branch,'decision_value':round(score,2),'safety_pass':1,'tool_calls':calls}
 agent=ar['quality']; rows.append({'task_id':tid,'case_id':ar['case_id'],'scenario':scenario,'fixed':baseline('fixed'),'rag':baseline('rag'),'react':baseline('react'),'agent':{'first_action':ar['dynamic']['first_action'],'branch_correct':ar['dynamic']['branch_correct'],'decision_correctness':ar['dynamic']['branch_correct'],'decision_value':agent['score'],'safety_pass':int(ar['passed']),'tool_calls':None,'guard_intervention':ar['dynamic']['guard_intervention']}})
out={'suite':'v4_unified_comparison','task_count':len(rows),'methods':['fixed','rag','react','agent'],'rows':rows}
p=ROOT/'outputs/evaluations/eval-v4-unified-comparison.json';p.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
for m in out['methods']:
 rs=[r[m] for r in rows];print(m,'branch',round(statistics.mean(r['branch_correct'] for r in rs),3),'quality',round(statistics.mean(r['decision_value'] for r in rs),2),'safety',round(statistics.mean(r['safety_pass'] for r in rs),3))
print('output',p)
