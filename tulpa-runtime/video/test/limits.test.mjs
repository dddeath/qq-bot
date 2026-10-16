import test from 'node:test';
import assert from 'node:assert/strict';
import {frameToolSchemas} from '../tool-schemas.mjs';
test('discovery alone exposes configured sampling limits',()=>{
 const s=frameToolSchemas(12,45).find(t=>t.name==='sample_video_frames');
 assert.match(s.description,/1–12/);assert.match(s.description,/45000/);
});
import {createAdapter} from '../../bilibili/adapter.mjs';
import {videoContextSchema} from '../../bilibili/video-context.mjs';
test('context validation explains the rejected field through the public adapter',async()=>{
 assert.match(videoContextSchema.description,/1–50/);
 const r=await createAdapter(()=>{throw Error('unexpected network');}).call('get_video_context',{bvid_or_url:'BV13NJC6tEzs',comment_limit:0});
 assert.match(r.error.message,/comment_limit.*1.*50/);
});
import {createFrameDispatch} from '../frame-tools.mjs';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
test('invalid sampling exposes field and configured ceiling',async()=>{
 const d=createFrameDispatch({root:await mkdtemp(join(tmpdir(),'limits-')),run:async()=>({duration:120}),maxFrames:12,maxSeconds:45});
 await d('watch_video',{video:'v'});
 await assert.rejects(()=>d('sample_video_frames',{video:'v',frame_count:24}),/frame_count.*12/);
 await assert.rejects(()=>d('sample_video_frames',{video:'v',timeout_ms:46000}),/timeout_ms.*45000/);
});
