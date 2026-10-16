import test from 'node:test';
import assert from 'node:assert/strict';
import {createAdapter} from '../adapter.mjs';
import {collectVideoContext} from '../video-context.mjs';
process.env.BILIBILI_RATE_LIMIT_MS='1';
test('exploration context supplies navigable comment roots with a bounded page',async()=>{
 const r=await collectVideoContext({bvid_or_url:'BV1KXYc6aEFR',structured_comments:true,comment_limit:10},async(name,args)=>{
  if(name==='get_video_comment_threads')return {status:'ok',data:{items:[{id:'123',root_id:'123',text:'反话[doge]'}],next_page:2}};
  return {status:'ok',data:{}};
 });
 assert.equal(r.materials.comments.data.items[0].root_id,'123');
 assert.equal(r.materials.comments.data.next_page,2);
 assert.equal(r.reading_policy.exploration_budget_ratio,0.2);
 assert.equal(r.reading_policy.max_read_units,10);
});
test('background video material combines description, comments and timestamped danmaku while identifying absent subtitles',async()=>{
 const old=globalThis.fetch;
 const bvid='BV1KXYc6aEFR';
 globalThis.fetch=async input=>new URL(input).pathname.includes('/view')?Response.json({code:0,data:{bvid,pages:[{page:2,cid:82}]}}):new Response('<i><chatid>82</chatid><d p="12,1,25,1,1,0,hash,10">反转了</d></i>');
 const dispatch=async(name,args)=>{
  if(name==='get_video_metadata')return {structuredContent:{bvid,title:'短剧',description:'作者说明',pages:[{page:2,cid:82}]}};
  if(name==='get_video_transcript'){
   assert.equal(args.page,2);assert.equal(args.fallback_to_asr,false);
   return {isError:true,structuredContent:{error:{code:'SUBTITLE_UNAVAILABLE',message:'No subtitles'}}};
  }
  if(name==='get_video_chapters')return {structuredContent:{chapters:[]}};
  if(name==='get_video_comments')return {structuredContent:{bvid,comments:[{content:'这里的笑点是反差'}]}};
  throw Error(name);
 };
 try{
  const r=await createAdapter(dispatch).call('get_video_context',{bvid_or_url:`https://www.bilibili.com/video/${bvid}/?p=2`});
  assert.equal(r.status,'ok');assert.equal(r.source.page,2);
  assert.equal(r.data.materials.description.data.description,'作者说明');
  assert.equal(r.data.materials.comments.scope,'whole_video_comment_sample');
  assert.deepEqual(r.data.missing,['subtitles']);
  assert.equal(r.data.materials.danmaku.data.items[0].at_seconds,12);
  assert.equal(r.data.frames.status,'not_requested');
  assert.equal(r.data.frames.video,`https://www.bilibili.com/video/${bvid}/?p=2`);
  assert.equal(r.data.complete,false);
  for(const m of Object.values(r.data.materials))assert.ok(m.elapsed_ms>=0);
 }finally{globalThis.fetch=old;}
});

test('background materials preserve failed audience sources without discarding author text',async()=>{
 const old=globalThis.fetch,bvid='BV1KXYc6aEFR';
 globalThis.fetch=async input=>new URL(input).pathname.includes('/view')?Response.json({code:0,data:{bvid,pages:[{page:1,cid:82}]}}):new Response('',{status:412});
 const dispatch=async name=>name==='get_video_comments'?{isError:true,structuredContent:{error:{code:'COMMENTS_DISABLED'}}}:{structuredContent:{bvid,description:name==='get_video_metadata'?'作者简介':undefined,segments:name==='get_video_transcript'?[{from:0,to:2,content:'对白'}]:undefined}};
 try{
  const r=await createAdapter(dispatch).call('get_video_context',{bvid_or_url:bvid});
  assert.deepEqual(r.data.missing,['comments','danmaku']);
  assert.equal(r.data.materials.description.data.description,'作者简介');
  assert.equal(r.data.materials.subtitles.data.segments[0].content,'对白');
  assert.equal(r.data.materials.danmaku.error.code,'RISK_CONTROL');
  assert.equal(r.data.text_materials_complete,false);
 }finally{globalThis.fetch=old;}
});
test('mandatory overview includes selected-part chapters before decisions',async()=>{
 const calls=[];
 const r=await collectVideoContext({bvid_or_url:'https://www.bilibili.com/video/BV1KXYc6aEFR/?p=4'},async(name,args)=>{
  calls.push([name,args]);return {status:'ok',data:name==='get_video_chapters'?{chapters:[{title:'机制',start:20,end:40}]}:{}};
 });
 assert.equal(r.materials.chapters.data.chapters[0].title,'机制');
 assert.equal(calls.find(x=>x[0]==='get_video_chapters')[1].page,4);
});
