import test from 'node:test';
import assert from 'node:assert/strict';
import {createVideoAdapter} from '../adapter.mjs';

test('video preparation does not request frame extraction or ASR', async()=>{
  const requests=[];
  const adapter=createVideoAdapter(async(name,args)=>{
    requests.push({name,args});
    return {content:[{type:'text',text:requests.length===1?'RUNNING: extracting':'DONE: frames ready'}]};
  });
  const first=await adapter.call('watch_video',{video:'https://www.bilibili.com/video/BV1KXYc6aEFR/'});
  const second=await adapter.call('watch_video',{video:'https://www.bilibili.com/video/BV1KXYc6aEFR/',mode:'full',refresh:true});
  assert.match(first.content[0].text,/RUNNING/);
  assert.match(second.content[0].text,/DONE/);
  assert.ok(requests.every(x=>x.args.mode===undefined && x.args.refresh===undefined));
});

test('a prepared Bilibili file is shared by submission, polling and image reads',async()=>{
  const seen=[];let prepared=0;
  const adapter=createVideoAdapter(async(name,args)=>{seen.push(args.video);return {content:[{type:'text',text:'DONE'}]};},()=>{},async()=>{prepared++;return '/cache/BV1KXYc6aEFR-p1.mp4';});
  for(const name of ['watch_video','watch_video','get_frame_at']) await adapter.call(name,{video:'BV1KXYc6aEFR'});
  assert.equal(prepared,1);
  assert.deepEqual(seen,Array(3).fill('/cache/BV1KXYc6aEFR-p1.mp4'));
});

test('frame images and timestamps survive forwarding with correlated timing records',async()=>{
  const records=[];
  const image={type:'image',mimeType:'image/jpeg',data:'/9j/2Q=='};
  const adapter=createVideoAdapter(async(name)=>({content:name==='watch_video'?[{type:'text',text:'DONE: frames ready'}]:[{type:'text',text:'keyframe #1 · 00:05'},image]}),r=>records.push(r));
  await adapter.call('watch_video',{video:'fixture.mp4'});
  const result=await adapter.call('get_frames',{video:'fixture.mp4',count:1});
  assert.deepEqual(result.content,[{type:'text',text:'keyframe #1 · 00:05'},image]);
  assert.equal(records.length,2);
  assert.equal(records[0].video_id,records[1].video_id);
  assert.equal(records[0].status,'DONE');
  assert.equal(records[1].image_count,1);
  assert.ok(records.every(r=>r.elapsed_ms>=0 && r.started_at && r.finished_at && r.call_id));
  assert.equal(records[1].content,undefined);
});

test('upstream extraction failure remains a tool error and is recorded',async()=>{
 const records=[];
 const adapter=createVideoAdapter(async()=>({content:[{type:'text',text:'ERROR: unavailable video'}]}),r=>records.push(r));
 const result=await adapter.call('watch_video',{video:'missing.mp4'});
 assert.equal(result.isError,true);assert.equal(records[0].status,'ERROR');
 await assert.rejects(()=>adapter.call('get_transcript',{video:'missing.mp4'}),/TOOL_NOT_ALLOWED/);
});
