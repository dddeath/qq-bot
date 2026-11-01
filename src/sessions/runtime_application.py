"""Durable application operations over existing fixed runtime snapshots."""
import copy
import json
import os
from pathlib import Path
import time

from runtime_configuration import settings, status, sha, consumer_names
from run_records import save
from sessions import process_alive


def bundle(path):
    path=Path(path).resolve()
    config=json.loads(path.read_text(encoding='utf-8'))
    if config.get('schema_version')!=2 or not config.get('conversations'):
        raise ValueError('fixed runtime configuration required')
    values={cid:settings(config,cid) for cid in config['conversations']}
    return path,config,values


def session_guard(plane,sid):
    value=plane.binding(sid)
    value['native_session_id']=plane.sessions.get(sid).get('native_session_id')
    return value


def build_preview(plane,*,config_path,previous_config_path):
    target,config,values=bundle(config_path)
    previous,old,prior=bundle(previous_config_path)
    if set(values)!=set(prior):raise ValueError('previous and target conversation scope must match')
    if status(previous)['status']!='loaded':raise ValueError('previous configuration requires complete loading evidence')
    guards={};consumers=[]
    for cid,value in values.items():
        meta=value['configuration'];before=prior[cid]['configuration']
        if (meta['session_id']!=before['session_id'] or
            meta['native_session_id']!=before['native_session_id']):
            raise ValueError('runtime session identity changed')
        sid=meta['session_id'];session=plane.sessions.get(sid)
        for key in ('account_id','group_id','harness','model','effort','native_session_id','bot_ref'):
            if session.get(key)!=meta[key]:raise ValueError('target snapshot no longer matches '+key)
        if not meta['native_session_id']:raise ValueError('registered native thread required')
        guards[sid]=session_guard(plane,sid)
        names=consumer_names(value)
        for screen_id in {meta.get('screening_session_id'),before.get('screening_session_id')}-{None}:
            screen=plane.sessions.get(screen_id)
            if (screen.get('purpose')!='screening' or screen.get('account_id')!=meta['account_id']
                or screen.get('group_id')!=meta['group_id'] or screen.get('bot_ref')!=meta['bot_ref']):
                raise ValueError('target screening binding mismatch')
            guards[screen_id]=session_guard(plane,screen_id)
        consumers.extend({'consumer':name,'conversation':cid,'session_id':sid,
            'native_session_id':meta['native_session_id'],'configuration_sha256':meta['configuration_sha256']}
            for name in names)
    result={'schema_version':1,'config_path':str(target),'previous_config_path':str(previous),
        'config_sha256':sha(target.read_bytes()),'previous_sha256':sha(previous.read_bytes()),
        'conversations':list(values),'sessions':guards,'consumers':consumers}
    result['preview_id']=plane._fingerprint(result)
    return result


def read(plane,operation_id):
    row=plane.db.execute('SELECT result FROM configuration_operations WHERE request_id=?',(operation_id,)).fetchone()
    if not row:raise ValueError('unknown runtime application')
    value=json.loads(row[0])
    if value.get('operation_type') not in ('runtime_apply','runtime_rollback'):
        raise ValueError('not a runtime application')
    return value


def store(plane,value):
    plane.db.execute('UPDATE configuration_operations SET result=? WHERE request_id=?',
        (json.dumps(value,ensure_ascii=False),value['operation_id']))


def dispatch_alive(value):
    if value.get('owner_pid') and process_alive(value['owner_pid']):return True
    for path in Path(value['config_path']).parent.glob('host-*.json'):
        item=json.loads(path.read_text(encoding='utf-8'))
        if (item.get('request',{}).get('operation_id')==value['operation_id']
            and item.get('finished_at') is None and item.get('pid') and process_alive(item['pid'])):
            return True
    return False


