"""Recognize a denied auxiliary read without changing the recorded native outcome."""
import json
import shlex


def auxiliary_read_denial(result):
    if result.get('status')!='unknown' or not result.get('denied') or result.get('error') or result.get('exit_code')!=0:
        return False
    events=result.get('events',[])
    finals=[e.get('result',{}) for e in events if e.get('event')=='result']
    if not finals or finals[-1].get('status')!='SUCCESS':return False
    steps={}
    for e in events:
        s=e.get('step_update',{})
        if e.get('event')=='step_update' and s.get('step_type')=='tool':steps[s.get('step_index')]=s
    denied=0
    for s in steps.values():
        info=s.get('tool_info',{});name=s.get('tool_name');params=info.get('parameters',{})
        if s.get('state')=='ERROR':
            if name=='call_mcp_tool' and params.get('ToolName','').startswith(('get_','list_','read_','wait_','search_','check_')):continue
            error=info.get('error',{});message=str(error.get('message','')).lower()
            if 'permission' not in message or not any(x in message for x in ('denied','not allowed')):return False
            if name=='run_command':
                command=params.get('CommandLine','')
                if any(c in command for c in '$`;|&<>\n\r'):return False
                try:parts=shlex.split(command)
                except ValueError:return False
                if len(parts)!=4 or parts[:2]!=['grep','-n'] or not parts[-1].startswith('/') or not parts[-1].endswith('/.system_generated/logs/transcript.jsonl'):return False
            elif name not in ('view_file','read_file'):return False
            denied+=1
        elif s.get('state')!='DONE':return False
        elif name=='call_mcp_tool':
            tool=params.get('ToolName','')
            if tool.startswith(('get_','list_','read_','wait_','search_','plan_','check_')):continue
            try:receipt=json.loads(info.get('output',''))
            except (ValueError,TypeError):return False
            if not isinstance(receipt,dict) or receipt.get('state')!='SUCCEEDED':return False
        elif name=='run_command':return False
    return denied>0
