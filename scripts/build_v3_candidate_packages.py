from __future__ import annotations
import json,zipfile,hashlib,pathlib,datetime,urllib.parse
ROOT=pathlib.Path(__file__).resolve().parents[1]; OUT=ROOT/'data'/'eval'/'v3_candidates'; OUT.mkdir(parents=True,exist_ok=True)
config=[('EA22002','TESLA','MODEL 3',2020,'ELECTRICAL SYSTEM','2024-04-25','23V085','electrical system / driver controls'),('PE20016','CHEVROLET','BOLT EV',2020,'ELECTRICAL SYSTEM:PROPULSION SYSTEM','2022-02-07','21V650','electrical system / propulsion battery'),('PE23015','FORD','ECOSPORT',2020,'ENGINE AND ENGINE COOLING:ENGINE:OIL/LUBRICATION:PUMP','2024-02-14','23V905','engine / oil lubrication'),('PE24004','HONDA','RIDGELINE',2020,'BACK OVER PREVENTION','2024-08-05','24V321','back over prevention / rear camera')]
zip_path=ROOT/'data/imported/raw/investigations/FLAT_INV.zip'; zip_sha=hashlib.sha256(zip_path.read_bytes()).hexdigest(); raw=zipfile.ZipFile(zip_path).read('FLAT_INV.txt').decode('latin1')
def iso(v):
 for fmt in ('%Y%m%d','%m/%d/%Y','%d/%m/%Y','%Y-%m-%d'):
  try: return datetime.datetime.strptime(str(v),fmt).date().isoformat()
  except ValueError: pass
 return str(v)
cases=[];records=[];evidence=[]
for cid,make,model,year,component,cut,campaign,label in config:
 line=next(x.split('\t') for x in raw.splitlines() if x.startswith(cid+'\t'))
 cases.append({'case_id':cid,'title':line[9],'make':make,'models':[model],'component':label,'cutoff_date':cut,'data_status':'v3_candidate_public_snapshot','source_url':'https://static.nhtsa.gov/odi/ffdd/inv/FLAT_INV.zip','migration_basis':{'investigation_id':cid,'campaign':campaign,'component_family':component,'dynamic_case':True}})
 evidence.append({'evidence_id':cid+'-FLAT-INV','case_id':cid,'title':line[9]+' ODI closing resume summary','content':line[10],'published_date':iso(line[7]),'source_kind':'nhtsa_flat_investigation','source_url':'https://static.nhtsa.gov/odi/ffdd/inv/FLAT_INV.zip','citation_locator':cid,'source_sha256':zip_sha,'holdout_only':False})
 api=ROOT/'data/eval/v3_official_materials'/f'{cid}_recalls.json'
 if api.exists():
  x=json.loads(api.read_text()); rr=next((r for r in x.get('results',[]) if str(r.get('NHTSACampaignNumber','')).replace('000','')==campaign),None)
  if rr:
   u='https://api.nhtsa.gov/recalls/recallsByVehicle?'+urllib.parse.urlencode({'make':make.title(),'model':model.title(),'modelYear':year})
   pub=iso(rr.get('ReportReceivedDate','')) if rr.get('ReportReceivedDate') else cut
   evidence.append({'evidence_id':cid+'-RECALL-'+campaign,'case_id':cid,'title':'NHTSA Recall '+campaign+' public disposition','content':' '.join(str(rr.get(k,'')) for k in ('Summary','Consequence','Remedy')),'published_date':pub,'source_kind':'nhtsa_recall_api','source_url':u,'citation_locator':'NHTSACampaignNumber='+campaign,'source_sha256':hashlib.sha256(api.read_bytes()).hexdigest(),'holdout_only':pub>cut})
 stem={'EA22002':'TESLA_MODEL_3_2020','PE20016':'CHEVROLET_BOLT_EV_2020','PE23015':'FORD_ECOSPORT_2020','PE24004':'HONDA_RIDGELINE_2020'}[cid]
 rawf=ROOT/'data/expanded/raw_complaints'/f'{cid}_{stem}_complaints.json'
 x=json.loads(rawf.read_text())
 for r in x.get('results',[]):
  try: filed=datetime.datetime.strptime(r['dateComplaintFiled'],'%m/%d/%Y').date()
  except: continue
  if filed<=datetime.date.fromisoformat(cut):
   records.append({'record_id':str(r['odiNumber']),'case_id':cid,'record_type':'complaint','make':make,'model':model,'model_year':year,'component':r.get('components',''),'received_date':filed.isoformat(),'occurred_date':r.get('dateOfIncident',''),'text':r.get('summary',''),'source_id':str(r['odiNumber']),'source_url':'https://api.nhtsa.gov/complaints/complaintsByVehicle?'+urllib.parse.urlencode({'make':make.title(),'model':model.title(),'modelYear':year}),'raw_nhtsa':r})
for name,val in [('cases.json',cases),('records.json',records),('evidence.json',evidence)]: (OUT/name).write_text(json.dumps(val,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'cases':len(cases),'records':len(records),'evidence':len(evidence),'output':str(OUT)},ensure_ascii=False))
