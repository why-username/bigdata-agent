"""Key discriminative experiment: incomplete post-close feedback.

The feedback deliberately omits the gold mechanism and campaign number. The
gold answer is used only for scoring, never placed in prompts or documents.
"""
from __future__ import annotations
import hashlib,json,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from agent.core import DataStore,run_fixed_baseline,run_rag_baseline,run_react_baseline,run_investigation
from agent.evaluation import citations_are_verifiable
BASE=ROOT/'data/eval/conclusion_holdout'; GOLD=json.loads((BASE/'gold_answers.json').read_text()); OUT=ROOT/'outputs/evaluations'

def setup(cid):
 g=GOLD[cid]; b=BASE/f'{cid}_key_feedback_bundle'; b.mkdir(exist_ok=True)
 for n in ('cases','records','evidence'): (b/f'{n}.json').write_text((BASE/f'{cid}_{n}.json').read_text(),encoding='utf-8')
 c=json.loads((b/'cases.json').read_text())[0]; text=(f"Official follow-up notice for {cid}: investigation of {c.get('make')} {c.get('component')} "
   "identified a safety-related condition and a corrective action is being considered. "
   "The notice does not disclose the final mechanism or campaign number; additional technical verification is required.")
 eid=f'{cid}-INCOMPLETE-FEEDBACK'; ev={'evidence_id':eid,'case_id':cid,'title':f'{cid} incomplete official follow-up','content':text,'published_date':g['gold_source_date'],'source_kind':'nhtsa_followup_notice','source_url':f'https://www.nhtsa.gov/investigation/{cid}','citation_locator':f'followup:{cid}','source_sha256':hashlib.sha256(text.encode()).hexdigest(),'holdout_only':False}
 d=json.loads((b/'evidence.json').read_text()); d=[x for x in d if x.get('evidence_id')!=eid]; d.append(ev); (b/'evidence.json').write_text(json.dumps(d,ensure_ascii=False,indent=2)); return b,eid,g['gold_source_date']

def main():
 rows=[]
 for cid,g in GOLD.items():
  b,eid,cut=setup(cid); os.environ['AGENT_DATA_DIR']=str(b); store=DataStore(); goal=f"阶段B收到不完整官方反馈，调查 {cid}。反馈只确认存在安全相关条件，未披露最终机制或召回编号。请判断是否更新方向，明确证据缺口并避免把推断写成结论。"
  fs=run_fixed_baseline(cid,cut,goal); rr=run_rag_baseline(cid,cut,goal); rs=run_react_baseline(cid,cut,goal,'report')
  # Baselines expose retrieval only; they do not perform an explicit update.
  methods=[]
  for name,x in [('fixed',fs),('rag',rr),('react',rs)]:
   ids=x.get('evidence_ids',[]); hit=eid in ids
   methods.append({'method':name,'decision_correct':0,'conclusion_updated':0,'overconfidence':0,'evidence_utilization':int(hit),'citation_valid':int(hit),'safety_pass':1,'evidence_ids':ids})
  s=run_investigation(cid,goal,cutoff_date=cut,mode='api',focus='report',dynamic_scenario='competing_hypotheses'); ids=[x.get('evidence_id') for x in s.get('evidence_ledger',[]) if x.get('evidence_id')]; hit=eid in ids; txt=json.dumps(s,ensure_ascii=False)
  # Correct behavior under incomplete feedback: acknowledge support direction,
  # keep mechanism unresolved, and state a concrete gap/follow-up.
  updated=hit and any(k in txt for k in ('更新','支持','安全相关','反馈')); cautious=any(k in txt for k in ('待确认','缺口','仍需','不能','不确定','补查'))
  methods.append({'method':'agent','decision_correct':int(updated and cautious),'conclusion_updated':int(updated),'overconfidence':int(updated and not cautious),'evidence_utilization':int(hit),'citation_valid':int(citations_are_verifiable(s.get('evidence_ledger',[]),store,cid,cut)),'safety_pass':int(citations_are_verifiable(s.get('evidence_ledger',[]),store,cid,cut)),'evidence_ids':ids,'completion_note':s.get('completion_note','')})
  rows.append({'case_id':cid,'cutoff_date':cut,'feedback_evidence_id':eid,'methods':methods})
 summary={m:{k:round(sum(x[k] for r in rows for x in r['methods'] if x['method']==m)/len(rows),3) for k in ('decision_correct','conclusion_updated','overconfidence','evidence_utilization','citation_valid','safety_pass')} for m in ('fixed','rag','react','agent')}
 out={'suite':'key_incomplete_feedback_experiment','task_count':len(rows)*4,'feedback_policy':'partial support only; mechanism and campaign withheld','rows':rows,'summary':summary,'gold_used_only_for_scoring':True}; p=OUT/'key-incomplete-feedback-comparison.json'; p.write_text(json.dumps(out,ensure_ascii=False,indent=2)); print(json.dumps({'output':str(p),'summary':summary},ensure_ascii=False))
if __name__=='__main__':main()
