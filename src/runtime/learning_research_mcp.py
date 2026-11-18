"""MCP reading gateway using the same task protocol as chat research proxies."""
import asyncio
from contextlib import AsyncExitStack
import json
import os
from pathlib import Path
import sys
from reading_tools import ALLOWED
from research_trace import ResearchTrace, CONTROL_TOOLS

async def main(config_path):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp.server import Server
    from mcp.server.lowlevel.server import NotificationOptions
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, TextContent
    cfg=json.loads(Path(config_path).read_text(encoding='utf-8'));root=Path(cfg['folder'])
    trace = ResearchTrace.for_servers(cfg['trace'], cfg['servers'])
    task_id=cfg.get('task_id');app=Server('learning-reads');available={};schemas=[]
    async with AsyncExitStack() as stack:
        for name,c in cfg['servers'].items():
            try:
                inp,out=await stack.enter_async_context(stdio_client(StdioServerParameters(command=c['command'],args=c.get('args',[]),env=os.environ|c.get('env',{}))))
                session=await stack.enter_async_context(ClientSession(inp,out));await session.initialize()
                for tool in (await session.list_tools()).tools:
                    if tool.name not in ALLOWED or ('tools' in c and tool.name not in c['tools']):continue
                    if tool.name in available:raise ValueError('duplicate_research_tool:'+tool.name)
                    schemas.append(tool.model_dump(mode='json',exclude_none=True));available[tool.name]=session
            except Exception as exc:
                with (root/'gateway-errors.jsonl').open('a') as f:f.write(json.dumps({'server':name,'error':str(exc)})+'\n')
        def catalog():
            exposed=[Tool.model_validate(s) for s in trace.schemas(schemas,task_id=task_id)]
            if not task_id:return [t for t in exposed if t.name=='begin_reading_task']
            folder=trace.folder(task_id)
            if (folder/'completion.json').exists():
                return [t for t in exposed if t.name=='finish_reading_task']
            from reading_budget import OVERVIEW
            overview_required=trace.task_budget(folder).overview_required()
            return [t for t in exposed if t.name!='begin_reading_task' and
                    (not overview_required or t.name in OVERVIEW or t.name in CONTROL_TOOLS)]
        def signature():
            return json.dumps([t.model_dump(mode='json') for t in catalog()],sort_keys=True)
        @app.list_tools()
        async def list_tools():return catalog()
        async def execute(name,arguments):
            nonlocal task_id
            if name=='begin_reading_task':
                if task_id:raise ValueError('reading_task_already_started')
                result=trace.control(name,arguments);task_id=result['task_id']
                return [TextContent(type='text',text=json.dumps(result,ensure_ascii=False))]
            supplied=arguments.get('task_id') if name in CONTROL_TOOLS else arguments.get('_reading',{}).get('task_id')
            if not task_id or supplied!=task_id:raise ValueError('reading_task_mismatch')
            if name in CONTROL_TOOLS:
                result=trace.control(name,arguments)
                return [TextContent(type='text',text=json.dumps(result,ensure_ascii=False))]
            if name not in available:raise ValueError('read_tool_not_enabled')
            async def invoke(tool,args):
                reply=await available[tool].call_tool(tool,args)
                return {'result':reply.model_dump(mode='json',by_alias=True,exclude_none=True)}
            response=await trace.execute(name,arguments,invoke)
            from mcp.types import CallToolResult
            reply=CallToolResult.model_validate(response['result'])
            return reply
        @app.call_tool()
        async def call_tool(name,arguments):
            before=signature()
            try:return await execute(name,arguments)
            finally:
                if signature()!=before:
                    await app.request_context.session.send_tool_list_changed()
        async with stdio_server() as (read,write):
            await app.run(read,write,app.create_initialization_options(NotificationOptions(tools_changed=True)))

if __name__=='__main__':asyncio.run(main(sys.argv[1]))
