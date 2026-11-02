from __future__ import annotations
import json,os,statistics,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
os.environ['AGENT_DATA_DIR']=str(ROOT/'data/eval/v3_candidates')
from agent.core import run_investigation,DataStore
from agent.evaluation import dynamic_decision_metrics,decision_quality_score,citations_are_verifiable
SCENARIOS=[('empty_recovery','初始证据检索为空，请恢复调查并选择下一步。','retrieve_evidence'),('source_conflict','来源或字段存在冲突，请先核验冲突并暂停结论。','link_entities'),('competing_hypotheses','已有支持材料，请主动寻找替代解释和反证。','retrieve_evidence'),('evidence_sufficiency','已有两类独立来源，请判断是否应安全停止。','done'),('cutoff_leakage','结果中可能含截点后材料，请隔离并安全停止。','done'),('followup_gap','公开材料不足以回答个体车辆问题，请生成可验收补查。','create_followup')]
def main():
 manifest=json.loads((ROOT/'data/eval/v3_candidate_manifest.json').read_text())[:4]; store=DataStore(); tasks=[]
 for c in manifest:
  if not store.case(c['case_id']): continue
  for i,(scenario,goal,gold) in enumerate(SCENARIOS,1): tasks.append({'task_id':f"V3-{c['case_id']}-{i:02d}",'case_id':c['case_id'],'cutoff_date':c['replay_cutoff'],'scenario':scenario,'goal':goal,'focus':scenario,'gold_next_action':gold})
 outp=ROOT/'outputs/evaluations/v3-dynamic-api-progress.json'; outp.parent.mkdir(parents=True,exist_ok=True)
 progress=json.loads(outp.read_text()) if outp.exists() else {'suite':'research_v3_dynamic_api','rows':[]}; done={r['task_id'] for r in progress['rows']}
 for t in tasks:
  if t['task_id'] in done: continue
  try:
   s=run_investigation(t['case_id'],t['goal'],cutoff_date=t['cutoff_date'],mode='api',focus=t['focus'],dynamic_scenario=t['scenario'])
   cv=citations_are_verifiable(s.get('evidence_ledger',[]),store,t['case_id'],t['cutoff_date'])
   row={'task_id':t['task_id'],'case_id':t['case_id'],'scenario':t['scenario'],'status':s['status'],'passed':s['status'] in {'completed','needs_human_review'} and cv,'dynamic_metrics':dynamic_decision_metrics(s,t),'decision_value_v3':decision_quality_score(s,t,cv),'tool_calls':s['usage']['tool_calls'],'latency_ms':s['usage']['latency_ms'],'tokens':s['usage']['total_tokens'],'errors':s.get('errors',[])}
  except Exception as e: row={'task_id':t['task_id'],'case_id':t['case_id'],'scenario':t['scenario'],'status':'failed','passed':False,'errors':[{'error':str(e)}]}
  progress['rows'].append(row); progress['rows'].sort(key=lambda x:x['task_id']); progress['task_count']=len(tasks); progress['completed_count']=len(progress['rows']); outp.write_text(json.dumps(progress,ensure_ascii=False,indent=2),encoding='utf-8'); print(json.dumps({'task':t['task_id'],'status':row['status'],'passed':row['passed']},ensure_ascii=False),flush=True)
 final=ROOT/'outputs/evaluations/eval-research_v3-dynamic-api.json'; final.write_text(json.dumps(progress,ensure_ascii=False,indent=2),encoding='utf-8'); print(json.dumps({'output':str(final),'count':len(progress['rows'])},ensure_ascii=False))
if __name__=='__main__': main()
