"""Run a bounded explicit-mention QQ test against a registered session."""
import argparse,asyncio,json,time,urllib.request
from pathlib import Path
from sessions import Sessions
from harnesses import Harnesses
from qq_gateway import Gateway

def ws_connect(*args,**kwargs):
 from websockets.sync.client import connect
 return connect(*args,**kwargs)

def call(config,action,data):
 if config.get('transport')=='websocket':
  import uuid
  echo=uuid.uuid4().hex;deadline=time.monotonic()+20
  with ws_connect(config['ws'],additional_headers={'Authorization':'Bearer '+config['token']},open_timeout=10) as ws:
   ws.send(json.dumps({'action':action,'params':data,'echo':echo}))
   while time.monotonic()<deadline:
    response=json.loads(ws.recv(timeout=max(.1,deadline-time.monotonic())))
    if response.get('echo')==echo:return response
  raise TimeoutError('QQ action receipt timeout')
 req=urllib.request.Request(config['http'].rstrip('/')+'/'+action,data=json.dumps(data).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+config['token']})
 with urllib.request.urlopen(req,timeout=20) as response:return json.load(response)
async def run(config):
 from websockets.asyncio.client import connect
 cutoff=int(time.time());seconds=config.get('test_window_seconds',600)
 if config.get('stop_at_epoch') is not None:seconds=min(seconds,max(0,config['stop_at_epoch']-time.time()))
 deadline=time.monotonic()+seconds
 execute=Harnesses(config['harnesses'],config['evidence'])
 login=call(config['qq'],'get_login_info',{})
 with Sessions(config['database']) as api:
  session=api.get(config['session_id'])
  if str(login.get('data',{}).get('user_id'))!=session['account_id'] or login.get('retcode')!=0:raise ValueError('QQ login account mismatch')
  gateway=Gateway(api,config['session_id'],execute=execute,qq=lambda a,b:call(config['qq'],a,b))
  async with connect(config['qq']['ws'],additional_headers={'Authorization':'Bearer '+config['qq']['token']}) as ws:
   print(json.dumps({'stage':'READY','session_id':session['session_id'],'account':session['account_id'],'group':session['group_id'],'seconds':config.get('test_window_seconds',600)}),flush=True)
   while time.monotonic()<deadline:
    try:raw=await asyncio.wait_for(ws.recv(),timeout=max(.1,deadline-time.monotonic()))
    except asyncio.TimeoutError:break
    event=json.loads(raw)
    if event.get('time',0)<cutoff:continue
    # Keep the websocket heartbeat alive while the model is running; the worker
    # owns its SQLite connection and processes messages sequentially.
    def handle():
     with Sessions(config['database']) as worker:
      return Gateway(worker,config['session_id'],execute=execute,qq=lambda a,b:call(config['qq'],a,b),send_before=config.get('stop_at_epoch')).handle(event)
    result=await asyncio.to_thread(handle)
    if result:
     summary={k:result.get(k) for k in ('key','session_id','status','receipt','error','received_at','send_started_at','sent_at')}
     with Path(config['event_log']).open('a',encoding='utf-8') as f:f.write(json.dumps(summary)+'\n')
     print(json.dumps(summary),flush=True)
 print(json.dumps({'stage':'window_closed'}),flush=True)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--config',required=True);a=p.parse_args();asyncio.run(run(json.load(open(a.config,encoding='utf-8-sig'))))
