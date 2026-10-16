import test from 'node:test';
import assert from 'node:assert/strict';
import {Client} from '@modelcontextprotocol/sdk/client/index.js';
import {StdioClientTransport} from '@modelcontextprotocol/sdk/client/stdio.js';
import {fileURLToPath} from 'node:url';

test('MCP publishes only the read interface and returns structured failures with timing',async()=>{
  const c=new Client({name:'offline-contract-test',version:'1'});
  const t=new StdioClientTransport({command:process.execPath,args:[fileURLToPath(new URL('../server.mjs',import.meta.url))],stderr:'pipe'});
  try {
    await c.connect(t);
    const {tools}=await c.listTools();
    assert.equal(tools.length,11);
    assert.ok(tools.some(x=>x.name==='get_video_comment_threads'));
    const threads=await c.callTool({name:'get_video_comment_threads',arguments:{bvid_or_url:'invalid'}});
    assert.equal(threads.structuredContent.error.code,'INVALID_COMMENT_ARGUMENT');
    assert.ok(tools.some(x=>x.name==='get_video_context'));
    const dm=tools.find(x=>x.name==='get_video_danmaku');
    assert.equal(dm.annotations.readOnlyHint,true);
    assert.equal(dm.inputSchema.properties.limit.maximum,200);
    assert.ok(!tools.some(x=>x.name.includes('favorite')));
    const sub=tools.find(x=>x.name==='get_video_transcript');
    assert.equal(sub.inputSchema.properties.force_asr,undefined);
    const invalid=await c.callTool({name:'get_video_metadata',arguments:{bvid_or_url:'invalid'}});
    assert.equal(invalid.isError,true);
    assert.equal(invalid.structuredContent.status,'error');
    assert.ok(invalid.structuredContent.error.code);
    assert.ok(invalid.structuredContent.elapsed_ms>=0);
  } finally {await c.close();}
});
