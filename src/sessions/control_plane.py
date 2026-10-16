"""Versioned configuration objects, independent of running processes."""
import copy
import json
import re
import time
from pathlib import Path


class ControlPlane:
    KINDS = ('bot', 'learning_job', 'tool_profile')

    def __init__(self, sessions):
        self.sessions = sessions
        self.db = sessions.db
        self.db.execute('CREATE TABLE IF NOT EXISTS configurations(kind TEXT, id TEXT, version INTEGER, body TEXT, PRIMARY KEY(kind,id,version))')
        self.db.commit()

    def get(self, kind, id, version=None):
        if kind not in self.KINDS:
            raise ValueError('unknown object kind')
        rows = self.db.execute('SELECT version,body FROM configurations WHERE kind=? AND id=?' + (' AND version=?' if version is not None else '') + ' ORDER BY version DESC LIMIT 1', (kind,id,version) if version is not None else (kind,id)).fetchone()
        if not rows:
            raise ValueError('unknown configuration')
        return dict(kind=kind,id=id,version=rows[0],ref={'kind':kind,'id':id,'version':rows[0]},body=json.loads(rows[1]))

    def list(self, kind=None):
        return [self.get(k,i) for k,i in self.db.execute('SELECT DISTINCT kind,id FROM configurations ORDER BY kind,id') if kind is None or k == kind]

    def dereference(self, ref):
        return self.get(ref['kind'], ref['id'], ref['version'])

    def put(self, kind, id, body, expected_version=0):
        if kind not in self.KINDS or not isinstance(body, dict) or not id:
            raise ValueError('invalid configuration')
        if kind == 'bot':
            if not body.get('account_id') or not isinstance(body.get('bindings',{}),dict):
                raise ValueError('bot account and bindings required')
            if body.get('tool_profile'):
                if body['tool_profile'].get('kind') != 'tool_profile':
                    raise ValueError('tool profile reference required')
                self.dereference(body['tool_profile'])
        if kind == 'learning_job':
            s = self.sessions.get(body['session_id'])
            if s.get('purpose') != 'learning':
                raise ValueError('learning session required')
        if kind == 'tool_profile' and not isinstance(body.get('servers'), dict):
            raise ValueError('servers required')
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            row = self.db.execute('SELECT version,body FROM configurations WHERE kind=? AND id=? ORDER BY version DESC LIMIT 1', (kind,id)).fetchone()
            if row and json.loads(row[1]) == body:
                return self.get(kind,id)
            current = row[0] if row else 0
            if current != expected_version:
                raise ValueError('configuration version conflict')
            self.db.execute('INSERT INTO configurations VALUES(?,?,?,?)',(kind,id,current+1,json.dumps(body,ensure_ascii=False)))
        return self.get(kind,id)

    def inherit_bot(self, id, *, source_bot_ref, account_id, bindings, disabled_tools=None, persona_ref=None):
        source = self.dereference(source_bot_ref)
        if source['kind'] != 'bot':
            raise ValueError('source bot required')
        body = dict(account_id=str(account_id), bindings=bindings,
                    tool_profile=source['body']['tool_profile'], inherited_from=source_bot_ref,
                    disabled_tools=disabled_tools or {})
        if persona_ref:
            body['persona_ref'] = persona_ref
        return self.put('bot',id,body)

    def bind(self, session_id, *, purpose, bot_ref=None, runtime_refs=None):
        s=self.sessions.get(session_id)
        if purpose not in ('chat','learning','research'):raise ValueError('unknown purpose')
        if bot_ref:
            if bot_ref.get('kind')!='bot':raise ValueError('bot reference required')
            if self.dereference(bot_ref)['body']['account_id']!=s.get('account_id'):raise ValueError('bot account mismatch')
        body={'purpose':purpose,'runtime_refs':runtime_refs or {}}
        if bot_ref:body['bot_ref']=bot_ref
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            row=self.db.execute('SELECT body FROM session_configuration WHERE session=?',(session_id,)).fetchone()
            before=json.loads(row[0]) if row else None
            if before==body:return dict(session_id=session_id,changed=False)
            self.db.execute('INSERT OR REPLACE INTO session_configuration VALUES(?,?)',(session_id,json.dumps(body)))
        return dict(session_id=session_id,changed=True,before=before,after=body)

    def rollback_binding(self, receipt):
        if not receipt['changed']:return {'changed':False}
        sid=receipt['session_id']
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            row=self.db.execute('SELECT body FROM session_configuration WHERE session=?',(sid,)).fetchone()
            current=json.loads(row[0]) if row else None
            if current==receipt['before']:return {'changed':False}
            if current!=receipt['after']:raise ValueError('binding changed since migration')
            if receipt['before'] is None:self.db.execute('DELETE FROM session_configuration WHERE session=?',(sid,))
            else:self.db.execute('UPDATE session_configuration SET body=? WHERE session=?',(json.dumps(receipt['before']),sid))
        return {'changed':True,'runtime_unchanged':True}

    def runs(self, session_id):
        s=self.sessions.get(session_id)
        root=s.get('runtime_refs',{}).get('learning_runs_root')
        if root:
            records=[]
            for path in sorted(Path(root).iterdir()):
                if not path.is_dir():continue
                record=dict(run_id=path.name,session_id=session_id,evidence=str(path),native_session_id=None,status='unknown',elapsed_seconds=None)
                events=path/'execution.jsonl'
                if events.exists():
                    for line in events.read_text(encoding='utf-8').splitlines():
                        try:event=json.loads(line)
                        except ValueError:continue
                        if event.get('type')=='thread.started':record['native_session_id']=event.get('thread_id');break
                result=path/'execution-result.json'
                if result.exists():
                    data=json.loads(result.read_text(encoding='utf-8'))
                    record.update(exit_status=data.get('exit_status'),elapsed_seconds=data.get('elapsed_seconds'),status='execution_succeeded' if data.get('exit_status')==0 else 'execution_failed')
                record['publication_record']=str(path/'apply.json') if (path/'apply.json').exists() else None
                records.append(record)
            return records
        if s.get('run_path'):
            return [{'run_id':s['run_path'],'session_id':session_id,'evidence':s['run_path'],'status':s['status'],'native_session_id':s.get('native_session_id'),'configuration':s.get('runtime_refs',{})}]
        return [dict(t,run_id=t['request_id']) for t in self.sessions.history(session_id)]

    def effective(self, session_id):
        session = self.sessions.get(session_id)
        bot = self.dereference(session['bot_ref'])['body']
        if str(bot['account_id']) != session.get('account_id'):
            raise ValueError('bot account mismatch')
        profile = self.dereference(bot['tool_profile'])['body']
        bindings = dict(bot.get('bindings',{}),account_id=session['account_id'],group_id=session['group_id'])
        def expand(value):
            if isinstance(value,str):
                def replace(match):
                    key=match.group(1)
                    if key not in bindings:raise ValueError('unbound tool parameter: '+key)
                    return str(bindings[key])
                return re.sub(r'\$\{([a-zA-Z0-9_]+)\}',replace,value)
            if isinstance(value,list):return [expand(v) for v in value]
            if isinstance(value,dict):return {k:expand(v) for k,v in value.items()}
            return value
        servers, unavailable = {}, {}
        for name, definition in profile['servers'].items():
            if any(str(session.get(k))!=str(v) for k,v in definition.get('binding_scope',{}).items()):
                unavailable[name]={'tools':definition.get('tools',[]),'reason':'recipient account/group adapter required'}
                continue
            if session['harness'] not in definition.get('harnesses',[]):
                unavailable[name]={'tools':definition.get('tools',[]),'reason':definition.get('reason','harness adapter pending')}
                continue
            cfg=expand(definition)
            disabled=bot.get('disabled_tools',{}).get(name,[])
            cfg['tools']=[x for x in cfg.get('tools',[]) if x not in disabled]
            servers[name]=cfg
        return dict(session_id=session_id,bot_ref=session['bot_ref'],tool_profile_ref=bot['tool_profile'],
                    servers=servers,unavailable=unavailable,persona_ref=bot.get('persona_ref'),
                    activation=copy.deepcopy(bot.get('activation', {'enabled':False})),
                    applied=session.get('runtime_refs',{}).get('applied_configuration'))

    def export_tools(self, session_id, directory, *, python, proxy):
        effective=self.effective(session_id)
        if self.sessions.get(session_id)['harness']!='antigravity':raise ValueError('export adapter not implemented for this harness')
        for name,c in effective['servers'].items():
            if not c.get('command') and not c.get('url'):raise ValueError('stdio or HTTP adapter required: '+name)
        root=Path(directory).resolve();root.mkdir(parents=True,exist_ok=False)
        snapshot=root/'tool-profile.json';mcp=root/'mcp_config.json'
        snapshot.write_text(json.dumps(effective,ensure_ascii=False,indent=2),encoding='utf-8')
        servers={name:{'command':python,'args':[proxy,'--config',str(snapshot),'--server',name]} for name,c in effective['servers'].items() if c['tools']}
        mcp.write_text(json.dumps({'mcpServers':servers},indent=2),encoding='utf-8')
        return dict(snapshot=str(snapshot),mcp_config=str(mcp),allow=[f'mcp({name}/{tool})' for name,c in effective['servers'].items() for tool in c['tools']],unavailable=effective['unavailable'])
