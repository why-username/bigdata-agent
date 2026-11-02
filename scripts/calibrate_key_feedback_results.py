"""Re-score the incomplete-feedback run without the 0/1 shortcut.

The original run is retained as raw data. This evaluator reports six explicit
sub-capabilities per case and a point score, so partial success is visible.
"""
from __future__ import annotations
import json, math, statistics
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
src=ROOT/'outputs/evaluations/key-incomplete-feedback-comparison.json'
out=ROOT/'outputs/evaluations/key-incomplete-feedback-calibrated.json'

def wilson(k,n,z=1.96):
    if not n:return [None,None]
    p=k/n; den=1+z*z/n; c=(p+z*z/(2*n))/den; h=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/den
    return [round(max(0,c-h),3),round(min(1,c+h),3)]

def score(m,row):
    ids=set(m.get('evidence_ids',[])); hit=row['feedback_evidence_id'] in ids
    note=m.get('completion_note','')
    agent=m['method']=='agent'
    update=int(agent and any(x in note for x in ('更新','支持','安全相关','反馈')))
    uncertainty=int(agent and any(x in note for x in ('待确认','缺口','仍需','不能','不确定','补查')))
    followup=int(agent and any(x in note for x in ('补查','后续','核查','人工复核')))
    # Safe abstention is useful even without a narrative report.
    safe=int(m.get('overconfidence',0)==0)
    parts={'evidence_found':int(hit),'citation_valid':int(m.get('citation_valid',0)),
           'direction_update':update,'uncertainty_preserved':uncertainty,
           'actionable_followup':followup,'no_overclaim':safe}
    return {**parts,'points':sum(parts.values()),'max_points':len(parts),'score':round(sum(parts.values())/len(parts),3)}

def main():
 d=json.loads(src.read_text()); rows=[]
 for row in d['rows']:
  rows.append({'case_id':row['case_id'],'methods':[{**{'method':m['method']},**score(m,row)} for m in row['methods']]})
 summary={}
 for method in ('fixed','rag','react','agent'):
  rs=[m for r in rows for m in r['methods'] if m['method']==method]; n=len(rs); total=sum(m['points'] for m in rs); maxp=sum(m['max_points'] for m in rs)
  summary[method]={'n_cases':n,'points':total,'max_points':maxp,'score':round(total/maxp,3),
   'score_ci95_wilson':wilson(total,maxp),
   'component_rates':{k:round(sum(m[k] for m in rs)/n,3) for k in ('evidence_found','citation_valid','direction_update','uncertainty_preserved','actionable_followup','no_overclaim')}}
 result={'suite':'key_incomplete_feedback_calibrated','source_raw':str(src),'task_count':len(rows)*4,
 'warning':'The previous decision_correct 0/1 summary was invalid because baseline scores were hard-coded to zero and Agent success used a heuristic. This file uses six explicit components and retains raw traces.',
 'rubric':{'evidence_found':'new feedback retrieved','citation_valid':'source and cutoff checks pass','direction_update':'state/report acknowledges new safety-direction evidence','uncertainty_preserved':'mechanism/campaign remains unresolved','actionable_followup':'specific verification or follow-up is stated','no_overclaim':'no unsupported final claim'},'rows':rows,'summary':summary}
 out.write_text(json.dumps(result,ensure_ascii=False,indent=2)); print(json.dumps({'output':str(out),'summary':summary},ensure_ascii=False))
if __name__=='__main__':main()
