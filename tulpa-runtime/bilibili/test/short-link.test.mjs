import test from 'node:test';
import assert from 'node:assert/strict';
import {createAdapter} from '../adapter.mjs';
process.env.BILIBILI_RATE_LIMIT_MS='1';

test('short link target P2 reaches aggregate subtitles, danmaku and frame request',async()=>{
 const old=globalThis.fetch,bvid='BV1KXYc6aEFR';
 globalThis.fetch=async input=>{
  const u=new URL(input);
  if(u.hostname==='b23.tv')return new Response(null,{status:302,headers:{location:`https://www.bilibili.com/video/${bvid}/?p=2&share_source=qq`}});
  if(u.pathname.includes('/view'))return Response.json({code:0,data:{bvid,pages:[{page:1,cid:81},{page:2,cid:82}]}});
  assert.equal(u.searchParams.get('oid'),'82');
  return new Response('<i><chatid>82</chatid><d p="12,1,25,1,1,0,hash,10">第二集</d></i>');
 };
 try{
  let page;
  const r=await createAdapter(async(name,args)=>{
   if(name==='get_video_transcript'){
    page=args.page;assert.equal(args.fallback_to_asr,false);
    return {structuredContent:{bvid,page:args.page,transcript:'[00:12] 第二集对白',data_source:'subtitle'}};
   }
   return {structuredContent:{bvid}};
  }).call('get_video_context',{bvid_or_url:'https://b23.tv/example'});
  assert.equal(page,2);assert.equal(r.data.page,2);
  assert.equal(r.data.materials.subtitles.data.transcript,'[00:12] 第二集对白');
  assert.equal(r.data.materials.danmaku.data.cid,82);
  assert.equal(r.data.frames.video,`https://www.bilibili.com/video/${bvid}/?p=2`);
 }finally{globalThis.fetch=old;}
});

test('video tool resolves a shared b23 link before requesting metadata',async()=>{
 const original=globalThis.fetch;
 globalThis.fetch=async(url,options)=>{
  assert.equal(String(url),'https://b23.tv/tNIQNOz');
  assert.equal(options.redirect,'manual');assert.equal(options.headers,undefined);
  return new Response(null,{status:302,headers:{location:'https://www.bilibili.com/video/BV1234567890/?share_source=qq'}});
 };
 try{
  let received;
  const result=await createAdapter(async(name,args)=>{received=args.bvid_or_url;return {structuredContent:{bvid:'BV1234567890',title:'原视频'}};}).call('get_video_metadata',{bvid_or_url:'https://b23.tv/tNIQNOz'});
  assert.equal(received,'BV1234567890');assert.equal(result.status,'ok');assert.equal(result.source.bvid,'BV1234567890');
 }finally{globalThis.fetch=original;}
});
test('short-link failure reports its own error and does not call metadata',async()=>{
 const original=globalThis.fetch;let calls=0;
 globalThis.fetch=async()=>{calls++;return new Response(null,{status:302,headers:{location:'http://127.0.0.1/private'}});};
 try{
  const result=await createAdapter(async()=>{assert.fail('metadata must not run');}).call('get_video_metadata',{bvid_or_url:'https://b23.tv/example'});
  assert.equal(result.error.code,'B23_RESOLUTION_FAILED');assert.equal(calls,1);
 }finally{globalThis.fetch=original;}
});
test('existing BV input does not request a short link',async()=>{
 const original=globalThis.fetch;globalThis.fetch=async()=>{assert.fail('unexpected short-link fetch');};
 try{
  const result=await createAdapter(async(name,args)=>({structuredContent:{bvid:args.bvid_or_url}})).call('get_video_metadata',{bvid_or_url:'BV1234567890'});
  assert.equal(result.status,'ok');
 }finally{globalThis.fetch=original;}
});
