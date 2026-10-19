"""Private stdio MCP facade for the unified session registry."""
import argparse,json,sys
from sessions import Sessions
from harnesses import Harnesses
import control_mcp
def tools():
 fields={k:{'type':'string'} for k in ('harness','account_id','group_id','model','effort','native_session_id')};fields['harness']['enum']=['codex','antigravity']
 fields.update(purpose={'type':'string','enum':['chat','learning','research']},bot_ref={'type':'object'})
 return [dict(name=n,description=d,inputSchema={'type':'object','properties':p,'required':r,'additionalProperties':False},annotations={'readOnlyHint':n in ('session_list','session_get','session_history')}) for n,d,p,r in [
 ('session_list','List registered sessions for either harness.',{},[]),
 ('session_create','Register a session; an existing native ID preserves its context.',fields,['harness','model','effort']),
 ('session_adopt','Attach an existing live chat runner without starting or stopping it.',dict(fields,run_path={'type':'string'},tulpa_session_id={'type':'string'}),['harness','account_id','group_id','model','effort','native_session_id','run_path','tulpa_session_id']),
 ('session_get','Read session status.',{'session_id':{'type':'string'}},['session_id']),
 ('session_history','Read messages, native events, errors and timings.',{'session_id':{'type':'string'}},['session_id']),
 ('session_send','Send one message or resume the stored native thread. Repeated request_id is not executed again.',{k:{'type':'string'} for k in ('session_id','prompt','request_id')},['session_id','prompt','request_id'])]] + control_mcp.tools()
def main():
 p=argparse.ArgumentParser();p.add_argument('--config',required=True);a=p.parse_args();c=json.load(open(a.config,encoding='utf-8-sig'));execute=Harnesses(c['harnesses'],c['evidence'])
 with Sessions(c['database']) as api:
  for line in sys.stdin:
   req={}
   try:
    req=json.loads(line);rid=req.get('id');method=req.get('method')
    if rid is None:continue
    if method=='initialize':result={'protocolVersion':req['params']['protocolVersion'],'capabilities':{'tools':{}},'serverInfo':{'name':'unified-sessions','version':'0.1.0'}}
    elif method=='ping':result={}
    elif method=='tools/list':result={'tools':tools()}
    elif method=='tools/call':
     n=req['params']['name'];args=req['params'].get('arguments',{})
     schema=next((t['inputSchema'] for t in tools() if t['name']==n),None)
     if schema is None:raise ValueError('unknown tool')
     if set(args)-set(schema['properties']) or set(schema['required'])-set(args):raise ValueError('invalid arguments')
     control_mcp.validate(schema,args)
     methods={'session_list':api.list,'session_create':api.create,'session_adopt':api.adopt,'session_get':api.get,'session_history':api.history}
     try:
      if n.startswith('configuration_') or n in ('bot_inherit','session_bind','session_effective_configuration','session_runs','session_export_tools','session_publish_runtime','session_rollback_publication'):value=control_mcp.call(api,n,args)
      else:value=api.send(**args,execute=execute) if n=='session_send' else methods[n](**args)
      result={'content':[{'type':'text','text':json.dumps(value,ensure_ascii=False)}]}
     except Exception as exc:result={'isError':True,'content':[{'type':'text','text':str(exc)}]}
    else:raise ValueError('unsupported method')
    response={'jsonrpc':'2.0','id':rid,'result':result}
   except Exception as exc:response={'jsonrpc':'2.0','id':req.get('id'),'error':{'code':-32602,'message':str(exc)}}
   print(json.dumps(response,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
