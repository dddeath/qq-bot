"""Fixed per-conversation runtime inputs and consumer-written loading evidence."""
import copy
import hashlib
import json
import os
from pathlib import Path
import time


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def export(plane, *, session_ids, expected_revisions, directory, screening_runtime, python, proxy):
    if not session_ids or len(set(session_ids)) != len(session_ids):
        raise ValueError('distinct chat session_ids required')
    if set(expected_revisions) != set(session_ids):
        raise ValueError('expected revisions required for every session')
    database = Path(plane.db.execute('PRAGMA database_list').fetchone()[2]).resolve()
    if Path(screening_runtime['sessions_database']).resolve() != database:
        raise ValueError('screening database mismatch')
    for name in ('sessions_database', 'state_root', 'evidence_root'):
        if not Path(screening_runtime[name]).is_absolute():
            raise ValueError('absolute screening runtime paths required')
    root=Path(directory).resolve()
    selected=[]; seen=set()
    with plane.db:
        plane.db.execute('BEGIN IMMEDIATE')
        sessions=plane.sessions.list()
        for sid in session_ids:
            session=plane.sessions.get(sid)
            if session['purpose']!='chat':raise ValueError('chat session required')
            if session['harness'] not in ('codex','antigravity'):raise ValueError('unsupported runtime harness')
            if plane.binding(sid)['revision']!=expected_revisions[sid]:
                raise ValueError('binding revision conflict')
            cid=session['account_id']+':group:'+session['group_id']
            if cid in seen:raise ValueError('duplicate conversation')
            seen.add(cid)
            effective=plane.effective(sid)
            if not effective['main_context'].get('target_window'):
                raise ValueError('explicit main_context.target_window required')
            screen=None
            if effective['activation'].get('enabled') and effective['screening'].get('enabled'):
                matches=[s for s in sessions if s.get('purpose')=='screening' and
                    s.get('account_id')==session['account_id'] and s.get('group_id')==session['group_id']]
                if len(matches)!=1:raise ValueError('one screening session required per conversation')
                screen=matches[0]
                if screen.get('bot_ref')!=session['bot_ref'] or screen['harness']!='codex':
                    raise ValueError('chat/screening fixed Bot reference mismatch')
            selected.append((session,cid,screen))
        root.mkdir(parents=True,exist_ok=False)
        config={'schema_version':2,'bots':{},'conversations':{},
                'receipt_root':str(root/'loaded'),'screening_runtime':copy.deepcopy(screening_runtime)}
        for session,cid,screen in selected:
            result=plane.export_tools(session['session_id'],root/session['session_id'],python=python,proxy=proxy)
            config['conversations'][cid]={'snapshot':result['snapshot'],
                'sha256':sha(Path(result['snapshot']).read_bytes()),
                'screening_session_id':screen['session_id'] if screen else None}
        path=root/'runtime-config.json'
        path.write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf-8')
    return {'config_path':str(path),'conversations':list(config['conversations']),
            'runtime_unchanged':True}


def settings(config, conversation):
    entry=config.get('conversations',{}).get(conversation)
    if entry is None:
        if config.get('schema_version')==2:
            raise ValueError('conversation missing from fixed runtime configuration')
        return config.get('bots',{}).get(conversation.split(':')[0],{})
    raw=Path(entry['snapshot']).read_bytes()
    if sha(raw)!=entry['sha256']:raise ValueError('runtime snapshot hash mismatch')
    snapshot=json.loads(raw)
    if conversation!=snapshot['account_id']+':group:'+snapshot['group_id']:
        raise ValueError('runtime snapshot conversation mismatch')
    value={**snapshot['activation'],'batching':copy.deepcopy(snapshot['batching']),
        'screening':copy.deepcopy(snapshot['screening']),
        'main_context':copy.deepcopy(snapshot['main_context'])}
    value['knowledge_application']=copy.deepcopy(snapshot.get('knowledge_application',{'enabled':False}))
    value['configuration']={key:snapshot[key] for key in
        ('session_id','account_id','group_id','harness','model','effort','native_session_id','bot_ref','tool_profile_ref')}
    value['configuration'].update(snapshot=entry['snapshot'],configuration_sha256=entry['sha256'],
        screening_session_id=entry.get('screening_session_id'),conversation=conversation)
    return value


