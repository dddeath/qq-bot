import test from 'node:test';
import assert from 'node:assert/strict';
import {createVideoAdapter,allowedTools} from '../adapter.mjs';
test('preparation does not request extraction and four tools have separate names',async()=>{
 const calls=[];const a=createVideoAdapter(async(n,v)=>{calls.push([n,v]);return {content:[{type:'text',text:'DONE'}]};},()=>{},async()=>'/prepared.mp4');
 await a.call('watch_video',{video:'v'});
 assert.equal(calls[0][1].mode,undefined);
 assert.ok(allowedTools.includes('sample_video_frames'));
});

import {mkdtemp,readFile,writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {createFrameDispatch} from '../frame-tools.mjs';
test('prepare, sample, then read separate immutable samples without resampling on reads',async()=>{
 const root=await mkdtemp(join(tmpdir(),'four-tools-'));let probes=0,samples=0;
 const run=async req=>{
  if(req.operation==='prepare'){probes++;return {duration:120,source:req.video};}
  if(req.operation==='sample'){
   samples++;const file=join(root,`grid-${samples}.jpg`);await writeFile(file,'image'+samples);
   return {status:'ok',range:{start_seconds:req.start_seconds??0,end_seconds:req.end_seconds??120},selection:[{time:65,status:'ok',source_path:file}],images:[{path:file}]};
  }
  assert.equal(req.operation,'at');return {requested_seconds:req.time,actual_seconds:req.time,path:join(root,'grid-1.jpg')};
 };
 const dispatch=createFrameDispatch({root,run});
 const ready=await dispatch('watch_video',{video:'/v.mp4'});assert.equal(probes,1);assert.equal(samples,0);
 const full=JSON.parse((await dispatch('sample_video_frames',{video:'/v.mp4',frame_count:9})).content[0].text);
 const part=JSON.parse((await dispatch('sample_video_frames',{video:'/v.mp4',start_seconds:60,end_seconds:70,frame_count:9})).content[0].text);
 assert.notEqual(full.sample_id,part.sample_id);assert.deepEqual(part.range,{start_seconds:60,end_seconds:70});
 const r=await dispatch('get_frames',{sample_id:full.sample_id,kind:'grids',start:1,count:1});assert.equal(r.content.find(x=>x.type==='image').data,Buffer.from('image1').toString('base64'));assert.equal(samples,2);
 const restored=createFrameDispatch({root,run});assert.equal((await restored('get_frames',{sample_id:part.sample_id,kind:'frames',start:1,count:1})).content.find(x=>x.type==='image').data,Buffer.from('image2').toString('base64'));
 await assert.rejects(()=>dispatch('sample_video_frames',{video:'/v.mp4',frame_count:100}),/sample_budget/);
 await assert.rejects(()=>dispatch('get_frames',{sample_id:full.sample_id,start:86,count:1}),/image_index/);
 const at=await dispatch('get_frame_at',{video:'/v.mp4',time:'01:26'});assert.equal(JSON.parse(at.content[0].text).requested_seconds,86);
 assert.equal(samples,2);
});


import {frameToolSchemas} from '../tool-schemas.mjs';
test('tool descriptions expose separate preparation generation reading and timestamp contracts',()=>{
 const schemas=frameToolSchemas();assert.deepEqual(schemas.map(x=>x.name),['watch_video','sample_video_frames','get_frames','get_frame_at']);
 assert.equal(schemas[0].inputSchema.properties.frame_interval_seconds,undefined);
 assert.deepEqual(schemas[2].inputSchema.required,['sample_id']);assert.equal(schemas[2].inputSchema.properties.overview,undefined);
 assert.equal(schemas[1].inputSchema.properties.frame_count.maximum,18);
});
