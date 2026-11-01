"""Private stdio MCP facade for the unified session registry."""
import argparse,json,sys
from sessions import Sessions
from harnesses import Harnesses
import control_mcp
def tools():
 fields={'harness': {'type': 'string', 'description': 'Execution harness to use: codex or antigravity.'}, 'account_id': {'type': 'string', 'description': 'QQ login account ID as a decimal string.'}, 'group_id': {'type': 'string', 'description': 'QQ group ID as a decimal string.'}, 'model': {'type': 'string', 'description': 'Model identifier accepted by the configured harness.'}, 'effort': {'type': 'string', 'description': 'Reasoning effort accepted by the chosen model/harness.'}, 'native_session_id': {'type': 'string', 'description': 'Existing native harness thread/session ID; preserve it to resume that model context.'}};fields['harness']['enum']=['codex','antigravity']
 fields.update(purpose={'type':'string','enum':['chat','learning','research','screening'],'description':'Session role: chat, learning, research or screening.'},bot_ref={'type':'object','description':'Fixed Bot reference {kind:"bot", id, version}; obtain from configuration_get.'})
 return [dict(name=n,description=d,inputSchema={'type':'object','properties':p,'required':r,'additionalProperties':False},annotations={'readOnlyHint':n in ('session_list','session_get','session_history')}) for n,d,p,r in [
 ('session_list','List registered sessions for either harness.',{},[]),
 ('session_create','Register a session; an existing native ID preserves its context.',fields,['harness','model','effort']),
 ('session_adopt','Attach an existing live chat runner without starting or stopping it.',dict(fields,run_path={'type':'string', 'description': 'Absolute runtime Run directory on the executing host; not the registry Session ID.'},tulpa_session_id={'type':'string', 'description': 'Tulpa chat session_id bound to this runner; distinct from the unified and native session IDs.'}),['harness','account_id','group_id','model','effort','native_session_id','run_path','tulpa_session_id']),
 ('session_get','Read session status.',{'session_id':{'type':'string', 'description': 'Unified registry Session ID, not a native model thread or Tulpa chat ID.'}},['session_id']),
 ('session_history','Read messages, native events, errors and timings.',{'session_id':{'type':'string', 'description': 'Unified registry Session ID, not a native model thread or Tulpa chat ID.'}},['session_id']),
 ('session_send','Send one message or resume the stored native thread. Repeated request_id is not executed again.',{'session_id': {'type': 'string', 'description': 'Unified registry Session ID, not a native model thread or Tulpa chat ID.'}, 'prompt': {'type': 'string', 'description': 'Text to deliver to this native model session.'}, 'request_id': {'type': 'string', 'description': 'Stable request identifier for one operation; reuse unchanged arguments after an uncertain response.'}},['session_id','prompt','request_id'])]] + control_mcp.tools()
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
     methods={'session_list':api.list,'session_create':api.create,'session_adopt':api.adopt,'session_get':api.get,'session_history':api.history}
     try:
      control_mcp.validate(schema,args)
      if n in {tool['name'] for tool in control_mcp.tools()}:
       adapter=None
       if n=='runtime_application_execute' and c.get('runtime_reload'):
        from application_worker import CommandReloader
        adapter=CommandReloader(c['runtime_reload'])
       value=control_mcp.call(api,n,args,reload_consumer=adapter)
      else:value=api.send(**args,execute=execute) if n=='session_send' else methods[n](**args)
      result={'content':[{'type':'text','text':json.dumps(value,ensure_ascii=False)}]}
     except Exception as exc:result={'isError':True,'content':[{'type':'text','text':str(exc)}]}
    else:raise ValueError('unsupported method')
    response={'jsonrpc':'2.0','id':rid,'result':result}
   except Exception as exc:response={'jsonrpc':'2.0','id':req.get('id'),'error':{'code':-32602,'message':str(exc)}}
   print(json.dumps(response,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
