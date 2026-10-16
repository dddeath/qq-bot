import test from 'node:test';
import assert from 'node:assert/strict';
import {deflateRawSync} from 'node:zlib';
import {createAdapter} from '../adapter.mjs';

process.env.BILIBILI_RATE_LIMIT_MS='1';
const bvid='BV1KXYc6aEFR';
const xml='<i><chatid>82</chatid><d p="12.5,1,25,16777215,1,0,privatehash,100">反转 &amp; 好笑</d><d p="2,1,25,1,1,0,privatehash,101">铺垫</d><d p="22,1,25,1,1,0,privatehash,102">结尾</d></i>';
test('read tool returns timestamped danmaku from the selected part, with a bounded sample',async()=>{
 const old=globalThis.fetch;
 globalThis.fetch=async input=>{
  const u=new URL(input);
  if(u.pathname==='/x/web-interface/view')return Response.json({code:0,data:{bvid,pages:[{page:1,cid:81},{page:2,cid:82}]}});
  assert.equal(u.searchParams.get('oid'),'82');
  return new Response(deflateRawSync(xml));
 };
 try{
  const r=await createAdapter(()=>{throw Error('unexpected upstream tool');}).call('get_video_danmaku',{bvid_or_url:`https://www.bilibili.com/video/${bvid}/?p=2`,limit:1,start_seconds:10});
  assert.equal(r.status,'ok');assert.equal(r.source.page,2);
  assert.equal(r.data.cid,82);
  assert.deepEqual(r.data.items,[{at_seconds:12.5,text:'反转 & 好笑'}]);
  assert.equal(r.data.truncated,true);assert.equal(r.data.available_in_window,2);
  assert.equal(r.completeness,'bounded_current_danmaku_pool');
  assert.ok(!JSON.stringify(r).includes('privatehash'));
 }finally{globalThis.fetch=old;}
});

test('invalid fields and part conflicts fail before network access',async()=>{
 const old=globalThis.fetch;let calls=0;
 globalThis.fetch=async()=>{calls++;throw Error('network should not run');};
 try{
  for(const args of [{bvid_or_url:bvid,limit:201},{bvid_or_url:bvid,start_seconds:8,end_seconds:2},{bvid_or_url:`https://www.bilibili.com/video/${bvid}/?p=2`,page:1}]){
   const r=await createAdapter(()=>{}).call('get_video_danmaku',args);
   assert.equal(r.status,'error');
  }
  assert.equal(calls,0);
 }finally{globalThis.fetch=old;}
});

test('empty pools, denied requests and invalid XML remain distinguishable',async()=>{
 const old=globalThis.fetch;
 try{
  for(const [response,code] of [[()=>new Response('<i><chatid>82</chatid></i>'),null],[()=>new Response('',{status:412}),'RISK_CONTROL'],[()=>Response.json({code:-403}),'ACCESS_DENIED'],[()=>new Response('<html>blocked</html>'),'DANMAKU_CID_MISMATCH'],[()=>new Response('<i><chatid>81</chatid></i>'),'DANMAKU_CID_MISMATCH']]){
   globalThis.fetch=async input=>new URL(input).pathname.includes('/view')?Response.json({code:0,data:{bvid,pages:[{page:2,cid:82}]}}):response();
   const r=await createAdapter(()=>{}).call('get_video_danmaku',{bvid_or_url:bvid,page:2});
   if(code){assert.equal(r.status,'error');assert.equal(r.error.code,code);assert.equal(r.data,null);}
   else{assert.equal(r.status,'ok');assert.deepEqual(r.data.items,[]);}
  }
 }finally{globalThis.fetch=old;}
});

test('sample spans the time window and an oversized pool is stopped',async()=>{
 const old=globalThis.fetch;
 try{
  let oversized=false;
  globalThis.fetch=async input=>new URL(input).pathname.includes('/view')?Response.json({code:0,data:{bvid,pages:[{page:1,cid:82}]}}):oversized?new Response('x'.repeat(2*1024*1024+1)):new Response(xml);
  const adapter=createAdapter(()=>{});
  const r=await adapter.call('get_video_danmaku',{bvid_or_url:bvid,limit:2});
  assert.deepEqual(r.data.items.map(x=>x.at_seconds),[2,22]);
  oversized=true;
  const denied=await adapter.call('get_video_danmaku',{bvid_or_url:bvid});
  assert.equal(denied.error.code,'DANMAKU_SIZE_LIMIT');assert.equal(denied.data,null);
 }finally{globalThis.fetch=old;}
});
