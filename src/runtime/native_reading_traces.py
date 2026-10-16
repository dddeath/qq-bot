"""Read-only native rollout conversion. Unknown purposes and inner exec calls stay unknown."""
import datetime as dt
import hashlib
import json
import re
import uuid
import base64
from pathlib import Path

CALLS={'function_call','custom_tool_call'}
OUTPUTS={'function_call_output','custom_tool_call_output'}

def materialize_images(report, destination):
 """Export actual native image blocks; preserve raw outputs and call association."""
 destination=Path(destination)
 for read in report['reads']:
  result=read['result'];result['images']=[]
  for output_index,row in enumerate(result['raw_outputs']):
   blocks=row.get('payload',{}).get('output',[])
   if not isinstance(blocks,list):continue
   for block_index,block in enumerate(blocks):
    if not isinstance(block,dict) or block.get('type') not in ('input_image','image'):continue
    url=block.get('image_url')
    if isinstance(url,dict):url=url.get('url')
    if block.get('type')=='image' and block.get('data') and block.get('mimeType'):
     url='data:'+block['mimeType']+';base64,'+block['data']
    match=re.fullmatch(r'data:(image/(?:png|jpeg|webp|gif));base64,(.+)',url or '',re.S)
    try:
     if not match:raise ValueError('unsupported_image_encoding')
     data=base64.b64decode(match[2],validate=True)
     if not data:raise ValueError('empty_image')
    except ValueError as exc:
     report['issues'].append({'call_id':read['call_id'],'output_index':output_index,'block_index':block_index,'issue':'image_conversion_failed','reason':str(exc)})
     continue
    destination.mkdir(parents=True,exist_ok=True)
    ext={'image/png':'png','image/jpeg':'jpg','image/webp':'webp','image/gif':'gif'}[match[1]]
    path=destination/f"read-{read['read_id']}-{output_index}-{block_index}.{ext}"
    with path.open('xb') as f:f.write(data)
    result['images'].append({'path':str(path.resolve()),'mime_type':match[1],'call_id':read['call_id'],'output_index':output_index,'block_index':block_index})
 report['trace_quality']['image_conversion_complete']=not any(x.get('issue')=='image_conversion_failed' for x in report['issues'])
def seconds(value):
 try:return dt.datetime.fromisoformat(value.replace('Z','+00:00')).timestamp()
 except (TypeError,ValueError,AttributeError):return None

