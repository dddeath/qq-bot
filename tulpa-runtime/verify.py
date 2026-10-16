"""Repeatable offline suite + read-only live MCP/config checks; unique evidence per run."""
import asyncio,datetime,json,subprocess,sys,tomllib,uuid
from pathlib import Path
from latency import write_report

async def live_check(home):
    import httpx
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    config=tomllib.loads((home/'.local/qq-bot-runtime/codex-home/config.toml').read_text())
    assert config['model']=='gpt-6.1-sol' and config['model_reasoning_effort']=='low'
    entry=config['mcp_servers']['tulpa']
    async with httpx.AsyncClient(headers=entry['http_headers'],timeout=20,trust_env=False) as http:
        async with streamable_http_client(entry['url'],http_client=http) as (read,write,_):
            async with ClientSession(read,write) as client:
                await client.initialize();tools=await client.list_tools();t=next(t for t in tools.tools if t.name=='send_chat_reply')
                assert len(t.inputSchema['properties']['bubbles']['items']['oneOf'])==3
                result=await client.call_tool('send_chat_reply',{'session_id':'a'*32,'plan_id':'b'*32,'bubbles':[{'kind':'text','text':'not sent','event_id':1}]})
                data=json.loads(next(c.text for c in result.content if c.type=='text'))
                assert data.get('error_code')=='invalid_arguments',data
    sessions=home/'.local/qq-bot-runtime/codex-home/sessions'
    p=next(sessions.rglob('*01a12be5-4aa1-75e1-8245-dbde4bfcaa83*'));contexts=[]
    for line in p.open():
        r=json.loads(line)
        if r.get('type')=='turn_context':contexts.append(r['payload'])
    context=contexts[-1];effort=context.get('effort') or context.get('reasoning_effort') or context.get('collaboration_mode',{}).get('settings',{}).get('reasoning_effort')
    assert context['model']=='gpt-6.1-sol' and effort=='low',(context['model'],effort)
    return {'schema_variants':3,'invalid_text_blocked_before_dispatch':True,'model':context['model'],'effort':effort}

if __name__=='__main__':
    home=Path.home();runtime=Path(__file__).parent
    result=subprocess.run([sys.executable,'-m','unittest','discover','-s','tests'],cwd=runtime,env=__import__('os').environ|{'PYTHONPATH':str(runtime)+':'+str(runtime.parent/'source')},capture_output=True,text=True)
    report={'command':[sys.executable,'-m','unittest','discover','-s','tests'],'exit_status':result.returncode,'stdout':result.stdout,'stderr':result.stderr}
    try:
        assert result.returncode==0
        report['live']=asyncio.run(live_check(home));report['passed']=True
    except Exception as e:report.update(passed=False,error=str(e))
    p=write_report(runtime.parent/'evidence/runtime-verification',report);print(json.dumps({'record':str(p),'passed':report['passed'],'live':report.get('live'),'error':report.get('error')}));sys.exit(0 if report['passed'] else 1)