def record_loaded(config, conversation, consumer, value, *, invocation=None, native_session_id=None, unapplied_settings=None):
    meta=value.get('configuration')
    if not meta:return None
    if consumer not in ('activation','screening','chat'):raise ValueError('unknown runtime consumer')
    from run_records import save
    root=Path(config['receipt_root']);root.mkdir(parents=True,exist_ok=True)
    result={'schema_version':1,'consumer':consumer,'status':'loaded','loaded_at':time.time(),
        'owner_pid':os.getpid(),'configuration':copy.deepcopy(meta),
        'settings':{k:copy.deepcopy(v) for k,v in value.items() if k!='configuration'},
        'invocation':invocation,'native_session_id':native_session_id}
    if unapplied_settings is not None:result['unapplied_settings']=list(unapplied_settings)
    if config.get('application_id'):result['application_id']=config['application_id']
    path=root/(sha(conversation.encode())+'-'+consumer+'.json')
    if invocation is not None and path.exists():
        previous=json.loads(path.read_text(encoding='utf-8'))
        if previous.get('configuration',{}).get('configuration_sha256')==meta['configuration_sha256']:
            result['loaded_at']=previous['loaded_at']
        result['invocation']={**invocation,'observed_at':time.time()}
    save(path,result)
    return result


def consumer_names(value):
    return ['activation']+(['screening'] if value.get('enabled') and value['screening'].get('enabled') else [])+['chat']


def status(config_path):
    config=json.loads(Path(config_path).read_text(encoding='utf-8'))
    consumers=[]
    for cid in config.get('conversations',{}):
        value=settings(config,cid); expected=value['configuration']['configuration_sha256']
        names=consumer_names(value)
        for name in names:
            path=Path(config['receipt_root'])/(sha(cid.encode())+'-'+name+'.json')
            observed=json.loads(path.read_text(encoding='utf-8')) if path.exists() else None
            matches=observed and observed.get('configuration',{}).get('configuration_sha256')==expected
            consumers.append({'conversation':cid,'consumer':name,'expected_configuration_sha256':expected,
                'status':'loaded' if matches and observed.get('status')=='loaded' else 'stale' if observed else 'unknown',
                'observed':observed})
    count=sum(c['status']=='loaded' for c in consumers)
    return {'status':'loaded' if consumers and count==len(consumers) else 'partial' if count else 'unknown',
            'consumers':consumers}


def chat_policy(policy, conversation):
    result=copy.deepcopy(policy or {})
    config_path=result.get('runtime_config')
    if config_path:
        config=json.loads(Path(config_path).read_text(encoding='utf-8'))
        value=settings(config,conversation)
        meta=value['configuration']
        if result.get('tool_snapshot') and Path(result['tool_snapshot']).resolve()!=Path(meta['snapshot']).resolve():
            raise ValueError('runtime tool snapshot conflicts with policy')
        result['tool_snapshot']=meta['snapshot']
        for key in ('model','effort'):
            if key in result and result[key]!=meta[key]:raise ValueError('runtime '+key+' conflicts with policy')
            result[key]=meta[key]
        result['_runtime_binding']={'config':config,'conversation':conversation,'settings':value}
    if result.get('tool_snapshot'):
        from qq_tool_runtime import load_snapshot
        snapshot=load_snapshot(result['tool_snapshot'],conversation=conversation)
        explicit=result.get('main_context',{})
        fixed=snapshot.get('main_context',{})
        for key,value in fixed.items():
            if key in explicit and explicit[key]!=value:
                raise ValueError('main_context.'+key+' conflicts with fixed snapshot')
        result['main_context']={**explicit,**fixed}
        from knowledge_application import policy as knowledge_policy
        fixed=knowledge_policy(snapshot.get('knowledge_application'))
        if 'knowledge_application' in result and knowledge_policy(result['knowledge_application'])!=fixed:
            raise ValueError('knowledge_application conflicts with fixed snapshot')
        result['knowledge_application']=fixed
    return result


def chat_loaded(policy, native_session_id):
    binding=policy.get('_runtime_binding')
    if binding:
        return record_loaded(binding['config'],binding['conversation'],'chat',binding['settings'],
                             native_session_id=native_session_id)
