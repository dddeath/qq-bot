"""Read only the evidence bound to one review; every disclosure is recorded."""
import asyncio
import base64
import json
import sys
import time
import uuid
from pathlib import Path
from review_materials import ReviewMaterials

TOOLS = ('list_review_materials','read_review_material','read_review_image')


def cli_arguments(directory, python, deadline=None):
    server_args=[str(Path(__file__).resolve()),str(directory)]
    if deadline is not None:server_args.append(str(deadline))
    args = ['-c','mcp_servers.review_materials.enabled=true',
            '-c','mcp_servers.review_materials.command='+json.dumps(python),
            '-c','mcp_servers.review_materials.args='+json.dumps(server_args)]
    for name in TOOLS:
        args += ['-c',f'mcp_servers.review_materials.tools.{name}.approval_mode="approve"']
    return args


async def main(directory, deadline=None):
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool,TextContent,ImageContent,CallToolResult
    materials=ReviewMaterials(directory);app=Server('review-materials')
    page={'offset':{'type':'integer','minimum':0,'default':0},'limit':{'type':'integer','minimum':1,'maximum':6000,'default':6000}}
    descriptions=[
        ('list_review_materials','List the bound review evidence directory or a section. Start without section; then expand original/reads or extension/reads. No network read budget is spent.',
         {'section':{'type':['string','null']},'offset':page['offset'],'limit':{'type':'integer','minimum':1,'maximum':20,'default':8}},[]),
        ('read_review_material','Read one material. Default outline returns field pointers; /result/text reads recorded text, /result/structured_content reads structured output. format=json pages the selected value. Follow next_offset to retain complete evidence; it is not an omission. offset uses entries for outlines, characters for text. Images are listed in the outline.',
         {'material_id':{'type':'string'},'pointer':{'type':'string','default':''},**page,'format':{'type':'string','enum':['outline','json'],'default':'outline'}},['material_id']),
        ('read_review_image','Read actual pixels from an image ID listed by read_review_material. Missing images are reported; paths outside the bound evidence are not accepted.',
         {'image_id':{'type':'string'}},['image_id'])]
    @app.list_tools()
    async def list_tools():
        return [Tool(name=name,description=desc,inputSchema={'type':'object','properties':props,'required':required,'additionalProperties':False}) for name,desc,props,required in descriptions]
    @app.call_tool()
    async def call_tool(name,arguments):
        started=time.time();began=time.monotonic();entry={'tool':name,'arguments':arguments,'started_at':started}
        try:
            if deadline is not None and started>=deadline:raise ValueError('review_budget_exhausted')
            if name=='read_review_image':
                info,data=materials.image(**arguments)
                if deadline is not None:info['review_remaining_seconds']=max(0,deadline-time.time())
                entry['result']=info
                return CallToolResult(content=[TextContent(type='text',text=json.dumps(info,ensure_ascii=False)),
                    ImageContent(type='image',data=base64.b64encode(data).decode(),mimeType=info['source'].get('mime_type') or 'image/png')])
            if name=='list_review_materials':result=materials.list(**arguments)
            elif name=='read_review_material':result=materials.read(**arguments)
            else:raise ValueError('unknown_review_tool')
            if deadline is not None:result['review_remaining_seconds']=max(0,deadline-time.time())
            entry['result']=result
            return CallToolResult(content=[TextContent(type='text',text=json.dumps(result,ensure_ascii=False))],structuredContent=result)
        except Exception as exc:
            entry['error']=str(exc)
            return CallToolResult(isError=True,content=[TextContent(type='text',text=str(exc))])
        finally:
            entry.update(elapsed_seconds=time.monotonic()-began,finished_at=time.time())
            # One immutable file per disclosure also remains usable across MCP restarts.
            log=materials.root/'access';log.mkdir(exist_ok=True)
            with (log/(uuid.uuid4().hex+'.json')).open('x',encoding='utf-8') as f:
                json.dump(entry,f,ensure_ascii=False,indent=2)
    async with stdio_server() as (read,write):
        await app.run(read,write,app.create_initialization_options())


if __name__=='__main__':asyncio.run(main(sys.argv[1],float(sys.argv[2]) if len(sys.argv)>2 else None))
