from __future__ import annotations
import json,zipfile,datetime,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; out=ROOT/'data/eval/conclusion_holdout';out.mkdir(parents=True,exist_ok=True)
# Gold labels are derived from official closing-resume text, kept out of runtime.
labels={
'EA22002':{'pre_cutoff':'2024-04-24','defect_direction':'supported_safety_defect','mechanism':'driver_engagement_controls_mismatch','remedy':'recall_23V838','gold_source_date':'2024-04-25'},
'PE20016':{'pre_cutoff':'2022-02-06','defect_direction':'supported_safety_defect','mechanism':'battery_cell_manufacturing_defects_thermal_events','remedy':'recall_21V650','gold_source_date':'2022-02-07'},
'PE23015':{'pre_cutoff':'2024-02-13','defect_direction':'supported_safety_defect','mechanism':'oil_pump_drive_belt_tensioner_or_belt_failure','remedy':'recall_23V905','gold_source_date':'2024-02-14'},
'PE24004':{'pre_cutoff':'2024-08-04','defect_direction':'supported_safety_defect','mechanism':'tailgate_harness_material_and_bending_failure','remedy':'recall_24V321','gold_source_date':'2024-08-05'},}
# Copy only candidate records/evidence published before pre-cutoff.
cases=json.loads((ROOT/'data/eval/v3_candidates/cases.json').read_text()); records=json.loads((ROOT/'data/eval/v3_candidates/records.json').read_text()); evidence=json.loads((ROOT/'data/eval/v3_candidates/evidence.json').read_text())
for cid,label in labels.items():
 c=next(x for x in cases if x['case_id']==cid); c={**c,'cutoff_date':label['pre_cutoff']}
 rs=[r for r in records if r['case_id']==cid and r.get('received_date','9999-12-31')<=label['pre_cutoff']]
 es=[e for e in evidence if e['case_id']==cid and e.get('published_date','9999-12-31')<=label['pre_cutoff']]
 (out/f'{cid}_cases.json').write_text(json.dumps([c],ensure_ascii=False,indent=2));(out/f'{cid}_records.json').write_text(json.dumps(rs,ensure_ascii=False,indent=2));(out/f'{cid}_evidence.json').write_text(json.dumps(es,ensure_ascii=False,indent=2))
for cid,l in labels.items(): l['holdout_only']=True
(out/'gold_answers.json').write_text(json.dumps(labels,ensure_ascii=False,indent=2));print(json.dumps({'cases':len(labels),'gold_holdout':True},ensure_ascii=False))
