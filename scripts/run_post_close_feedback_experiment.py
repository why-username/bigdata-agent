from __future__ import annotations
import json, os, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from agent.core import run_investigation, DataStore
from agent.evaluation import citations_are_verifiable
BASE=ROOT/'data/eval/conclusion_holdout'; GOLD=json.loads((BASE/'gold_answers.json').read_text())
CASES=['EA22002','PE20016','PE23015','PE24004']
def bundle(cid):
 b=BASE/f'{cid}_feedback_bundle'; b.mkdir(exist_ok=True)
 for name in ('cases','records','evidence'):
  (b/f'{name}.json').write_text((BASE/f'{cid}_{name}.json').read_text(),encoding='utf-8')
 return b
def main():
 rows=[]
 for cid in CASES:
  g=GOLD[cid]; b=bundle(cid); os.environ['AGENT_DATA_DIR']=str(b); store=DataStore()
  feedback=(f"官方结案后反馈（仅阶段B可见）：后续结案材料确认方向为 {g['defect_direction']}，"
            f"主要机制为 {g['mechanism']}，处置为 {g['remedy']}。请基于该新证据更新原有假设，"
            "明确哪些原判断得到支持、哪些需要修正，并给出带来源的最终调查摘要。")
  goal=f"阶段B：收到结案后反馈后，更新 {cid} 的调查判断、竞争性假设、证据台账和最终报告。反馈内容：{feedback}"
  s=run_investigation(cid,goal,cutoff_date=g['pre_cutoff'],mode='api',focus='report',dynamic_scenario='competing_hypotheses')
  cv=citations_are_verifiable(s.get('evidence_ledger',[]),store,cid,g['pre_cutoff'])
  text=json.dumps(s,ensure_ascii=False)
  rows.append({'case_id':cid,'status':s['status'],'passed':cv,'completion_note':s.get('completion_note',''),'claims':s.get('claims',[]),'evidence_ids':[x.get('evidence_id') for x in s.get('evidence_ledger',[])],'feedback_visible':True,'gold':g,'overconfident':int(('已确认' in s.get('completion_note','') or '确定' in s.get('completion_note','')) and not s.get('evidence_ledger')),'errors':s.get('errors',[])})
 out={'suite':'post_close_feedback_api','task_count':len(rows),'rows':rows}; p=ROOT/'outputs/evaluations/post-close-feedback-api.json';p.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({'output':str(p),'count':len(rows),'passed':sum(r['passed'] for r in rows)},ensure_ascii=False))
if __name__=='__main__':main()
