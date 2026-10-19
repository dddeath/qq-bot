"""Versioned configuration objects, independent of running processes."""
import copy
import json
import re
import time
from pathlib import Path
import qq_tools


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
        if kind == 'tool_profile':
            qq_tools.configured(body, {})
        if kind == 'bot' and body.get('tool_profile'):
            qq_tools.configured(self.dereference(body['tool_profile'])['body'], body.get('qq_tools', {}))
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
                    disabled_tools=copy.deepcopy(source['body'].get('disabled_tools',{})) if disabled_tools is None else disabled_tools)
        if persona_ref:
            body['persona_ref'] = persona_ref
        if 'qq_tools' in source['body']:
            body['qq_tools'] = copy.deepcopy(source['body']['qq_tools'])
        return self.put('bot',id,body)

    def bind(self, session_id, *, purpose, bot_ref=None, runtime_refs=None):
        s=self.sessions.get(session_id)
        if purpose not in ('chat','learning','research','screening'):raise ValueError('unknown purpose')
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

    def publish_runtime(self, session_id, *, release, run_path, tool_snapshot=None):
        """Atomically register an observed deployment; never start or stop a runner."""
        if not release or not run_path:
            raise ValueError('release and run_path required')
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            row = self.db.execute('SELECT body FROM sessions WHERE id=?', (session_id,)).fetchone()
            if row is None:
                raise ValueError('unknown session')
            base = json.loads(row[0])
            row = self.db.execute('SELECT body FROM session_configuration WHERE session=?', (session_id,)).fetchone()
            overlay = json.loads(row[0]) if row else None
            before = {'base': copy.deepcopy(base), 'overlay': copy.deepcopy(overlay)}
            config = copy.deepcopy(overlay or {})
            refs = {**base.pop('runtime_refs', {}), **config.get('runtime_refs', {})}
            refs['release'] = release
            if tool_snapshot is not None:
                refs['tool_snapshot'] = tool_snapshot
            config['runtime_refs'] = refs
            config.pop('run_path', None)
            base['run_path'] = run_path
            after = {'base': base, 'overlay': config}
            if before == after:
                return dict(session_id=session_id, changed=False)
            self.db.execute('UPDATE sessions SET body=? WHERE id=?', (json.dumps(base), session_id))
            self.db.execute('INSERT OR REPLACE INTO session_configuration VALUES(?,?)', (session_id, json.dumps(config)))
            return dict(session_id=session_id, changed=True, before=before, after=after)

    def rollback_publication(self, receipt):
        if not receipt['changed']:
            return {'changed': False}
        sid = receipt['session_id']
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            row = self.db.execute('SELECT body FROM sessions WHERE id=?', (sid,)).fetchone()
            extra = self.db.execute('SELECT body FROM session_configuration WHERE session=?', (sid,)).fetchone()
            current = {'base': json.loads(row[0]) if row else None,
                       'overlay': json.loads(extra[0]) if extra else None}
            if current == receipt['before']:
                return {'changed': False}
            if current != receipt['after']:
                raise ValueError('session changed since publication')
            self.db.execute('UPDATE sessions SET body=? WHERE id=?', (json.dumps(receipt['before']['base']), sid))
            if receipt['before']['overlay'] is None:
                self.db.execute('DELETE FROM session_configuration WHERE session=?', (sid,))
            else:
                self.db.execute('INSERT OR REPLACE INTO session_configuration VALUES(?,?)', (sid, json.dumps(receipt['before']['overlay'])))
        return {'changed': True, 'runtime_unchanged': True}

    def runs(self, session_id):
        from run_records import receipt, from_turn
        from sessions import process_alive
        s = self.sessions.get(session_id)
        def read(path):
            record_path = path/'run-receipt.json'
            if record_path.exists():
                item = json.loads(record_path.read_text(encoding='utf-8'))
                if item.get('session_id') not in (None, session_id):
                    raise ValueError('run session mismatch')
                item['session_id'] = session_id
                if item['status'] == 'running' and (not item.get('owner_pid') or not process_alive(item['owner_pid'])):
                    item['status'] = 'unknown'
                return item
            item = receipt(s, str(path), status='unknown', evidence=str(path))
            item['native_session_id'] = None if s.get('purpose') == 'learning' else s.get('native_session_id')
            log = path/'execution.jsonl'
            if log.exists():
                for line in log.read_text(encoding='utf-8').splitlines():
                    try: event = json.loads(line)
                    except ValueError: continue
                    if event.get('type') == 'thread.started':
                        item['native_session_id'] = event.get('thread_id'); break
            execution = path/'execution-result.json'
            if execution.exists():
                result = json.loads(execution.read_text(encoding='utf-8'))
                item.update(result={'execution':result}, elapsed_seconds=result.get('elapsed_seconds'))
                if result.get('exit_status') not in (None, 0):
                    item['status']='failed'
            applied = path/'apply.json'
            if applied.exists():
                result = json.loads(applied.read_text(encoding='utf-8'))
                from run_records import state
                item.update(status=state(result.get('state')), result={**(item['result'] or {}),'publication':result}, error=result.get('error'))
            elif s.get('run_path') == str(path):
                exit_path=path/'exit.json'
                if exit_path.exists():
                    result=json.loads(exit_path.read_text(encoding='utf-8'))
                    item.update(status='succeeded' if result.get('exit_code')==0 else 'failed' if result.get('exit_code') is not None else 'unknown',
                                result=result,finished_at=result.get('at'))
                else:
                    item['status'] = 'running' if s['status'] == 'running' else 'unknown'
            return item
        root = s.get('runtime_refs', {}).get('learning_runs_root')
        if root:
            return [read(path) for path in sorted(Path(root).iterdir()) if path.is_dir()]
        if s.get('run_path'):
            path=Path(s['run_path'])
            records=[read(path)]
            background=path/'background-runs.jsonl'
            if background.exists():
                latest={}
                for line in background.read_text(encoding='utf-8').splitlines():
                    try:item=json.loads(line)
                    except ValueError:continue
                    item['parent_session_id']=session_id
                    latest[item['run_id']]=item
                records.extend(latest.values())
            return records
        return [from_turn(s, turn) for turn in self.sessions.history(session_id)]

    def effective(self, session_id):
        session = self.sessions.get(session_id)
        bot = self.dereference(session['bot_ref'])['body']
        if str(bot['account_id']) != session.get('account_id'):
            raise ValueError('bot account mismatch')
        profile = self.dereference(bot['tool_profile'])['body']
        qq = qq_tools.configured(profile, bot.get('qq_tools', {}))
        bindings = {**bot.get('bindings',{}), **qq_tools.parameter_bindings(qq),
                    'account_id':session['account_id'], 'group_id':session['group_id']}
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
        resolved_qq = qq_tools.resolve(qq, servers, account_id=session['account_id'], group_id=session['group_id']) if qq else None
        if resolved_qq:
            notes=bot.get('qq_guide_notes',{})
            for name,cap in resolved_qq['capabilities'].items():
                note=notes.get(name,{})
                cap['guide']=expand(cap['guide']+'\n'+note.get('guide','')).strip()
                cap['sections']={section:expand(text+'\n'+note.get('sections',{}).get(section,''))
                                 for section,text in cap.get('sections',{}).items()}
                cap['guide_sha256']=qq_tools.guide_hash(cap)
            resolved_qq['startup']=expand(resolved_qq['startup']+'\n'+bot.get('qq_context','')).strip()
        return dict(session_id=session_id,bot_ref=session['bot_ref'],tool_profile_ref=bot['tool_profile'],
                    qq_tools=resolved_qq,
                    servers=servers,unavailable=unavailable,persona_ref=bot.get('persona_ref'),
                    activation=copy.deepcopy(bot.get('activation', {'enabled':False})),
                    batching=copy.deepcopy(bot.get('batching', {})),
                    screening=copy.deepcopy(bot.get('screening', {'enabled':False})),
                    main_context=copy.deepcopy(bot.get('main_context', {})),
                    applied=session.get('runtime_refs',{}).get('applied_configuration'))

    def export_tools(self, session_id, directory, *, python, proxy):
        effective=self.effective(session_id)
        for name,c in effective['servers'].items():
            if not c.get('command') and not c.get('url'):raise ValueError('stdio or HTTP adapter required: '+name)
        root=Path(directory).resolve();root.mkdir(parents=True,exist_ok=False)
        snapshot=root/'tool-profile.json';mcp=root/'mcp_config.json'
        snapshot.write_text(json.dumps(effective,ensure_ascii=False,indent=2),encoding='utf-8')
        from qq_tool_runtime import server_configs
        servers=server_configs(effective,snapshot,python=python,proxy=proxy)
        mcp.write_text(json.dumps({'mcpServers':servers},indent=2),encoding='utf-8')
        allow=[f'mcp({name}/{tool})' for name,c in effective['servers'].items() for tool in c['tools']]
        if effective.get('qq_tools'):
            if effective['qq_tools']['capabilities']:
                allow.append('mcp(qq-guides/read_qq_tool_guide)')
            (root/'qq-startup.md').write_text(effective['qq_tools']['startup'],encoding='utf-8')
        return dict(snapshot=str(snapshot),mcp_config=str(mcp),allow=allow,unavailable=effective['unavailable'])