def observe(value):
    value=copy.deepcopy(value)
    receipts=status(value['config_path'])['consumers']
    for step in value['steps']:
        item=next(c for c in receipts if c['conversation']==step['conversation'] and c['consumer']==step['consumer'])
        receipt=item['observed']
        if (item['status']=='loaded' and receipt.get('application_id')==value['operation_id']
            and (step['consumer']!='chat' or receipt.get('native_session_id')==step['native_session_id'])):
            step.update(status='loaded',receipt=receipt,error=None)
    states=[s['status'] for s in value['steps']]
    if all(s=='loaded' for s in states):state='succeeded'
    elif value['dispatch_state']=='running':state='running' if dispatch_alive(value) else 'unknown'
    elif 'loaded' in states:state='partial'
    elif 'unknown' in states:state='unknown'
    elif 'failed' in states:state='failed'
    else:state='pending'
    value['status']=state
    return value


def get(plane,operation_id):
    return observe(read(plane,operation_id))


def require_available(plane,conversations):
    for raw, in plane.db.execute('SELECT result FROM configuration_operations'):
        existing=json.loads(raw)
        if existing.get('operation_type') in ('runtime_apply','runtime_rollback') and existing['dispatch_state'] in ('pending','running'):
            if set(existing['preview']['conversations']) & set(conversations):
                raise ValueError('another application is pending for conversation')


def start(plane,*,preview,request_id,directory):
    payload={'operation':'runtime_apply','preview':preview,'directory':str(Path(directory).resolve())}
    with plane.db:
        plane.db.execute('BEGIN IMMEDIATE')
        previous=plane._replay(request_id,payload)
        if previous is not None:return observe(previous)
        fresh=build_preview(plane,config_path=preview['config_path'],previous_config_path=preview['previous_config_path'])
        if fresh!=preview:raise ValueError('application preview is stale')
        require_available(plane,preview['conversations'])
        value=create_operation(plane,preview,request_id,directory,payload)
    return observe(value)


def create_operation(plane,view,request_id,directory,payload,rollback_of=None):
    if not Path(directory).is_absolute():raise ValueError('absolute application directory required')
    root=Path(directory).resolve();root.mkdir(parents=True,exist_ok=False)
    _,config,_=bundle(view['config_path'])
    config['receipt_root']=str(root/'loaded');config['application_id']=request_id
    path=root/'runtime-config.json';save(path,config)
    value={'schema_version':1,'operation_type':'runtime_rollback' if rollback_of else 'runtime_apply',
        'operation_id':request_id,'rollback_of':rollback_of,'adoption_registered':False,
        'created_at':time.time(),'dispatch_state':'pending','preview':copy.deepcopy(view),
        'config_path':str(path),'previous_config_path':view['previous_config_path'],
        'steps':[{**c,'status':'pending','error':None,'receipt':None} for c in view['consumers']]}
    plane._remember(request_id,payload,value)
    return value


def rollback(plane,operation_id,*,request_id,directory):
    payload={'operation':'runtime_rollback','parent':operation_id,'directory':str(Path(directory).resolve())}
    with plane.db:
        plane.db.execute('BEGIN IMMEDIATE')
        repeated=plane._replay(request_id,payload)
        if repeated is not None:return observe(repeated)
        parent=read(plane,operation_id)
        if parent['operation_type']!='runtime_apply' or parent['dispatch_state']!='finished':
            raise ValueError('finished application required before rollback')
        if parent.get('intent_changed'):raise ValueError('configuration intent changed during application')
        require_available(plane,parent['preview']['conversations'])
        for sid,guard in parent['completion_sessions'].items():
            if session_guard(plane,sid)!=guard:raise ValueError('session changed after application')
        path,config,values=bundle(parent['previous_config_path'])
        if status(path)['status']!='loaded':raise ValueError('rollback baseline loading evidence missing')
        consumers=[]
        for cid,value in values.items():
            meta=value['configuration']
            ids=[meta['session_id']]
            if meta.get('screening_session_id'):ids.append(meta['screening_session_id'])
            for sid in ids:
                row=plane.db.execute('SELECT body FROM session_configuration WHERE session=?',(sid,)).fetchone()
                body=json.loads(row[0]) if row else {}
                body['bot_ref']=meta['bot_ref']
                plane.db.execute('INSERT OR REPLACE INTO session_configuration VALUES(?,?)',(sid,json.dumps(body)))
            names=consumer_names(value)
            consumers.extend({'consumer':name,'conversation':cid,'session_id':meta['session_id'],
                'native_session_id':meta['native_session_id'],'configuration_sha256':meta['configuration_sha256']}
                for name in names)
        view={'schema_version':1,'config_path':str(path),'previous_config_path':parent['config_path'],
            'conversations':list(values),'consumers':consumers,
            'sessions':{sid:session_guard(plane,sid) for sid in parent['preview']['sessions']}}
        return observe(create_operation(plane,view,request_id,directory,payload,rollback_of=operation_id))


