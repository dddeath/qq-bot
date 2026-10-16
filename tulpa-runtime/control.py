import sys,json,urllib.request,datetime,os
from pathlib import Path
run=Path.home()/'tulpa-test/evidence'/sys.argv[1]; mode=sys.argv[2] if len(sys.argv)>2 else 'status'
rows=[]
for line in (run/'run.jsonl').read_text().splitlines():
 try:rows.append(json.loads(line))
 except ValueError:pass
starts=[r['item'] for r in rows if r.get('type')=='item.completed' and r.get('item',{}).get('tool')=='start_chat_session']
result={'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'thread_id':next((r.get('thread_id') for r in rows if r.get('type')=='thread.started'),None),'host_exited':(run/'exit.json').exists()}
if starts:
 i=starts[-1];d=i['result'].get('structured_content') or json.loads(i['result']['content'][0]['text']);s=d['session'];sid=s['id']
 result.update(session_id=sid,persona=s.get('persona_name'),preset=s.get('persona_preset'),participation=s.get('participation'),receiver=s.get('receiver',{}).get('state'))
 if mode=='stop':
  req=urllib.request.Request('http://127.0.0.1:7861/api/mcp/chats/'+sid+'/stop',data=b'{}',headers={'Content-Type':'application/json','x-chatweave-ui':'1'})
  with urllib.request.urlopen(req,timeout=15) as response: stopped=json.load(response)
  result['active']=stopped['session']['active'];result['stopped']=stopped.get('event')
 else:
  with urllib.request.urlopen('http://127.0.0.1:7861/api/mcp/chats/'+sid+'/learning',timeout=15) as response:learning=json.load(response)
  result['learning_enabled']=learning.get('enabled')
  result['last_event']=rows[-1].get('type');item=rows[-1].get('item',{});result['last_tool']=item.get('tool');result['last_status']=item.get('status');result['last_text']=item.get('text')
else:result['pending_start']=True
out=run/(mode+'-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'.json');out.write_text(json.dumps(result,ensure_ascii=False));print(json.dumps(result,ensure_ascii=False))
