import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,readFile,readdir} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {createVideoSource} from '../source.mjs';

test('Bilibili API video track is cached by BV and part, without page scraping or audio',async()=>{
 const root=await mkdtemp(join(tmpdir(),'qq-video-test-'));const calls=[];
 const api=async(path,args)=>{calls.push({path,args});return path.includes('view')?{pages:[{page:1,cid:81}]}:{dash:{video:[{id:32,codecid:7,bandwidth:300,baseUrl:'https://upos-hz-mirrorakam.akamaized.net/track.m4s'}]}};};
 let downloads=0;
 const prepare=createVideoSource({root,api,fetchMedia:async()=>{downloads++;return new Response(Buffer.from('fixture video bytes'));}});
 const a=await prepare('BV1KXYc6aEFR');const b=await prepare('https://www.bilibili.com/video/BV1KXYc6aEFR/?p=1');
 assert.equal(a,b);assert.equal(downloads,1);
 assert.equal(await readFile(a,'utf8'),'fixture video bytes');
 assert.equal(calls[1].path,'/x/player/playurl');assert.equal(calls[1].args.cid,81);
});

test('download size limit leaves no completed or partial video and records failure',async()=>{
 const root=await mkdtemp(join(tmpdir(),'qq-video-limit-'));const records=[];
 const api=async path=>path.includes('view')?{pages:[{page:1,cid:81}]}:{dash:{video:[{id:32,codecid:7,bandwidth:300,baseUrl:'https://test.bilivideo.com/track.m4s'}]}};
 const prepare=createVideoSource({root,api,maxBytes:4,record:r=>records.push(r),fetchMedia:async()=>new Response(Buffer.from('12345'))});
 await assert.rejects(()=>prepare('BV1KXYc6aEFR'),/VIDEO_SIZE_LIMIT/);
 assert.deepEqual(await readdir(root),[]);
 assert.equal(records[0].status,'ERROR');assert.equal(records[0].error_code,'VIDEO_SIZE_LIMIT');
});