def finalize(plane,value):
    value=observe(value)
    identity=('purpose','account_id','group_id','harness','bot_ref','native_session_id')
    value['intent_changed']=any(any(session_guard(plane,sid).get(k)!=guard.get(k) for k in identity)
        for sid,guard in value['preview']['sessions'].items())
    registered_now=False
    if value['status']=='succeeded' and not value['adoption_registered']:
        if any(session_guard(plane,sid)!=guard for sid,guard in value.get('completion_sessions',{}).items()):
            value['registration_error']='Session changed since dispatch; loading evidence retained'
            store(plane,value)
            return value
        _,_,values=bundle(value['config_path'])
        for cid,settings in values.items():
            meta=settings['configuration']
            ids=[meta['session_id']]
            if meta.get('screening_session_id'):ids.append(meta['screening_session_id'])
            for sid in ids:
                row=plane.db.execute('SELECT body FROM session_configuration WHERE session=?',(sid,)).fetchone()
                overlay=json.loads(row[0]) if row else {}
                refs={**plane.sessions.get(sid).get('runtime_refs',{})}
                refs['applied_configuration']={'operation_id':value['operation_id'],'config_path':value['config_path'],
                    'bot_ref':meta['bot_ref'],'configuration_sha256':meta['configuration_sha256']}
                overlay['runtime_refs']=refs
                plane.db.execute('INSERT OR REPLACE INTO session_configuration VALUES(?,?)',(sid,json.dumps(overlay)))
        value['adoption_registered']=True
        registered_now=True
    if registered_now or 'completion_sessions' not in value:
        value['completion_sessions']={sid:session_guard(plane,sid) for sid in value['preview']['sessions']}
    store(plane,value)
    return value


def execute(plane,operation_id,*,reload_consumer):
    if reload_consumer is None:raise ValueError('runtime reload adapter not configured')
    with plane.db:
        plane.db.execute('BEGIN IMMEDIATE')
        value=read(plane,operation_id)
        if value['dispatch_state']!='pending':
            if value['dispatch_state']=='running' and not dispatch_alive(value):
                value.update(dispatch_state='finished',interrupted=True)
                for step in value['steps']:
                    if step['status']=='pending':step['status']='not_dispatched'
                return finalize(plane,value)
            if value['dispatch_state']=='finished' and not value['adoption_registered']:
                return finalize(plane,value)
            return observe(value)
        for sid,guard in value['preview']['sessions'].items():
            if session_guard(plane,sid)!=guard:
                value.update(dispatch_state='finished',error='application precondition changed')
                for step in value['steps']:step.update(status='failed',error=value['error'])
                return finalize(plane,value)
        bundle(value['config_path'])
        value.update(dispatch_state='running',owner_pid=os.getpid())
        store(plane,value)
    for index,step in enumerate(value['steps']):
        step.update(status='unknown',started_at=time.time())
        with plane.db:store(plane,value)
        request={**step,'operation_id':operation_id,'config_path':value['config_path']}
        error=None
        try:reload_consumer(request)
        except Exception as exc:error=type(exc).__name__+': '+str(exc)
        value=observe(value);step=value['steps'][index]
        if step['status']!='loaded':
            step.update(status='failed' if error else 'unknown',error=error or 'loading receipt missing')
        step['finished_at']=time.time()
        with plane.db:store(plane,value)
    with plane.db:
        value['dispatch_state']='finished'
        return finalize(plane,value)
