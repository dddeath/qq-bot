import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,readFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {readLearningFrames} from '../learning-frames.mjs';
import {createVideoAdapter} from '../adapter.mjs';
const png='iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j5ioAAAAASUVORK5CYII=';
test('exploration retrieves an original timestamp frame rather than enlarging a grid',async()=>{
 const root=await mkdtemp(join(tmpdir(),'explore-frame-'));
 try{
  const r=await readLearningFrames({video:'v',output:join(root,'run'),kind:'frame',at_seconds:65,count:1},async(name,args)=>{
   if(name==='watch_video')return {content:[{type:'text',text:'DONE'}]};
   assert.equal(name,'get_frame_at');assert.equal(args.time,'00:01:05.000');
   return {content:[{type:'image',mimeType:'image/png',data:png},{type:'text',text:'01:05'}]};
  });
  assert.equal(r.status,'ok');assert.equal(r.images.length,1);assert.deepEqual(r.timeline,['01:05']);
 }finally{await rm(root,{recursive:true,force:true});}
});

test('daily video boundary polls frames-only and saves two timestamped image attachments',async()=>{
 const root=await mkdtemp(join(tmpdir(),'daily-frames-'));let polls=0;
 try{
  const adapter=createVideoAdapter(async(name,args)=>{
   if(name==='watch_video'){
    assert.equal(args.mode,undefined);
    return {content:[{type:'text',text:++polls===1?'RUNNING':'DONE'}]};
   }
   if(name==='sample_video_frames'){assert.equal(args.frame_count,18);return {content:[{type:'text',text:JSON.stringify({sample_id:'fixture-sample'})}]};}
   assert.equal(name,'get_frames');assert.equal(args.sample_id,'fixture-sample');assert.equal(args.kind,'grids');assert.equal(args.count,2);assert.equal(args.overview,undefined);
   return {content:[{type:'text',text:'Grid 1: 00:05, 00:10'},...Array.from({length:3},()=>({type:'image',mimeType:'image/png',data:png}))]};
  });
  const result=await readLearningFrames({video:'https://example.com/v',output:join(root,'run'),count:2},(n,a)=>adapter.call(n,a),{sleep:async()=>{}});
  assert.equal(result.status,'ok');assert.equal(polls,2);assert.equal(result.images.length,2);
  assert.equal(result.truncated,true);assert.deepEqual(result.timeline,['Grid 1: 00:05, 00:10']);
  assert.equal((await readFile(result.images[0].path)).subarray(0,8).toString('hex'),'89504e470d0a1a0a');
  const calls=JSON.parse(await readFile(join(root,'run/calls.json')));
  assert.equal(calls.length,4);assert.ok(calls.every(c=>c.elapsed_ms>=0));
  await assert.rejects(()=>readLearningFrames({video:'v',output:join(root,'run'),count:2},()=>assert.fail()),/EEXIST/);
 }finally{await rm(root,{recursive:true,force:true});}
});

test('daily frame failure and deadline return missing images without an unbounded poll',async()=>{
 const root=await mkdtemp(join(tmpdir(),'daily-frames-'));
 try{
  let clock=0,calls=0;
  const result=await readLearningFrames({video:'v',output:join(root,'timeout'),timeout_ms:20},async()=>{
   calls++;clock+=30;return {content:[{type:'text',text:'RUNNING'}]};
  },{now:()=>clock,sleep:async()=>{}});
  assert.equal(result.status,'error');assert.equal(result.error,'video_readiness_timeout');assert.equal(calls,1);
  const failed=await readLearningFrames({video:'v',output:join(root,'error')},async()=>({isError:true,content:[{type:'text',text:'ERROR: download failed'}]}));
  assert.equal(failed.status,'error');assert.deepEqual(failed.images,[]);
 }finally{await rm(root,{recursive:true,force:true});}
});
test('segment samples original frames in timestamp order preserving selected part',async()=>{
 const root=await mkdtemp(join(tmpdir(),'segment-'));
 try{
  const times=[];
  const r=await readLearningFrames({video:'https://www.bilibili.com/video/BV1KXYc6aEFR/?p=4',output:join(root,'run'),kind:'frames',start_seconds:40,end_seconds:42,interval_seconds:1},async(name,args)=>{
   assert.ok(args.video.endsWith('?p=4'));
   if(name==='watch_video')return {content:[{type:'text',text:'DONE'}]};
   times.push(args.time);return {content:[{type:'image',mimeType:'image/png',data:png}]};
  });
  assert.equal(r.status,'ok');assert.deepEqual(times,['00:00:40.000','00:00:41.000','00:00:42.000']);
  assert.deepEqual(r.images.map(x=>x.requested_at_seconds),[40,41,42]);
 }finally{await rm(root,{recursive:true,force:true});}
});
test('segment budget rejects excessive span density and invalid interval before download',async()=>{
 const root=await mkdtemp(join(tmpdir(),'segment-limits-'));
 try{
  let i=0;
  for(const range of [{start_seconds:0,end_seconds:13,interval_seconds:2},{start_seconds:0,end_seconds:8,interval_seconds:1},{start_seconds:0,end_seconds:1,interval_seconds:0},{start_seconds:4,end_seconds:2,interval_seconds:1}]){
   const r=await readLearningFrames({video:'v',output:join(root,String(i++)),kind:'frames',...range},async()=>assert.fail('must reject before network'));
   assert.equal(r.status,'error');assert.equal(r.error,'segment_budget_exceeded');
  }
 }finally{await rm(root,{recursive:true,force:true});}
});
