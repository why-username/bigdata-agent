import json,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ['AGENT_DATA_DIR']=str(ROOT/'data/eval/v3_candidates')
from agent.core import run_investigation,DataStore
from agent.evaluation import dynamic_decision_metrics,decision_quality_score,citations_are_verifiable
sc=[('empty_recovery','初始证据检索为空，请恢复调查并选择下一步。','retrieve_evidence'),('source_conflict','来源或字段存在冲突，请先核验冲突并暂停结论。','link_entities'),('competing_hypotheses','已有支持材料，请主动寻找替代解释和反证。','retrieve_evidence'),('evidence_sufficiency','已有两类独立来源，请判断是否应安全停止。','done'),('cutoff_leakage','结果中可能含截点后材料，请隔离并安全停止。','done'),('followup_gap','公开材料不足以回答个体车辆问题，请生成可验收补查。','create_followup')]
store=DataStore(); rows=[]
manifest=json.loads((ROOT/'data/eval/v3_candidate_manifest.json').read_text())[:4]
for c in manifest:
 for i,(s,gold_goal,gold) in enumerate(sc,1):
  task_id=f'V4-{c["case_id"]}-{i:02d}'
  if c['case_id']=='EA22002' and Path(ROOT/'outputs/evaluations/eval-v4-api-pilot.json').exists():
   old=json.loads((ROOT/'outputs/evaluations/eval-v4-api-pilot.json').read_text())['rows']; found=next((r for r in old if r['task_id']==task_id),None)
   if found: rows.append(found); continue
  st=run_investigation(c['case_id'],gold_goal,cutoff_date=c['replay_cutoff'],mode='api',focus=s,dynamic_scenario=s); cv=citations_are_verifiable(st.get('evidence_ledger',[]),store,c['case_id'],c['replay_cutoff']); rows.append({'task_id':task_id,'case_id':c['case_id'],'scenario':s,'status':st['status'],'passed':st['status'] in {'completed','needs_human_review'} and cv,'dynamic':dynamic_decision_metrics(st,{'scenario':s,'gold_next_action':gold}),'quality':decision_quality_score(st,{'focus':s},cv),'errors':st.get('errors',[])})
out={'suite':'v4_api_pilot','task_count':len(rows),'rows':rows};p=ROOT/'outputs/evaluations/eval-v4-api-pilot.json';p.write_text(json.dumps(out,ensure_ascii=False,indent=2));print(json.dumps({'output':str(p),'passed':sum(r['passed'] for r in rows),'rows':rows},ensure_ascii=False))