def convert_trace(rows,meta,*,scope,source,source_lines=None):
 calls={};cells={};reads=[];pending=None;messages=[];orphans=[];issues=[];turn=None;task_record=None;task_source=None;decisions=[];completion=None
 for number,row in zip(source_lines or range(1,len(rows)+1),rows):
  p=row.get('payload',{});kind=p.get('type');stamp=row.get('timestamp')
  if row.get('type')=='turn_context':
   if p.get('turn_id')!=turn:pending=None
   turn=p.get('turn_id');continue
  if kind=='message' and p.get('role') in ('user','assistant') and p.get('channel')!='analysis':
   texts=[c.get('text','') for c in p.get('content',[]) if c.get('type') in ('input_text','output_text','text')]
   text='\n'.join(texts);messages.append({'timestamp':stamp,'role':p['role'],'text':text,'line':number})
   if p['role']=='user':pending=None
   elif text.startswith('READING_TASK '):
    try:
     value=json.loads(text[len('READING_TASK '):])
     if not reads and task_record is None and isinstance(value,dict) and isinstance(value.get('goal'),str) and value['goal'].strip() and isinstance(value.get('budget'),dict):
      task_record=value;task_source={'line':number,'timestamp':stamp,'basis':'assistant_declared_at_entry'}
      first=value.get('first_read')
      if isinstance(first,dict) and first.get('purpose') in ('targeted','explore'):pending={'value':first,'line':number,'timestamp':stamp}
     else:issues.append({'line':number,'issue':'late_or_invalid_task_marker'})
    except ValueError:issues.append({'line':number,'issue':'invalid_task_marker'})
   elif text.startswith('READING_OBSERVATION '):
    try:
     value=json.loads(text[len('READING_OBSERVATION '):])
     if reads and reads[-1]['result']['raw_outputs'] and not reads[-1].get('observation') and isinstance(value,dict):
      reads[-1]['observation']=value;reads[-1]['observation_source']={'line':number,'timestamp':stamp,'basis':'assistant_assessment'}
      next_read=value.get('next_read')
      if isinstance(next_read,dict) and next_read.get('purpose') in ('targeted','explore'):pending={'value':next_read,'line':number,'timestamp':stamp}
     else:issues.append({'line':number,'issue':'observation_without_completed_read'})
    except ValueError:issues.append({'line':number,'issue':'invalid_observation_marker'})
   elif text.startswith('READING_END '):
    try:
     value=json.loads(text[len('READING_END '):])
     if isinstance(value,dict) and isinstance(value.get('stop_reason'),str):completion={**value,'source_line':number,'timestamp':stamp,'basis':'assistant_declared'}
    except ValueError:issues.append({'line':number,'issue':'invalid_end_marker'})
   elif text.startswith('READING_PURPOSE '):
    try:
     value=json.loads(text[len('READING_PURPOSE '):])
     pending={'value':value,'line':number,'timestamp':stamp} if isinstance(value,dict) and value.get('purpose') in ('targeted','explore') else None
    except ValueError:pending=None
   continue
  if kind in CALLS:
   cid=p.get('call_id')
   if not cid:issues.append({'line':number,'issue':'missing_call_id'});pending=None;continue
   if cid in calls:issues.append({'line':number,'issue':'duplicate_call_id','call_id':cid});pending=None;continue
   purpose=None;purpose_source=None
   if pending and pending['value'].get('tool')==p.get('name'):
    purpose=pending['value'];purpose_source={k:v for k,v in pending.items() if k!='value'}
   pending=None
   item={'read_id':len(reads)+1,'call_id':cid,'tool':p.get('name'),'raw_call':row,'source_line':number,'started_at':stamp,
         'action':{'kind':'native_call','purpose':purpose.get('purpose') if purpose else None},'purpose_record':purpose,'purpose_source':purpose_source,
         'result':{'status':'missing_output','images':[],'raw_outputs':[]},'elapsed_seconds':None,'timing_basis':'rollout_call_to_last_output_wall_span','missing':['purpose'] if purpose is None else []}
   if p.get('name') in ('wait','functions.wait'):
    try:arguments=json.loads(p.get('arguments','{}'))
    except (ValueError,TypeError):arguments={}
    item['continuation_of_call_id']=cells.get(str(arguments.get('cell_id')))
   if purpose:decisions.append({'read_id':item['read_id'],'call_id':cid,'purpose_record':purpose,'source':purpose_source})
   completion=None
   reads.append(item);calls[cid]=item
  elif kind in OUTPUTS:
   item=calls.get(p.get('call_id'))
   if item is None:orphans.append(row);continue
   output=p.get('output');texts=[output] if isinstance(output,str) else [v.get('text','') for v in output if isinstance(v,dict)] if isinstance(output,list) else []
   for text in texts:
    match=re.match(r'^Script running with cell ID ([A-Za-z0-9_-]+)(?:\s|$)',text)
    if match:cells[match.group(1)]=item.get('continuation_of_call_id') or item['call_id']
   item['result']['raw_outputs'].append(row);item['result']['status']='output_recorded';item['finished_at']=stamp
   a=seconds(item['started_at']);b=seconds(stamp)
   item['elapsed_seconds']=b-a if a is not None and b is not None and b>=a else None
 for item in reads:
  if not item['result']['raw_outputs']:item['missing'].append('output')
  if item['elapsed_seconds'] is None:item['missing'].append('timing')
  if item['tool'] in ('exec','functions.exec'):item['missing'].append('inner_call_timing_and_pairing')
 task_message=next((m for m in messages if m['role']=='user' and m['text'].strip() and not m['text'].lstrip().startswith(('<environment_context>', '# AGENTS.md'))),None)
 task=task_record['goal'] if task_record else task_message['text'] if task_message else None
 limitations=[] if task else ['task_goal_unavailable']
 audited=[x for x in reads if x['tool'].split('.')[-1] not in ('send_message','wait_agent','list_agents')]
 quality={'missing_purpose_call_ids':[x['call_id'] for x in audited if x['purpose_record'] is None],
          'missing_output_call_ids':[x['call_id'] for x in audited if not x['result']['raw_outputs']],
          'missing_observation_call_ids':[x['call_id'] for x in audited if not x.get('observation')],
          'task_recorded':task_record is not None,'stop_recorded':completion is not None}
 quality['complete']=bool(audited) and quality['task_recorded'] and quality['stop_recorded'] and not any(quality[k] for k in ('missing_purpose_call_ids','missing_output_call_ids','missing_observation_call_ids'))
 recorded=next((r.get('timestamp') for r in reversed(rows) if seconds(r.get('timestamp')) is not None),None)
 return {'native_thread_id':meta.get('id'),'trace_quality':quality,'recorded_at':recorded,'video':task_record.get('video') if task_record else None,'context':{'task_mode':'reading','task_record':task_record,'task_source':task_source,'budget':task_record.get('budget') if task_record else None,'audit_scope':scope,'goal':task,'goal_source_line':task_source['line'] if task_source else task_message['line'] if task_message else None,'purpose_anchor':task,'native_source':source},
         'reads':reads,'decisions':decisions,'completion':completion,'messages':messages,'orphan_outputs':orphans,'issues':issues,'stop_reason':completion['stop_reason'] if completion else 'native_snapshot',
         'limitations':limitations+['exec is preserved as an outer call; no inference of inner execution, return mapping, or per-tool runtime','purposes are accepted only from an explicit preceding assistant marker for the matching tool','timestamps measure recorded wall span, not model inference or isolated tool runtime']}

