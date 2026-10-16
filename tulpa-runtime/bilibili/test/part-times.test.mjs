import test from 'node:test';
import assert from 'node:assert/strict';
process.env.BILIBILI_RATE_LIMIT_MS='1';
const {handleToolCall}=await import('@xzxzzx/bilibili-mcp/dist/server/tool-handlers.js');
test('metadata retains per-part ctime and leaves absent times unknown',async()=>{
 const old=globalThis.fetch;
 globalThis.fetch=async()=>Response.json({code:0,data:{bvid:'BV1234567890',aid:1,cid:2,title:'parts',duration:30,owner:{name:'UP'},stat:{},pages:[
  {cid:2,page:1,part:'old',duration:10,ctime:1700000000},
  {cid:3,page:2,part:'new',duration:10,ctime:1800000000},
  {cid:4,page:3,part:'unknown',duration:10}]}});
 try{
  const r=await handleToolCall('get_video_metadata',{bvid_or_url:'BV1234567890'});
  const d=r.structuredContent??JSON.parse(r.content[0].text);
  assert.equal(d.pages[0].ctime,1700000000);assert.equal(d.pages[1].ctime,1800000000);
  assert.equal(d.pages[2].ctime,undefined);
 }finally{globalThis.fetch=old;}
});
