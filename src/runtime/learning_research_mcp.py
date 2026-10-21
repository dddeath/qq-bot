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
from research_trace import ResearchTrace

async def main(config_path):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, TextContent
    cfg=json.loads(Path(config_path).read_text(encoding='utf-8'));root=Path(cfg['folder'])
    trace=ResearchTrace(cfg['trace']);task_id=cfg['task_id'];root=trace.folder(task_id)
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
            reading={'task_id':task_id,'purpose':purpose,'reason':reason,'relation':args.pop('reading_relation',reason)}
            if name=='declare_web_search':
                path,_=trace.prepare('web_search',{'_reading':reading})
                record=json.loads(path.read_text(encoding='utf-8'));index=record['read_id']
                # Actual native result is attached by the owning executor, never by the model.
                return [TextContent(type='text',text=json.dumps({'read_id':index,'budget_remaining':trace.remaining(root)}))]
            async def invoke(tool,arguments):
                reply=await available[tool].call_tool(tool,arguments)
                return {'result':reply.model_dump(mode='json',exclude_none=True)}
            response=await trace.execute(name,{**args,'_reading':reading},invoke)
            from mcp.types import CallToolResult
            reply=CallToolResult.model_validate(response['result'])
            return [TextContent(type='text',text=json.dumps({'budget_remaining':trace.remaining(root)})),*reply.content]
        async with stdio_server() as (read,write):
            await app.run(read,write,app.create_initialization_options())

if __name__=='__main__':asyncio.run(main(sys.argv[1]))
