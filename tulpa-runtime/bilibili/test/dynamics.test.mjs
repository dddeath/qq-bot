import test from 'node:test';
import assert from 'node:assert/strict';
process.env.BILIBILI_SESSDATA='fixture-session';
process.env.BILIBILI_BILI_JCT='fixture-csrf';
process.env.BILIBILI_DEDEUSERID='42';
process.env.BILIBILI_RATE_LIMIT_MS='1';
const {handleToolCall}=await import('@xzxzzx/bilibili-mcp/dist/server/tool-handlers.js');
const {createAdapter}=await import('../adapter.mjs');
const row={id_str:'1258968303773155350',type:'DYNAMIC_TYPE_DRAW',modules:{module_author:{mid:161775300,pub_ts:'1791964800'},module_dynamic:{desc:null,major:{type:'MAJOR_TYPE_DRAW',draw:{items:[{src:'http://i0.hdslb.com/bfs/new_dyn/b7b83e07eaeb6b78d8abf86705784ca8161775300.jpg',width:'1000',height:'9653'}]}}}}};
async function read(items){
 const previous=globalThis.fetch;
 globalThis.fetch=async input=>{
  const path=new URL(input).pathname;
  assert.ok(['/x/web-interface/nav','/x/polymer/web-dynamic/v1/feed/space'].includes(path));
  return new Response(JSON.stringify({code:0,data:path.endsWith('/nav')?{isLogin:true}:{has_more:false,items}}),{headers:{'content-type':'application/json'}});
 };
 try{return await createAdapter(handleToolCall).call('get_bilibili_creator_content',{mid:161775300,section:'dynamics'});}finally{globalThis.fetch=previous;}
}
test('dynamic tool preserves real numeric-string publication time',async()=>{
 const result=await read([row]);
 assert.equal(result.status,'ok');assert.equal(result.data.dynamics.length,1);
 assert.equal(result.data.dynamics[0].published_at,'2026-10-14T08:00:00.000Z');
});
test('dynamic tool preserves official image URLs and numeric-string dimensions',async()=>{
 const result=await read([row]);const image=result.data.dynamics[0].images[0];
 assert.ok(image);assert.equal(image.url,'https://i0.hdslb.com/bfs/new_dyn/b7b83e07eaeb6b78d8abf86705784ca8161775300.jpg');
 assert.equal(image.width,1000);assert.equal(image.height,9653);
});
test('all skipped dynamics is an explicit error while a genuinely empty feed succeeds',async()=>{
 const bad=structuredClone(row);bad.modules.module_author.pub_ts='invalid';
 const rejected=await read([bad]);assert.equal(rejected.status,'error');assert.equal(rejected.error.code,'DYNAMIC_PARSE_EMPTY');
 assert.equal(rejected.data.skipped_count,1);
 const empty=await read([]);assert.equal(empty.status,'ok');assert.deepEqual(empty.data.dynamics,[]);
});
test('numeric timestamps remain valid and non-Bilibili images stay excluded',async()=>{
 const copy=structuredClone(row);copy.modules.module_author.pub_ts=1791964800;
 copy.modules.module_dynamic.major.draw.items.push({src:'http://example.com/image.jpg',width:'100',height:'100'});
 const result=await read([copy]);assert.equal(result.status,'ok');
 assert.equal(result.data.dynamics[0].images.length,1);
 assert.equal(result.data.dynamics[0].published_at,'2026-10-14T08:00:00.000Z');
});
