"""Harness-independent session registry. Native IDs remain owned by the harness."""
import json,sqlite3,time,uuid,os
from pathlib import Path

def process_alive(pid):
 if os.name=='nt':
  import ctypes
  k=ctypes.windll.kernel32
  handle=k.OpenProcess(0x1000,False,pid)
  if not handle:return False
  code=ctypes.c_ulong()
  try:return bool(k.GetExitCodeProcess(handle,ctypes.byref(code))) and code.value==259
  finally:k.CloseHandle(handle)
 try:os.kill(pid,0);return True
 except OSError:return False

class Sessions:
 def __init__(self,path):
  Path(path).parent.mkdir(parents=True,exist_ok=True)
  self.db=sqlite3.connect(path,timeout=30)
  self.db.execute('CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, body TEXT NOT NULL)')
  self.db.execute('CREATE TABLE IF NOT EXISTS turns(session TEXT, request TEXT, body TEXT, PRIMARY KEY(session,request))')
  self.db.execute('CREATE TABLE IF NOT EXISTS session_configuration(session TEXT PRIMARY KEY, body TEXT NOT NULL)')
  self.db.commit()
 def __enter__(self):return self
 def __exit__(self,*args):self.db.close()
 def create(self,*,harness,model,effort,account_id=None,group_id=None,native_session_id=None,purpose='chat',bot_ref=None):
  if harness not in ('codex','antigravity'):raise ValueError('unknown harness')
  if purpose not in ('chat','learning','research','screening'):raise ValueError('unknown purpose')
  if purpose in ('chat','screening') and (account_id is None or group_id is None):raise ValueError('chat binding required')
  s=dict(session_id=uuid.uuid4().hex,harness=harness,model=model,effort=effort,purpose=purpose,native_session_id=native_session_id,status='idle',created_at=time.time())
  if account_id is not None:s['account_id']=str(account_id)
  if group_id is not None:s['group_id']=str(group_id)
  if bot_ref is not None:
   from control_plane import ControlPlane
   if bot_ref.get('kind')!='bot':raise ValueError('bot reference required')
   bot=ControlPlane(self).dereference(bot_ref)['body']
   if bot['account_id']!=s.get('account_id'):raise ValueError('bot account mismatch')
   s['bot_ref']=bot_ref
  with self.db:
   self.db.execute('BEGIN IMMEDIATE')
   if native_session_id and any(e['harness']==harness and e.get('native_session_id')==native_session_id for e in self.list()):raise ValueError('native thread already registered')
   self.db.execute('INSERT INTO sessions VALUES(?,?)',(s['session_id'],json.dumps(s)))
  return s
 def get(self,session_id):
  row=self.db.execute('SELECT body FROM sessions WHERE id=?',(session_id,)).fetchone()
  if row is None:raise ValueError('unknown session')
  s=json.loads(row[0])
  extra=self.db.execute('SELECT body FROM session_configuration WHERE session=?',(session_id,)).fetchone()
  if extra:s.update(json.loads(extra[0]))
  if s.get('run_path'):
   run=Path(s['run_path'])
   try:alive=process_alive(int((run/'codex.pid').read_text()))
   except (OSError,ValueError):alive=False
   s['status']='stopped' if (run/'exit.json').exists() else ('running' if alive else 'unknown')
  return s
 def list(self):return [self.get(r[0]) for r in self.db.execute('SELECT id FROM sessions ORDER BY rowid')]

 def _save(self,s):
  # Runtime updates must not copy separately managed bindings into the base row.
  original=json.loads(self.db.execute('SELECT body FROM sessions WHERE id=?',(s['session_id'],)).fetchone()[0])
  for key in ('native_session_id','status'):original[key]=s[key]
  self.db.execute('UPDATE sessions SET body=? WHERE id=?',(json.dumps(original),s['session_id']))
 def detach(self,session_id):
  s=self.get(session_id)
  if not s.get('run_path'):raise ValueError('only adopted runner can be detached')
  with self.db:self.db.execute('DELETE FROM sessions WHERE id=?',(session_id,))
  return {'detached':session_id,'runner_unchanged':True}
 def history(self,session_id):
  s=self.get(session_id)
  if s.get('run_path'):
   events=[]
   for line in (Path(s['run_path'])/'run.jsonl').read_text(encoding='utf-8').splitlines():
    try:events.append({'event':json.loads(line),'source':str(Path(s['run_path'])/'run.jsonl')})
    except ValueError:continue
   return events
  return [json.loads(r[0]) for r in self.db.execute('SELECT body FROM turns WHERE session=? ORDER BY rowid',(session_id,))]
 def send(self,session_id,prompt,*,request_id,execute):
  if not prompt.strip() or not request_id:raise ValueError('prompt and request_id required')
  with self.db:
   self.db.execute('BEGIN IMMEDIATE')
   s=self.get(session_id)
   if s.get('runtime_refs',{}).get('scheduler'):raise ValueError('externally managed by existing scheduler')
   if s.get('run_path'):raise ValueError('externally managed by existing chat runner')
   row=self.db.execute('SELECT body FROM turns WHERE session=? AND request=?',(session_id,request_id)).fetchone()
   if row:return json.loads(row[0])
   if s['status']!='idle':raise ValueError('session not idle')
   turn=dict(request_id=request_id,session_id=session_id,prompt=prompt,status='running',started_at=time.time(),native_session_id=s['native_session_id'])
   self.db.execute('INSERT INTO turns VALUES(?,?,?)',(session_id,request_id,json.dumps(turn)))
   s['status']='running';self._save(s)
  try:
   result=execute(s,prompt)
   turn.update(result)
   if result.get('status')!='success':turn['status']='unknown'
   if result.get('native_session_id'):s['native_session_id']=result['native_session_id']
  except Exception as exc:turn.update(status='unknown',error=type(exc).__name__+': '+str(exc))
  turn['finished_at']=time.time();turn['elapsed_seconds']=turn['finished_at']-turn['started_at']
  from continuation_policy import auxiliary_read_denial
  recoverable=s['harness']=='antigravity' and s.get('purpose')=='chat' and auxiliary_read_denial(turn)
  if recoverable:turn['continuation']={'action':'abandon_auxiliary_read','reason':'explicit_read_permission_denial'}
  s['status']='idle' if turn['status']=='success' or recoverable else 'unknown'
  with self.db:
   self._save(s);self.db.execute('UPDATE turns SET body=? WHERE session=? AND request=?',(json.dumps(turn),session_id,request_id))
  return turn

 def adopt(self,*,run_path,tulpa_session_id,**kwargs):
  run=Path(run_path).resolve()
  native=kwargs.get('native_session_id')
  if not native or not tulpa_session_id:raise ValueError('native and Tulpa IDs required')
  events=[]
  for line in (run/'run.jsonl').read_text(encoding='utf-8').splitlines():
   try:events.append(json.loads(line))
   except ValueError:continue
  if not any(e.get('type')=='thread.started' and e.get('thread_id')==native for e in events):raise ValueError('native ID does not match runner')
  with self.db:
   self.db.execute('BEGIN IMMEDIATE')
   for existing in self.list():
    if existing['harness']==kwargs['harness'] and existing.get('native_session_id')==native:
     if existing.get('run_path')!=str(run):raise ValueError('native thread already registered')
     return existing
   # Inline insertion keeps adoption atomic.
   s=dict(kwargs,session_id=uuid.uuid4().hex,status='running',created_at=time.time(),run_path=str(run),tulpa_session_id=tulpa_session_id,management='existing-runner')
   self.db.execute('INSERT INTO sessions VALUES(?,?)',(s['session_id'],json.dumps(s)))
  return self.get(s['session_id'])
