"""OneBot HTTP and WebSocket action transport."""
import json,time,urllib.request

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

