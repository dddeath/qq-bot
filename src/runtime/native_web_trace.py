"""Correlate explicit native read reservations with actual harness call IDs."""
import json
import re
from research_trace import write_record

HEADER = re.compile(r'^// reading:([0-9a-f]{32}):([0-9]+)\n')

def same_native_input(expected, actual):
    if expected.strip() == actual.strip():return True
    # Only normalize the fixed JSON web-call wrapper; arbitrary JavaScript stays exact.
    pattern = r'text\(await tools\.web__run\((.*)\)\);'
    left = re.fullmatch(pattern, expected.strip(), re.S)
    right = re.fullmatch(pattern, actual.strip(), re.S)
    if not left or not right:return False
    try:
        a,b=json.loads(left[1]),json.loads(right[1])
        return type(a) is dict and type(b) is dict and a == b
    except ValueError:return False


class NativeWebRecorder:
    def __init__(self, trace):
        self.trace = trace
        self.calls = {}

    def reserve(self, task_id, native_tool, native_input, purpose, reason, relation):
        if native_tool not in ('exec', 'web_search'):
            raise ValueError('unsupported_native_read_tool')
        if native_tool == 'exec' and (not isinstance(native_input,str) or not native_input.strip()):
            raise ValueError('native_input_required')
        if native_tool == 'web_search' and (not isinstance(native_input,dict) or not native_input):
            raise ValueError('native_action_required')
        path,_ = self.trace.prepare('web_search', {'native_tool':native_tool,'native_input':native_input,
            '_reading':dict(task_id=task_id,purpose=purpose,reason=reason,relation=relation)})
        row=json.loads(path.read_text(encoding='utf-8'))
        if native_tool == 'exec':
            native_input=f'// reading:{task_id}:{row["read_id"]}\n'+native_input
        return dict(task_id=task_id,read_id=row['read_id'],native_input=native_input,
                    budget_remaining=self.trace.remaining(path.parent))

    def _bind(self, thread, call_id, path):
        row=json.loads(path.read_text(encoding='utf-8'))
        if row.get('native_call_id'):
            if row['native_call_id']==call_id and row['native_thread_id']==thread:
                self.calls[(thread,call_id)]=path
            return
        if row['result']['status']!='pending':return
        row.update(native_thread_id=thread,native_call_id=call_id)
        write_record(path,row);self.calls[(thread,call_id)]=path

    def observe(self, thread, event, *, task_id=None):
        p=event.get('payload',{})
        if event.get('type')=='response_item' and p.get('type')=='custom_tool_call' and p.get('name')=='exec':
            match=HEADER.match(p.get('input',''))
            if not match or not p.get('call_id'):return
            try:path=self.trace.folder(match[1])/f'read-{int(match[2]):03d}.json'
            except ValueError:return
            if not path.exists():return
            row=json.loads(path.read_text(encoding='utf-8'))
            if row['arguments'].get('native_tool')!='exec' or not same_native_input(row['arguments'].get('native_input',''),p['input'][match.end():]):return
            self._bind(thread,p['call_id'],path)
        elif event.get('type')=='response_item' and p.get('type') in ('custom_tool_call_output','function_call_output'):
            path=self.calls.get((thread,p.get('call_id')))
            if path:self._complete(path,p.get('output'),event)
        # CLI web_search items expose action/status but may omit fetched text.
        elif event.get('type') in ('item.started','item.completed') and event.get('item',{}).get('type')=='web_search' and task_id:
            item=event['item'];cid=item.get('id')
            if not cid:return
            path=self.calls.get((thread,cid))
            if path is None and isinstance(item.get('action'),dict):
                candidates=[]
                for candidate in self.trace.folder(task_id).glob('read-*.json'):
                    row=json.loads(candidate.read_text(encoding='utf-8'))
                    if (row['result']['status']=='pending' and not row.get('native_call_id')
                        and row['arguments'].get('native_tool')=='web_search'
                        and row['arguments'].get('native_input')==item['action']):candidates.append(candidate)
                if len(candidates)==1:
                    path=candidates[0];self._bind(thread,cid,path)
            if path and event['type']=='item.completed':
                self._complete(path,item.get('output'),event)

    def _complete(self,path,output,event):
        row=json.loads(path.read_text(encoding='utf-8'))
        if row['result']['status']!='pending':return
        if output is None:
            row['result']={'status':'missing_output','images':[]}
            row['missing_reason']='native_event_does_not_include_result_content'
            row['elapsed_seconds']=None
            write_record(path,row)
        else:
            blocks=output if isinstance(output,list) else [{'type':'text','text':output if isinstance(output,str) else json.dumps(output,ensure_ascii=False)}]
            content=[]
            for block in blocks:
                if isinstance(block,dict) and block.get('type') in ('text','image'):content.append(block)
                elif isinstance(block,dict) and block.get('type')=='input_image':
                    url=block.get('image_url', '')
                    if isinstance(url,dict):url=url.get('url','')
                    match=re.fullmatch(r'data:(image/[a-zA-Z0-9.+-]+);base64,(.+)',url,re.S)
                    if match:content.append({'type':'image','mimeType':match[1],'data':match[2]})
                    else:content.append({'type':'text','text':json.dumps(block,ensure_ascii=False)})
                elif isinstance(block,dict) and block.get('type')=='input_text':content.append({'type':'text','text':block.get('text','')})
                else:content.append({'type':'text','text':json.dumps(block,ensure_ascii=False)})
            self.trace.complete(path,{'result':{'content':content}},None)
            row=json.loads(path.read_text(encoding='utf-8'))
        evidence=path.with_name('native-event-'+str(row['read_id'])+'.json')
        write_record(evidence,event)
        row['native_completion_event_path']=str(evidence)
        row['timing_basis']='tool_start_end_timestamps_unavailable'
        write_record(path,row);self.trace.report(path.parent)

    def close(self, task_id):
        folder=self.trace.folder(task_id)
        for path in folder.glob('read-*.json'):
            row=json.loads(path.read_text(encoding='utf-8'))
            if row['result']['status']=='pending' and row['arguments'].get('native_tool'):
                row['result']={'status':'missing_output','images':[]}
                row['missing_reason']='no_unambiguous_native_completion'
                row['elapsed_seconds']=None
                write_record(path,row)
        self.trace.report(folder)


