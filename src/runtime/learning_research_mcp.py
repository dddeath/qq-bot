"""Read-only MCP gateway for an independent learning run; all reads share one ledger."""
import asyncio
import base64
from contextlib import AsyncExitStack
import json
import os
from pathlib import Path
import sys
import time
from learning_research import ReadBudget, ALLOWED

async def main(config_path):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, TextContent
    cfg=json.loads(Path(config_path).read_text(encoding='utf-8'));root=Path(cfg['folder'])
    budget=ReadBudget(root/'budget.db');app=Server('learning-reads');available={};schemas=[]
    async with AsyncExitStack() as stack:
        for name,c in cfg['servers'].items():
            try:
                inp,out=await stack.enter_async_context(stdio_client(StdioServerParameters(command=c['command'],args=c.get('args',[]),env=os.environ|c.get('env',{}))))
                session=await stack.enter_async_context(ClientSession(inp,out));await session.initialize()
                for tool in (await session.list_tools()).tools:
                    if tool.name not in ALLOWED:continue
                    schema=json.loads(json.dumps(tool.inputSchema));schema.setdefault('properties',{}).update(reading_purpose={'type':'string','enum':['targeted','explore']},reading_reason={'type':'string','minLength':1})
                    schema['required']=list(dict.fromkeys(schema.get('required',[])+['reading_purpose','reading_reason']))
                    schemas.append(Tool(name=tool.name,description=tool.description,inputSchema=schema,annotations=tool.annotations));available[tool.name]=session
            except Exception as exc:
                with (root/'gateway-errors.jsonl').open('a') as f:f.write(json.dumps({'server':name,'error':str(exc)})+'\n')
        schemas.append(Tool(name='declare_web_search',description='Reserve one native web search and record its purpose before using web search. Search consumes shared budget.',inputSchema={'type':'object','properties':{'reading_purpose':{'type':'string','enum':['targeted','explore']},'reading_reason':{'type':'string','minLength':1}},'required':['reading_purpose','reading_reason'],'additionalProperties':False}))
        @app.list_tools()
        async def list_tools():return schemas
        @app.call_tool()
        async def call_tool(name,arguments):
            args=dict(arguments);purpose=args.pop('reading_purpose',None);reason=args.pop('reading_reason',None)
            if name not in available and name!='declare_web_search':raise ValueError('read_tool_not_enabled')
            tool='web_search' if name=='declare_web_search' else name
            index=budget.reserve(tool,purpose,reason);started=time.time()
            record={'read_id':index,'tool':tool,'arguments':args,'action':{'kind':tool,'purpose':purpose},'purpose_record':{'question':reason,'source':'learning_model'},'started_at':started,'result':{'status':'pending','images':[]}}
            path=root/f'read-{index:03d}.json';path.write_text(json.dumps(record,ensure_ascii=False),encoding='utf-8')
            try:
                if name=='declare_web_search':
                    result=[TextContent(type='text',text=f'Web search reserved as read_id={index}. Perform one search now.')]
                    record['result']['status']='reserved'
                else:
                    with budget.db() as db:deadline=db.execute('select deadline from settings').fetchone()[0]
                    reply=await asyncio.wait_for(available[name].call_tool(name,args),max(.01,deadline-time.time()))
                    result=reply.content;record['result']['status']='error' if reply.isError else 'ok'
                    record['result']['text']='\n'.join(c.text for c in result if c.type=='text')
                    for n,c in enumerate(result):
                        if c.type=='image':
                            ext={'image/png':'png','image/jpeg':'jpg','image/webp':'webp'}.get(c.mimeType,'img')
                            p=root/f'read-{index:03d}-image-{n}.{ext}';p.write_bytes(base64.b64decode(c.data,validate=True))
                            record['result']['images'].append({'path':str(p),'mime_type':c.mimeType})
                with budget.db() as db:
                    rows=db.execute("select overview from calls").fetchall()
                    units=db.execute("select units from settings").fetchone()[0]
                return [TextContent(type='text',text=json.dumps({'read_id':index,'remaining_read_units':max(0,units-sum(not x[0] for x in rows))})),*result]
            except Exception as exc:
                record['result'].update(status='error',error=str(exc));raise
            finally:
                record['finished_at']=time.time();record['elapsed_seconds']=time.time()-started
                path.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
        async with stdio_server() as (read,write):
            await app.run(read,write,app.create_initialization_options())

if __name__=='__main__':asyncio.run(main(sys.argv[1]))
