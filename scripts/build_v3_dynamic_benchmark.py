"""Build a dynamic-decision benchmark with branch states and gold next actions."""
from __future__ import annotations
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def build(out: Path):
 cases=json.loads((ROOT/'data/imported/cases.json').read_text())
 rows=[]
 scenarios=[
  ('empty_recovery','初始检索为空，判断是否需要改写查询或放宽实体条件。','empty','retrieve_evidence'),
  ('source_conflict','来源日期或部件字段冲突，先核验冲突来源并暂停结论。','conflict','link_entities'),
  ('competing_hypotheses','已有支持材料，寻找替代解释和反证。','support_only','retrieve_evidence'),
  ('evidence_sufficiency','已有两类独立来源，判断是否停止无效检索并说明剩余缺口。','sufficient','done'),
  ('cutoff_leakage','检索结果含截点后材料，隔离未来材料并保持安全停止。','future_material','done'),
  ('followup_gap','公开材料不足以回答个体车辆问题，生成带依据和验收条件的补查。','missing_field','create_followup'),
 ]
 for c in cases:
  cid=c['case_id']; cutoff=c.get('cutoff_date')
  for i,(name,goal,state,action) in enumerate(scenarios,1):
   rows.append({'task_id':f'V3-{cid}-{i:02d}','case_id':cid,'cutoff_date':cutoff,'kind':'dynamic_decision','scenario':name,'initial_state':state,'goal':goal,'focus':name,'gold_next_action':action,'max_steps':5,'same_snapshot_group':cid})
 payload={'schema_version':'research-benchmark-v3','created_at':'2026-11-01','selection':'all imported cases with six dynamic branch scenarios','cases':[{'case_id':c['case_id'],'cutoff_date':c.get('cutoff_date')} for c in cases],'tasks':rows}
 out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8'); return payload
if __name__=='__main__':
 p=Path(__import__('sys').argv[1]) if len(__import__('sys').argv)>1 else ROOT/'data/eval/research_v3_tasks.json'; x=build(p); print(json.dumps({'cases':len(x['cases']),'tasks':len(x['tasks']),'output':str(p)},ensure_ascii=False))
