from __future__ import annotations
import json, os, sys, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
os.environ['AGENT_DATA_DIR']=str(ROOT/'data/eval/v3_candidates')
from agent.core import DataStore, run_fixed_baseline, run_rag_baseline, run_react_baseline, run_investigation
from agent.evaluation import dynamic_decision_metrics, decision_quality_score, citations_are_verifiable
SCENARIOS=[('empty_recovery','初始证据检索为空，请恢复调查并选择下一步。','retrieve_evidence'),('source_conflict','来源或字段存在冲突，请先核验冲突并暂停结论。','link_entities'),('competing_hypotheses','已有支持材料，请主动寻找替代解释和反证。','retrieve_evidence'),('evidence_sufficiency','已有两类独立来源，请判断是否应安全停止。','done'),('cutoff_leakage','结果中可能含截点后材料，请隔离并安全停止。','done'),('followup_gap','公开材料不足以回答个体车辆问题，请生成可验收补查。','create_followup')]
def tasks():
  manifest=json.loads((ROOT/'data/eval/v3_candidate_manifest.json').read_text())[:4]
  store=DataStore(); out=[]
  for c in manifest:
    if not store.case(c['case_id']): continue
    for i,(scenario,goal,gold) in enumerate(SCENARIOS,1): out.append({'task_id':f'V4-{c["case_id"]}-{i:02d}','case_id':c['case_id'],'cutoff_date':c['replay_cutoff'],'scenario':scenario,'goal':goal,'focus':scenario,'gold_next_action':gold})
  return out
def main():
  store=DataStore(); rows=[]
  for t in tasks():
    fixed=run_fixed_baseline(t['case_id'],t['cutoff_date'],t['goal']); rag=run_rag_baseline(t['case_id'],t['cutoff_date'],t['goal']); react=run_react_baseline(t['case_id'],t['cutoff_date'],t['goal'],t['scenario'])
    react_state=react['state']; react_cv=citations_are_verifiable(react_state.get('evidence_ledger',[]),store,t['case_id'],t['cutoff_date'])
    row={'task_id':t['task_id'],'case_id':t['case_id'],'scenario':t['scenario'],'fixed':{'tool_calls':fixed['tool_calls'],'evidence_count':len(fixed['evidence_ids'])},'rag':{'tool_calls':rag['tool_calls'],'evidence_count':len(rag['evidence_ids'])},'react':{'tool_calls':react['tool_calls'],'decision_value_v3':decision_quality_score(react_state,t,react_cv),'dynamic':dynamic_decision_metrics(react_state,t)}}
    row['agent_status']='pending_api'; rows.append(row)
  p=ROOT/'outputs/evaluations/eval-v4-dynamic-comparison-offline.json'; p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps({'suite':'v4_dynamic_comparison_offline','task_count':len(rows),'rows':rows},ensure_ascii=False,indent=2),encoding='utf-8'); print(json.dumps({'output':str(p),'tasks':len(rows)},ensure_ascii=False))
if __name__=='__main__': main()