def collect_traces(sessions,output,*,parent_thread_ids,scope):
 if not parent_thread_ids or not scope:raise ValueError('parent_and_scope_required')
 output=Path(output);output.mkdir(parents=True,exist_ok=True)
 registry=output/'native-index.json';index=json.loads(registry.read_text()) if registry.exists() else {}
 discovered={};errors=[]
 for path in sorted(Path(sessions).rglob('*.jsonl')):
  try:
   with path.open(encoding='utf-8') as f:first=json.loads(next(f))
   if first.get('type')!='session_meta':continue
   meta=first['payload'];source=meta.get('source');parent=source.get('subagent',{}).get('thread_spawn',{}).get('parent_thread_id') if isinstance(source,dict) else None
   if parent and meta.get('id'):discovered[meta['id']]=(path,meta,parent)
  except (ValueError,StopIteration,OSError):continue
 allowed=set(parent_thread_ids);selected=set()
 while True:
  found={id for id,(_,_,parent) in discovered.items() if parent in allowed}-selected
  if not found:break
  selected|=found;allowed|=found
 snapshots=[]
 for id in sorted(selected):
  path,meta,parent=discovered[id];raw=path.read_bytes();digest=hashlib.sha256(raw).hexdigest();key=scope+':'+id
  if index.get(key,{}).get('sha256')==digest:continue
  rows=[];source_lines=[];malformed=[];parts=raw.splitlines();trailing=False
  for n,line in enumerate(parts,1):
   try:rows.append(json.loads(line));source_lines.append(n)
   except (ValueError,UnicodeDecodeError):
    if n==len(parts) and not raw.endswith(b'\n'):trailing=True
    else:malformed.append(n)
  cutoff=seconds(meta.get('timestamp'))
  if cutoff is not None:
   retained=[(n,r) for n,r in zip(source_lines,rows) if seconds(r.get('timestamp')) is None or seconds(r.get('timestamp'))>=cutoff]
   source_lines=[n for n,r in retained];rows=[r for n,r in retained]
  stamp=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'-'+uuid.uuid4().hex[:8]
  dest=output/stamp;dest.mkdir(exist_ok=False)
  report=convert_trace(rows,meta,scope=scope,source=str(path.resolve()),source_lines=source_lines)
  materialize_images(report,dest/'images')
  report.update(captured_at=dt.datetime.now(dt.timezone.utc).isoformat(),source_sha256=digest,parent_thread_id=parent,trailing_partial=trailing,malformed_lines=malformed)
  if cutoff is None:report['limitations'].append('session creation timestamp absent; inherited history boundary unverified')
  (dest/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
  item={'thread_id':id,'report':str((dest/'report.json').resolve()),'sha256':digest,'trailing_partial':trailing}
  snapshots.append(item);index[key]=item
 temporary=output/('index-'+uuid.uuid4().hex+'.tmp');temporary.write_text(json.dumps(index,ensure_ascii=False,indent=2));temporary.replace(registry)
 result={'written':len(snapshots),'matched_threads':len(selected),'snapshots':snapshots,'errors':errors}
 return result

if __name__=='__main__':
 import argparse
 p=argparse.ArgumentParser();p.add_argument('--sessions',required=True);p.add_argument('--output',required=True);p.add_argument('--parent',action='append',required=True);p.add_argument('--scope',required=True);a=p.parse_args()
 print(json.dumps(collect_traces(a.sessions,a.output,parent_thread_ids=a.parent,scope=a.scope),ensure_ascii=False))