def sync_native_reads(trace, task_id, sessions, *, native_thread_id=None):
    """Read only explicit reservation tokens and their call-ID outputs at task finish."""
    from pathlib import Path
    recorder=NativeWebRecorder(trace)
    folder=trace.folder(task_id)
    tokens=[p for p in folder.glob('read-*.json') if json.loads(p.read_text(encoding='utf-8'))['arguments'].get('native_tool')=='exec']
    if not tokens:return
    oldest=min(p.stat().st_mtime for p in tokens)
    candidates={}
    for path in Path(sessions).rglob('rollout-*.jsonl'):
        if native_thread_id and native_thread_id not in path.name:continue
        if path.stat().st_mtime < oldest:continue
        thread=None;calls={};outputs={}
        with path.open(encoding='utf-8') as stream:
            for line in stream:
                try:event=json.loads(line)
                except ValueError:continue
                if event.get('type')=='session_meta':thread=event.get('payload',{}).get('id')
                if not thread or event.get('type')!='response_item':continue
                payload=event.get('payload',{})
                marker=HEADER.match(payload.get('input','')) if isinstance(payload.get('input'),str) else None
                cid=payload.get('call_id')
                if marker and marker[1]==task_id and payload.get('type')=='custom_tool_call' and payload.get('name')=='exec' and cid:
                    calls[cid]=(int(marker[2]),event)
                elif cid in calls and payload.get('type') in ('custom_tool_call_output','function_call_output'):
                    outputs[cid]=event
        for cid,(read_id,event) in calls.items():
            candidates.setdefault(read_id,{})[(thread,cid)]=(event,outputs.get(cid))
    for found in candidates.values():
        if len(found)!=1:continue
        (thread,cid),(event,output)=next(iter(found.items()))
        recorder.observe(thread,event)
        if output:recorder.observe(thread,output)
    recorder.close(task_id)
