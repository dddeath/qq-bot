import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,readFile,readdir} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {createVideoSource} from '../source.mjs';
const api=async p=>p.includes('view')?{pages:[{page:1,cid:81}]}:{dash:{video:[{id:32,codecid:7,bandwidth:300,baseUrl:'https://primary.bilivideo.com/video',backupUrl:['https://backup.bilivideo.com/video']}]}};
test('primary gets initial attempt then retries after 2, 4, 8 seconds before backup',async()=>{
 const root=await mkdtemp(join(tmpdir(),'video-backoff-'));const hosts=[],delays=[],records=[];
 const prepare=createVideoSource({root,api,sleep:async ms=>{delays.push(ms);},record:r=>records.push(r),fetchMedia:async u=>{hosts.push(u.hostname);if(u.hostname.startsWith('primary'))throw new TypeError('fetch failed');return new Response('complete');}});
 const file=await prepare('BV15euuzWEcC');assert.equal(await readFile(file,'utf8'),'complete');
 assert.deepEqual(hosts,['primary.bilivideo.com','primary.bilivideo.com','primary.bilivideo.com','primary.bilivideo.com','backup.bilivideo.com']);
 assert.deepEqual(delays,[2000,4000,8000]);assert.deepEqual(records[0].attempts.map(a=>a.backoff_ms),[0,2000,4000,8000,0]);
 assert.equal(records[0].attempts.at(-1).timeout_ms,15000);
});
test('successful primary retry keeps downloaded bytes and never contacts backup',async()=>{
 const root=await mkdtemp(join(tmpdir(),'video-primary-resume-'));const hosts=[],ranges=[],delays=[];let n=0;
 const prepare=createVideoSource({root,api,sleep:async ms=>delays.push(ms),fetchMedia:async(u,o)=>{
  hosts.push(u.hostname);ranges.push(o.headers.Range??null);
  if(n++===0)return new Response(new ReadableStream({start(c){c.enqueue(new Uint8Array([1,2,3]));setTimeout(()=>c.error(new TypeError('terminated',{cause:{code:'UND_ERR_SOCKET'}})),20);}}),{headers:{'content-length':'5'}});
  return new Response(new Uint8Array([4,5]),{status:206,headers:{'content-range':'bytes 3-4/5','content-length':'2'}});
 }});
 assert.deepEqual([...await readFile(await prepare('BV15euuzWEcC'))],[1,2,3,4,5]);assert.deepEqual(hosts,['primary.bilivideo.com','primary.bilivideo.com']);assert.deepEqual(delays,[2000]);assert.deepEqual(ranges,[null,'bytes=3-']);
});
test('backoff stays inside total budget and maxAttempts limits requests',async()=>{
 for(const limit of ['budget','attempts']){
  const root=await mkdtemp(join(tmpdir(),'video-budget-'));let calls=0;const waits=[];
  const prepare=createVideoSource({root,api,totalTimeoutMs:limit==='budget'?100:180000,maxAttempts:limit==='attempts'?2:6,sleep:async ms=>waits.push(ms),fetchMedia:async()=>{calls++;throw new TypeError('network');}});
  await assert.rejects(prepare('BV15euuzWEcC'),limit==='budget'?/VIDEO_DOWNLOAD_DEADLINE/:/network/);
  assert.equal(calls,limit==='budget'?1:2);assert.deepEqual(waits,limit==='budget'?[]:[2000]);assert.deepEqual(await readdir(root),[]);
 }
});
test('backup timeout is independently bounded and aborts a slow body without publishing partial cache',async()=>{
 const root=await mkdtemp(join(tmpdir(),'video-backup-timeout-'));const records=[];let calls=0;
 const prepare=createVideoSource({root,api,primaryRetryDelaysMs:[],backupAttemptTimeoutMs:30,attemptTimeoutMs:1000,record:r=>records.push(r),fetchMedia:async()=>{if(++calls===1)throw new TypeError('primary failed');return new Response(new ReadableStream({start(c){c.enqueue(new Uint8Array([1]));}}));}});
 const keep=setInterval(()=>{},100);try{await assert.rejects(prepare('BV15euuzWEcC'));}finally{clearInterval(keep);}
 assert.equal(calls,2);assert.equal(records[0].attempts[1].timeout_ms,30);assert.equal(records[0].attempts[1].error_name,'AbortError');assert.ok(records[0].attempts[1].elapsed_ms<700);assert.deepEqual(await readdir(root),[]);
});
