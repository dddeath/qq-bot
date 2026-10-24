"""Independent, bounded reading reviews. Never publishes knowledge or applies parameters."""
import datetime as dt
import json
import time
import uuid
import math
from pathlib import Path

CATEGORIES=('purpose_deviation','exploration_insufficient','targeted_insufficient')
DEFAULTS={'max_tasks':3,'per_record_timeout_seconds':480,'selection_timeout_seconds':120,'extension_seconds':150,'max_read_units':2,'exploration_budget_ratio':0.5}

def candidate_directory(sources):
 result=[]
 for index,source in enumerate(sources,1):
  original=json.loads(Path(source).read_text(encoding='utf-8-sig'))
  context=original.get('context',{})
  request=original.get('user_request') or context.get('goal') or ''
  feedback=original.get('research_feedback') or {}
  result.append({'id':f'candidate-{index:03d}','source':str(Path(source).resolve()),
   'task_id':original.get('task_id'),'recorded_at':original.get('recorded_at'),
   'task_mode':context.get('task_mode'),'request_preview':str(request)[:800],
   'request_preview_truncated':len(str(request))>800,'status':original.get('status'),
   'stop_reason':original.get('stop_reason'),'feedback_available':bool(feedback)})
 return result


def review_readings(sources,output,extend,judge,*,settings=None,select=None,now=time.monotonic):
 sources=list(sources)

 cfg=DEFAULTS| (settings or {})
 cfg.pop('timeout_seconds',None)  # Retired batch timeout is not a per-record limit.
 cfg.pop('max_decisions',None)  # Legacy JSON decision-loop limit; native reads use time and read units.
 if (any(type(cfg[k]) is not int or cfg[k]<1 for k in ('max_tasks','max_read_units'))
     or cfg['max_tasks']>3 or any(type(cfg[k]) not in (int,float) or not math.isfinite(cfg[k]) or cfg[k]<=0
     for k in ('per_record_timeout_seconds','selection_timeout_seconds','extension_seconds'))):raise ValueError('invalid_review_budget')
 folder=Path(output)/(dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'-'+uuid.uuid4().hex[:8]);folder.mkdir(parents=True,exist_ok=False)
 started=now();items=[];chosen=list(sources)
 selection={'status':'not_required','elapsed_seconds':0,'selected':[], 'unselected':[]}
 if len(sources)>cfg['max_tasks']:
  selection_started=now();selection_folder=folder/'selection';selection_folder.mkdir()
  try:
   catalog=candidate_directory(sources)
   (selection_folder/'catalog.json').write_text(json.dumps(catalog,ensure_ascii=False,indent=2),encoding='utf-8')
   if select is None:raise RuntimeError('review_selector_missing')
   selection_remaining=cfg['selection_timeout_seconds']-(now()-selection_started)
   if selection_remaining<=0:raise TimeoutError('selection_budget_exhausted')
   answer=select(catalog,selection_folder,selection_remaining,cfg['max_tasks'])
   (selection_folder/'answer.json').write_text(json.dumps(answer,ensure_ascii=False,indent=2),encoding='utf-8')
   if now()-selection_started>cfg['selection_timeout_seconds']:raise TimeoutError('selection_budget_exhausted')
   entries=answer['selected'];by_id={x['id']:x for x in catalog}
   if not isinstance(entries,list) or not 1<=len(entries)<=cfg['max_tasks']:raise ValueError('invalid_review_selection')
   ids=[x['id'] for x in entries]
   if len(set(ids))!=len(ids) or any(x not in by_id for x in ids):raise ValueError('invalid_review_selection')
   if any(not isinstance(x.get('reason'),str) or not x['reason'].strip() for x in entries):raise ValueError('selection_reason_missing')
   chosen=[by_id[x]['source'] for x in ids]
   selection.update(status='selected',selected=[dict(by_id[x['id']],reason=x['reason']) for x in entries],
                    unselected=[dict(x,status='not_selected') for x in catalog if x['id'] not in ids])
  except Exception as exc:
   chosen=[];selection.update(status='failed',error=str(exc))
  selection['elapsed_seconds']=now()-selection_started
  (selection_folder/'receipt.json').write_text(json.dumps(selection,ensure_ascii=False,indent=2),encoding='utf-8')
 else:
  selection['selected']=[{'source':str(Path(p).resolve()),'reason':'within_batch_limit'} for p in chosen]
 for source in chosen:
  record_started=now()
  remaining=cfg['per_record_timeout_seconds']
  source=Path(source);raw=source.read_bytes();original=json.loads(raw)
  dest=folder/f'task-{len(items)+1:03d}';dest.mkdir();(dest/'original.json').write_bytes(raw)
  row={'source':str(source.resolve())};items.append(row)
  try:
   limits={k:cfg[k] for k in ('max_read_units','exploration_budget_ratio')}
   limits['timeout_seconds']=min(remaining/2,cfg['extension_seconds'])
   row['phase_budget']={'extension_seconds':limits['timeout_seconds'],
                        'assessment_reserved_seconds':remaining-limits['timeout_seconds']}
   extension=extend(original,dest/'extension',limits)
   (dest/'extension-result.json').write_text(json.dumps(extension,ensure_ascii=False,indent=2),encoding='utf-8')
   remaining=cfg['per_record_timeout_seconds']-(now()-record_started)
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
  row['elapsed_seconds']=now()-record_started
  if source.read_bytes()!=raw:raise RuntimeError('original_record_changed')
  (dest/'review.json').write_text(json.dumps(row,ensure_ascii=False,indent=2),encoding='utf-8')
 requests=[]
 for index,item in enumerate(items,1):
  for recommendation in item.get('assessment',{}).get('recommendations',[]):
   requests.append({'id':f'review-{index}-{len(requests)+1}','status':'pending_controller_review','source':item['source'],'review':str(folder/f'task-{index:03d}'/'review.json'),'request':recommendation,'applied':False})
 (folder/'change-requests.json').write_text(json.dumps(requests,ensure_ascii=False,indent=2),encoding='utf-8')
 completed=sum(bool(item.get('assessment_complete')) for item in items)
 result={'directory':str(folder.resolve()),'items':items,'selection':selection,
 'counts':{'candidates':len(sources),'selected':len(chosen),'completed':completed,'incomplete':len(chosen)-completed,'unselected':len(selection['unselected'])},
 'all_assessments_complete':bool(chosen) and completed==len(chosen),
 'status':'selection_failed' if selection['status']=='failed' else ('completed' if chosen and completed==len(chosen) else 'partial' if chosen else 'empty'),
 'parameters_applied':False,'elapsed_seconds':now()-started,'budget':cfg}
 (folder/'report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
 return result
