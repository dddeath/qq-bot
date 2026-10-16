import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,readFile,readdir} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {createVideoSource} from '../source.mjs';
const api=async p=>p.includes('view')?{pages:[{page:1,cid:81}]}:{dash:{video:[{id:32,codecid:7,bandwidth:300,baseUrl:'https://primary.bilivideo.com/video?secret=hidden',backupUrl:['https://backup.bilivideo.com/video?secret=hidden']}]}};
function brokenResponse(){let n=0;return new Response(new ReadableStream({pull(c){if(n++===0)c.enqueue(new Uint8Array([1,2,3]));else return new Promise(resolve=>setTimeout(()=>{c.error(new TypeError('terminated secret url',{cause:{code:'UND_ERR_SOCKET'}}));resolve();},15));}}),{headers:{'content-length':'10'}});}
test('interrupted video stream falls back to backup and records sanitized failure and successful bytes',async()=>{
 const root=await mkdtemp(join(tmpdir(),'video-recovery-'));const records=[],hosts=[];
 const prepare=createVideoSource({root,api,primaryRetryDelaysMs:[],record:r=>records.push(r),fetchMedia:async u=>{hosts.push(u.hostname);return hosts.length===1?brokenResponse():new Response('complete-video');}});
 const file=await prepare('BV15euuzWEcC');
 assert.equal(await readFile(file,'utf8'),'complete-video');
 assert.deepEqual(hosts,['primary.bilivideo.com','backup.bilivideo.com']);
 const attempts=records.at(-1).attempts;
 assert.equal(attempts[0].cause_code,'UND_ERR_SOCKET');assert.equal(attempts[0].stage,'download');
 assert.equal(attempts[0].expected_bytes,10);assert.equal(attempts[0].bytes,3);
 assert.equal(attempts[1].status,'DONE');assert.equal(records.at(-1).bytes,14);
 assert.ok(!JSON.stringify(records).includes('secret'));assert.ok(!(await readdir(root)).some(n=>n.endsWith('.part')));
});
import {createVideoAdapter} from '../adapter.mjs';
test('a later explicit tool request recovers after exhausted download failure instead of permanent failure caching',async()=>{
 let n=0;const adapter=createVideoAdapter(async()=>({content:[{type:'text',text:'DONE'}]}),()=>{},async()=>{if(n++===0)throw new TypeError('terminated');return '/cache/video.mp4';});
 assert.equal((await adapter.call('watch_video',{video:'BV15euuzWEcC'})).isError,true);
 const next=await adapter.call('watch_video',{video:'BV15euuzWEcC'});
 assert.ok(!next.isError);assert.equal(n,2);
});
test('failed acquisition is bounded and a later request can recover without a poisoned source cache',async()=>{
 const root=await mkdtemp(join(tmpdir(),'video-bounded-'));let calls=0,healthy=false;const records=[];
 const prepare=createVideoSource({root,api,primaryRetryDelaysMs:[],maxAttempts:2,record:r=>records.push(r),fetchMedia:async()=>{calls++;return healthy?new Response('ok'):brokenResponse();}});
 await assert.rejects(prepare('BV15euuzWEcC'),TypeError);assert.equal(calls,2);assert.deepEqual(await readdir(root),[]);
 healthy=true;const [a,b]=await Promise.all([prepare('BV15euuzWEcC'),prepare('BV15euuzWEcC')]);assert.equal(a,b);assert.equal(calls,3);assert.equal(await readFile(a,'utf8'),'ok');
 assert.equal(records[0].attempts.length,2);assert.ok(records[0].download_ms>0);
});
test('size violation is not retried and unsafe backup hosts are rejected before fetching',async()=>{
 for(const unsafe of [false,true]){
  const root=await mkdtemp(join(tmpdir(),'video-policy-'));let calls=0;
  const customized=async p=>{const v=await api(p);if(unsafe && v.dash)v.dash.video[0].backupUrl=['https://example.com/not-media'];return v;};
  const prepare=createVideoSource({root,api:customized,primaryRetryDelaysMs:[],maxBytes:unsafe?20:4,fetchMedia:async()=>{calls++;return unsafe?brokenResponse():new Response('12345');}});
  await assert.rejects(prepare('BV15euuzWEcC'),unsafe?/UNEXPECTED_MEDIA_HOST/:/VIDEO_SIZE_LIMIT/);assert.equal(calls,1);assert.deepEqual(await readdir(root),[]);
 }
});
test('download deadline aborts a stalled body, limits attempts, and removes its partial file',async()=>{
 const root=await mkdtemp(join(tmpdir(),'video-deadline-'));let calls=0;const records=[];
 const prepare=createVideoSource({root,api,primaryRetryDelaysMs:[],totalTimeoutMs:40,attemptTimeoutMs:100,maxAttempts:3,record:r=>records.push(r),fetchMedia:async()=>{calls++;return new Response(new ReadableStream({start(c){c.enqueue(new Uint8Array([1]));}}));}});
 // Keep the event loop alive: AbortSignal.timeout itself is unref'ed by Node.
 const keep=setInterval(()=>{},100);
 try{await assert.rejects(prepare('BV15euuzWEcC'));}finally{clearInterval(keep);}
 assert.ok(calls<=2);assert.ok(records[0].elapsed_ms<1000);assert.deepEqual(await readdir(root),[]);
});
test('interrupted stream resumes confirmed byte range on backup instead of losing downloaded bytes',async()=>{
 const root=await mkdtemp(join(tmpdir(),'video-resume-'));const records=[],requests=[];
 const prepare=createVideoSource({root,api,primaryRetryDelaysMs:[],record:r=>records.push(r),fetchMedia:async(u,o)=>{requests.push(o.headers.Range??null);return requests.length===1?brokenResponse():new Response('4567890',{status:206,headers:{'content-range':'bytes 3-9/10','content-length':'7'}});}});
 const file=await prepare('BV15euuzWEcC');assert.deepEqual([...await readFile(file)],[1,2,3,52,53,54,55,56,57,48]);
 assert.deepEqual(requests,[null,'bytes=3-']);assert.equal(records.at(-1).bytes,10);assert.equal(records.at(-1).attempts[1].resumed_from,3);
});
test('wrong resumed range never publishes a corrupted video or retries validation errors',async()=>{
 for(const header of ['bytes 2-9/10','bytes 3-9/11','invalid']){
  const root=await mkdtemp(join(tmpdir(),'video-range-'));let calls=0;
  const prepare=createVideoSource({root,api,primaryRetryDelaysMs:[],fetchMedia:async()=>++calls===1?brokenResponse():new Response('4567890',{status:206,headers:{'content-range':header,'content-length':'7'}})});
  await assert.rejects(prepare('BV15euuzWEcC'),/INVALID_MEDIA_RANGE/);assert.equal(calls,2);assert.deepEqual(await readdir(root),[]);
 }
});
