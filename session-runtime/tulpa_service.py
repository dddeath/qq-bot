"""Prepare a recipient-owned Tulpa service using an isolated source/data root."""
import argparse
import json
import os
from pathlib import Path
import signal
import sys
import threading


def prepare(config):
    source=Path(config['source']).resolve()
    sys.path.insert(0,str(source))
    from chatlocal.config import ROOT
    if ROOT.resolve()!=source:raise ValueError('Tulpa source root mismatch')
    connection=config['onebot']
    os.environ.update(REPLY_ONEBOT_URL=connection['url'],REPLY_ONEBOT_TOKEN=connection['token'],
                      REPLY_ONEBOT_WS_URL=connection['ws'],REPLY_ONEBOT_WS_TOKEN=connection['token'],REPLY_ONEBOT_WS_TOKEN_MODE='independent')
    if config.get('topic_settings'):
        settings=json.loads(Path(config['topic_settings']).read_text(encoding='utf-8'))
        if settings.get('mode')!='freshness_only' or settings.get('group')!=f"{config['account_id']}:group:{config['group_id']}":
            raise ValueError('topic adapter binding mismatch')
        os.environ['QQ_TOPIC_SETTINGS']=config['topic_settings']
        from topic_tulpa import install
        install()
    from chatlocal.store import Store
    from chatlocal.mcp_access import MCPAccess
    from chatlocal.mcp_server import MCPService
    access=MCPAccess(Store(source/'data/chats.sqlite3'))
    access.configure(True,config['port'])
    conversation=f"{config['account_id']}:group:{config['group_id']}"
    grant_path=Path(config['grant_file'])
    if grant_path.exists():
        grant=json.loads(grant_path.read_text(encoding='utf-8'))
        actual=access.authorize(grant['token'],source=False)
        if actual['scope'].get('chat_account')!=str(config['account_id']) or actual['scope']['conversations']!=[json.dumps(['qq',conversation])]:
            raise ValueError('saved Tulpa grant binding mismatch')
    else:
        grant=access.create(dict(name='Bot '+str(config['account_id']),platforms=['qq'],conversations=[['qq',conversation]],
                                chat=True,send=True,chat_images=True,chat_sticker_send=True,chat_sticker_collect=True,chat_reactions=True))
        grant_path.parent.mkdir(parents=True,exist_ok=True)
        with grant_path.open('x',encoding='utf-8') as f:json.dump(grant,f,ensure_ascii=False)
        grant_path.chmod(0o600)
    (access.path.parent/'mcp-self-qq.json').write_text(json.dumps({'enabled':True,'grant_ids':[grant['id']],'conversation_ids':[conversation]}),encoding='utf-8')
    if 'chat_policy' in config:
        (access.path.parent/'mcp-chat-policy.json').write_text(json.dumps(config['chat_policy']),encoding='utf-8')
    return MCPService(access),grant


def start_chat(service, grant, config):
    result=service.tools.call(grant['token'],'start_chat_session',{
        'conversation_id':f"{config['account_id']}:group:{config['group_id']}",
        'persona':Path(config['persona_file']).read_text(encoding='utf-8-sig'),
        'participation':config.get('participation','natural'),
        'idempotency_key':config['start_key']},threading.Event()).structuredContent
    if 'session' not in result:raise RuntimeError('Tulpa chat start failed: '+json.dumps(result,ensure_ascii=False))
    service.tools.chat.learning.configure(result['session']['id'],{'enabled':False})
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--config',required=True);args=parser.parse_args()
    config=json.loads(Path(args.config).read_text(encoding='utf-8-sig'))
    if config.get('topic_settings'):os.environ['QQ_TOPIC_SETTINGS']=config['topic_settings']
    service,grant=prepare(config)
    stop=threading.Event()
    for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,lambda *_:stop.set())
    service.start()
    try:
        if not service.status()['running']:raise RuntimeError('Tulpa MCP did not start')
        if config.get('persona_file'):
            chat=start_chat(service,grant,config)
            Path(config['chat_state_file']).write_text(json.dumps(chat,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'stage':'READY','account_id':config['account_id'],'group_id':config['group_id'],'service':service.status()}),flush=True)
        stop.wait()
    finally:service.stop()
