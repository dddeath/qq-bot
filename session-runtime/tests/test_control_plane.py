import tempfile
import unittest
import json
from pathlib import Path
from sessions import Sessions
from control_plane import ControlPlane


class ConfigurationTest(unittest.TestCase):
    def test_tulpa_http_profile_exports_recipient_binding_without_copying_token(self):
        with tempfile.TemporaryDirectory() as tmp, Sessions(Path(tmp)/'db') as sessions:
            p=ControlPlane(sessions)
            profile=p.put('tool_profile','tulpa',{'servers':{'tulpa':{'url':'${tulpa_url}','token_file':'${tulpa_token_file}','tools':['wait_chat_messages','send_chat_reply'],'harnesses':['antigravity']}}})
            bot=p.put('bot','pwie',{'account_id':'309','tool_profile':profile['ref'],'bindings':{'tulpa_url':'http://127.0.0.1:18778/mcp','tulpa_token_file':'/private/pwie-token'}})
            s=sessions.create(harness='antigravity',account_id='309',group_id='112',model='flash',effort='low',bot_ref=bot['ref'])
            result=p.export_tools(s['session_id'],Path(tmp)/'export',python='python',proxy='tool_proxy.py')
            snapshot=json.loads(Path(result['snapshot']).read_text())
            self.assertEqual(snapshot['servers']['tulpa']['url'],'http://127.0.0.1:18778/mcp')
            self.assertEqual(snapshot['servers']['tulpa']['token_file'],'/private/pwie-token')
            self.assertEqual(result['allow'],['mcp(tulpa/wait_chat_messages)','mcp(tulpa/send_chat_reply)'])

    def test_bot_and_learning_job_share_session_management_without_fake_qq_identity(self):
        with tempfile.TemporaryDirectory() as tmp, Sessions(Path(tmp) / 'db') as sessions:
            plane = ControlPlane(sessions)
            profile = plane.put('tool_profile', 'shared', {'servers': {}})
            bot = plane.put('bot', 'dragon', {'account_id': '457', 'tool_profile': profile['ref'], 'bindings': {}})
            chat = sessions.create(harness='codex', model='sol', effort='low', purpose='chat', bot_ref=bot['ref'], account_id='457', group_id='983')
            learning = sessions.create(harness='codex', model='astra', effort='medium', purpose='learning')
            job = plane.put('learning_job', 'daily', {'session_id': learning['session_id'], 'schedule': {'hour': 4, 'timezone': 'Asia/Taipei'}, 'scope': {'account_id': '457', 'group_id': '983'}, 'config_ref': '/existing/daily.json'})
            self.assertEqual(plane.get('learning_job', 'daily')['body']['session_id'], learning['session_id'])
            self.assertEqual(sessions.get(chat['session_id'])['bot_ref'], bot['ref'])
            self.assertNotIn('account_id', sessions.get(learning['session_id']))
            self.assertEqual(plane.get('bot', 'dragon')['body']['tool_profile'], profile['ref'])
            self.assertEqual(job['version'], 1)

    def test_inheritance_rebinds_target_scope_pins_version_and_reports_unadapted_tools(self):
        with tempfile.TemporaryDirectory() as tmp, Sessions(Path(tmp) / 'db') as sessions:
            p = ControlPlane(sessions)
            v1 = p.put('tool_profile', 'shared', {'servers': {
                'knowledge': {'command': 'python', 'args': ['knowledge.py'], 'env': {'ACCOUNT': '${account_id}', 'GROUP': '${group_id}'}, 'tools': ['search','read'], 'harnesses': ['codex','antigravity']},
                'qq': {'url': '${qq_url}', 'tools': ['send'], 'harnesses': ['codex'], 'reason': 'QQ event adapter required'}}})
            a = p.put('bot','dragon',{'account_id':'457','bindings':{'qq_url':'http://localhost:1'},'tool_profile':v1['ref']})
            b = p.inherit_bot('pwie', source_bot_ref=a['ref'], account_id='309', bindings={'qq_url':'http://localhost:2'})
            s = sessions.create(harness='antigravity',model='flash',effort='low',account_id='309',group_id='112',bot_ref=b['ref'])
            result = p.effective(s['session_id'])
            self.assertEqual(result['servers']['knowledge']['env'], {'ACCOUNT':'309','GROUP':'112'})
            self.assertEqual(result['unavailable']['qq']['reason'], 'QQ event adapter required')
            v2 = p.put('tool_profile','shared',{'servers':{}},expected_version=1)
            self.assertEqual(v2['version'],2)
            self.assertEqual(p.effective(s['session_id'])['tool_profile_ref']['version'],1)
            self.assertEqual(p.get('bot','dragon')['body']['bindings']['qq_url'],'http://localhost:1')
            with self.assertRaisesRegex(ValueError,'unbound'):
                c=p.inherit_bot('missing',source_bot_ref=a['ref'],account_id='300',bindings={})
                t=sessions.create(harness='codex',model='m',effort='low',account_id='300',group_id='112',bot_ref=c['ref'])
                p.effective(t['session_id'])

    def test_migration_is_repeatable_and_rollback_keeps_concurrent_turns(self):
        with tempfile.TemporaryDirectory() as tmp, Sessions(Path(tmp)/'db') as sessions:
            p=ControlPlane(sessions)
            profile=p.put('tool_profile','shared',{'servers':{}})
            bot=p.put('bot','dragon',{'account_id':'457','bindings':{},'tool_profile':profile['ref']})
            s=sessions.create(harness='codex',account_id='457',group_id='983',model='sol',effort='low',native_session_id='original')
            before=sessions.get(s['session_id'])
            receipt=p.bind(s['session_id'],purpose='chat',bot_ref=bot['ref'],runtime_refs={'config':'/existing/config'})
            self.assertEqual(p.bind(s['session_id'],purpose='chat',bot_ref=bot['ref'],runtime_refs={'config':'/existing/config'})['changed'],False)
            sessions.send(s['session_id'],'hello',request_id='new-turn',execute=lambda s,p:dict(status='success',response='hi',native_session_id='original'))
            self.assertEqual(sessions.get(s['session_id'])['bot_ref'],bot['ref'])
            self.assertEqual(p.runs(s['session_id'])[0]['request_id'],'new-turn')
            p.rollback_binding(receipt)
            self.assertEqual(sessions.get(s['session_id']),before)
            self.assertEqual(len(sessions.history(s['session_id'])),1)

    def test_learning_runs_keep_their_own_native_threads_and_external_scheduler(self):
        with tempfile.TemporaryDirectory() as tmp, Sessions(Path(tmp)/'db') as sessions:
            p=ControlPlane(sessions)
            root=Path(tmp)/'runs';run=root/'20261015-test';run.mkdir(parents=True)
            (run/'execution.jsonl').write_text(json.dumps({'type':'thread.started','thread_id':'daily-native'})+'\n')
            (run/'execution-result.json').write_text(json.dumps({'exit_status':0,'elapsed_seconds':32}))
            s=sessions.create(harness='codex',model='astra',effort='medium',purpose='learning')
            p.bind(s['session_id'],purpose='learning',runtime_refs={'learning_runs_root':str(root),'scheduler':'existing'})
            result=p.runs(s['session_id'])
            self.assertEqual(result[0]['native_session_id'],'daily-native')
            self.assertEqual(result[0]['elapsed_seconds'],32)
            self.assertIsNone(sessions.get(s['session_id'])['native_session_id'])
            with self.assertRaisesRegex(ValueError,'external'):
                sessions.send(s['session_id'],'run',request_id='forbidden',execute=lambda *a:self.fail('duplicate scheduler'))

    def test_export_uses_only_resolved_tools_and_session_specific_adapter(self):
        with tempfile.TemporaryDirectory() as tmp, Sessions(Path(tmp)/'db') as sessions:
            p=ControlPlane(sessions)
            profile=p.put('tool_profile','p',{'servers':{'knowledge':{'command':'python','args':['kb.py'],'env':{'GROUP':'${group_id}'},'tools':['read'],'harnesses':['antigravity']}}})
            bot=p.put('bot','pwie',{'account_id':'309','bindings':{},'tool_profile':profile['ref']})
            s=sessions.create(harness='antigravity',account_id='309',group_id='112',model='flash',effort='low',bot_ref=bot['ref'])
            out=p.export_tools(s['session_id'],str(Path(tmp)/'export'),python='/venv/python',proxy='/runtime/tool_proxy.py')
            cfg=json.loads(Path(out['mcp_config']).read_text())
            self.assertEqual(cfg['mcpServers']['knowledge']['args'][-1],'knowledge')
            self.assertEqual(json.loads(Path(out['snapshot']).read_text())['servers']['knowledge']['env']['GROUP'],'112')
            self.assertEqual(out['allow'],['mcp(knowledge/read)'])
            with self.assertRaises(FileExistsError):p.export_tools(s['session_id'],str(Path(tmp)/'export'),python='/venv/python',proxy='/runtime/tool_proxy.py')

    def test_stale_configuration_update_and_wrong_account_binding_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp, Sessions(Path(tmp)/'db') as sessions:
            p=ControlPlane(sessions)
            profile=p.put('tool_profile','shared',{'servers':{}})
            bot=p.put('bot','dragon',{'account_id':'457','bindings':{},'tool_profile':profile['ref']})
            with self.assertRaisesRegex(ValueError,'version conflict'):
                p.put('tool_profile','shared',{'servers':{},'note':'changed'},expected_version=0)
            s=sessions.create(harness='antigravity',model='flash',effort='low',account_id='309',group_id='112')
            with self.assertRaisesRegex(ValueError,'account mismatch'):
                p.bind(s['session_id'],purpose='chat',bot_ref=bot['ref'])

    def test_same_harness_inheritance_does_not_reuse_donor_qq_transport(self):
        with tempfile.TemporaryDirectory() as tmp, Sessions(Path(tmp)/'db') as sessions:
            p=ControlPlane(sessions)
            profile=p.put('tool_profile','shared',{'servers':{'qq':{'url':'http://donor/mcp','tools':['send'],'harnesses':['codex'],'binding_scope':{'account_id':'457','group_id':'983'}}}})
            bot=p.put('bot','dragon',{'account_id':'457','bindings':{},'tool_profile':profile['ref']})
            other=p.inherit_bot('other',source_bot_ref=bot['ref'],account_id='309',bindings={})
            s=sessions.create(harness='codex',account_id='309',group_id='112',model='sol',effort='low',bot_ref=other['ref'])
            effective=p.effective(s['session_id'])
            self.assertNotIn('qq',effective['servers'])
            self.assertEqual(effective['unavailable']['qq']['reason'],'recipient account/group adapter required')


if __name__ == '__main__':
    unittest.main()
