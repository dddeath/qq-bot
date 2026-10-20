"""Independent, bounded reading reviews. Never publishes knowledge or applies parameters."""
import datetime as dt
import json
import time
import uuid
from pathlib import Path

CATEGORIES=('purpose_deviation','exploration_insufficient','targeted_insufficient')
DEFAULTS={'max_tasks':3,'timeout_seconds':300,'extension_seconds':60,'max_read_units':2,'max_decisions':3,'exploration_budget_ratio':0.5}

def review_readings(sources,output,extend,judge,*,settings=None,now=time.monotonic):
 sources=list(sources)

 cfg=DEFAULTS| (settings or {})
 if any(type(cfg[k]) is not int or cfg[k]<1 for k in ('max_tasks','max_read_units','max_decisions')) or cfg['timeout_seconds']<=0 or cfg['extension_seconds']<=0:raise ValueError('invalid_review_budget')
 folder=Path(output)/(dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'-'+uuid.uuid4().hex[:8]);folder.mkdir(parents=True,exist_ok=False)
 started=now();items=[]
 for source in list(sources)[:cfg['max_tasks']]:
  remaining=cfg['timeout_seconds']-(now()-started)
  if remaining<=0:break
  source=Path(source);raw=source.read_bytes();original=json.loads(raw)
  dest=folder/f'task-{len(items)+1:03d}';dest.mkdir();(dest/'original.json').write_bytes(raw)
  row={'source':str(source.resolve())};items.append(row)
  try:
   limits={k:cfg[k] for k in ('max_read_units','max_decisions','exploration_budget_ratio')}
   limits['timeout_seconds']=min(remaining,cfg['extension_seconds'])
   extension=extend(original,dest/'extension',limits)
   (dest/'extension-result.json').write_text(json.dumps(extension,ensure_ascii=False,indent=2),encoding='utf-8')
   remaining=cfg['timeout_seconds']-(now()-started)
   if remaining<=0:raise TimeoutError('review_budget_exhausted')
   assessment=judge({'original':original,'extension':extension,'reads':extension.get('reads',[])},remaining)
   if set(assessment['scores'])!=set(CATEGORIES) or any(v is not None and (type(v) is not int or not 0<=v<=3) for v in assessment['scores'].values()):raise ValueError('invalid_review_scores')
   for finding in assessment['findings']:
    if finding['category'] not in CATEGORIES:raise ValueError('invalid_review_category')
    for field,data in [('original_read_ids',original),('extension_read_ids',extension)]:
     if any(type(x) is not int or not 1<=x<=len(data.get('reads',[])) for x in finding[field]):raise ValueError('invalid_evidence_reference')
   if original.get('native_thread_id') and not any(x.get('purpose_record') for x in original.get('reads',[])):
    assessment['scores']['purpose_deviation']=None
    assessment.setdefault('limitations',[]).append('No contemporaneous purpose records; purpose deviation is unscored.')
   missing=[name for name in CATEGORIES if assessment['scores'][name] is None]

   row.update(status='ok',assessment=assessment,assessment_complete=not missing,incomplete_categories=missing)
  except Exception as exc:row.update(status='error',error=str(exc))
  if source.read_bytes()!=raw:raise RuntimeError('original_record_changed')
  (dest/'review.json').write_text(json.dumps(row,ensure_ascii=False,indent=2),encoding='utf-8')
 requests=[]
 for index,item in enumerate(items,1):
  for recommendation in item.get('assessment',{}).get('recommendations',[]):
   requests.append({'id':f'review-{index}-{len(requests)+1}','status':'pending_controller_review','source':item['source'],'review':str(folder/f'task-{index:03d}'/'review.json'),'request':recommendation,'applied':False})
 (folder/'change-requests.json').write_text(json.dumps(requests,ensure_ascii=False,indent=2),encoding='utf-8')
 result={'directory':str(folder.resolve()),'items':items,'all_assessments_complete':bool(items) and len(items)==len(sources) and all(item.get('assessment_complete',False) for item in items),'parameters_applied':False,'elapsed_seconds':now()-started,'budget':cfg}
 (folder/'report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
 return result
