import {mkdir,stat,rename,rm,writeFile} from 'node:fs/promises';
import {createWriteStream} from 'node:fs';
import {Readable,Transform} from 'node:stream';
import {pipeline} from 'node:stream/promises';
import {join} from 'node:path';
import {createHash,randomUUID} from 'node:crypto';

const safeCode=v=>typeof v==='string' && /^[A-Za-z0-9_]{1,80}$/.test(v)?v:null;
const errorCode=e=>safeCode(e.message)??safeCode(e.code)??safeCode(e.name)??'UNKNOWN';
function mediaURL(value){
 const url=new URL(value);
 if(url.protocol==='http:')url.protocol='https:';
 if(url.protocol!=='https:' || url.port || url.username || url.password || !(/(^|\.)bilivideo\.(com|cn)$/.test(url.hostname) || url.hostname==='upos-hz-mirrorakam.akamaized.net'))throw new Error('UNEXPECTED_MEDIA_HOST');
 return url;
}
function retryable(e){return ['TypeError','TimeoutError','AbortError'].includes(e.name) || /^(UND_ERR_|ECONN|ETIMEDOUT|EAI_AGAIN)/.test(e.cause?.code??e.code??'') || /^MEDIA_HTTP_(408|429|5\d\d)$/.test(e.message) || e.message==='INCOMPLETE_VIDEO';}

export function createVideoSource({root,api,fetchMedia=fetch,resolveShort=async v=>v,record=()=>{},maxBytes=512*1024*1024,maxAttempts=6,totalTimeoutMs=180000,attemptTimeoutMs=60000,backupAttemptTimeoutMs=15000,primaryRetryDelaysMs=[2000,4000,8000],sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms))}) {
 if(!Number.isInteger(maxAttempts)||maxAttempts<1||!Number.isInteger(totalTimeoutMs)||totalTimeoutMs<1||!Number.isInteger(attemptTimeoutMs)||attemptTimeoutMs<1)throw new Error('INVALID_DOWNLOAD_LIMITS');
 if(!Number.isInteger(backupAttemptTimeoutMs)||backupAttemptTimeoutMs<1||!Array.isArray(primaryRetryDelaysMs)||!primaryRetryDelaysMs.every(ms=>Number.isInteger(ms)&&ms>=0))throw new Error('INVALID_DOWNLOAD_LIMITS');
 const jobs=new Map();
 return async function prepare(original){
  let input=original;
  if(/^https?:\/\/b23\.tv\//.test(input))input=await resolveShort(input);
  let bvid,page=1;
  if(/^BV[\da-zA-Z]{10}$/.test(input))bvid=input;
  else if(/^https?:\/\//.test(input)){
   const u=new URL(input);
   if(['www.bilibili.com','bilibili.com','m.bilibili.com'].includes(u.hostname)){
    bvid=u.pathname.match(/^\/video\/(BV[\da-zA-Z]{10})\/?$/)?.[1];page=Number(u.searchParams.get('p')??1);
    if(!bvid || !Number.isInteger(page) || page<1)throw new Error('INVALID_BILIBILI_VIDEO');
   }
  }
  if(!bvid)return input;
  const key=`${bvid}-p${page}`;
  if(jobs.has(key))return jobs.get(key);
  const job=(async()=>{
   await mkdir(root,{recursive:true});const path=join(root,key+'.mp4');
   try{if((await stat(path)).size>0)return path;}catch{}
   const started_at=new Date().toISOString(),start=performance.now();
   let status='ERROR',error_code=null,bytes=0,metadata_ms=null,download_ms=null;
   let downloadStart=null;const attempts=[];const partial=path+'.'+randomUUID()+'.part';let expectedTotal=null;
   try{
    const view=await api('/x/web-interface/view',{bvid});const part=view.pages?.find(p=>p.page===page);
    if(!part?.cid)throw new Error('VIDEO_PART_NOT_FOUND');
    const play=await api('/x/player/playurl',{bvid,cid:part.cid,qn:32,fnval:16,fnver:0,fourk:0});
    const tracks=(play.dash?.video??[]).filter(v=>v.codecid===7 && v.id<=64).sort((a,b)=>a.bandwidth-b.bandwidth);
    const track=tracks.find(v=>v.id>=32)??tracks[0];if(!track)throw new Error('VIDEO_TRACK_UNAVAILABLE');
    const urls=[...new Set([track.baseUrl??track.base_url,...(track.backupUrl??track.backup_url??[])])];
    metadata_ms=performance.now()-start;downloadStart=performance.now();
    const schedule=[{url:urls[0],backoff:0,role:'primary'},...primaryRetryDelaysMs.map(backoff=>({url:urls[0],backoff,role:'primary'})),...urls.slice(1).map(url=>({url,backoff:0,role:'backup'}))].slice(0,maxAttempts);
    for(let i=0;i<schedule.length;i++){
     const step=schedule[i];let remaining=totalTimeoutMs-(performance.now()-downloadStart);
     if(remaining<=step.backoff)throw new Error('VIDEO_DOWNLOAD_DEADLINE');
     const waitStart=performance.now();
     if(step.backoff)await sleep(step.backoff);
     const backoffElapsed=performance.now()-waitStart;
     remaining=totalTimeoutMs-(performance.now()-downloadStart);
     if(remaining<=0)throw new Error('VIDEO_DOWNLOAD_DEADLINE');
     let offset=0;try{offset=(await stat(partial)).size;}catch{}
     const attempt={attempt:i+1,role:step.role,backoff_ms:step.backoff,backoff_elapsed_ms:backoffElapsed,host:null,stage:'validate_url',started_at:new Date().toISOString(),bytes:0,expected_bytes:null,resumed_from:offset,status:'ERROR'};
     const t=performance.now();attempts.push(attempt);
     try{
      const url=mediaURL(step.url);attempt.host=url.hostname;attempt.stage='request';
      attempt.timeout_ms=Math.max(1,Math.ceil(Math.min(step.role==='backup'?backupAttemptTimeoutMs:attemptTimeoutMs,remaining)));
      const signal=AbortSignal.timeout(attempt.timeout_ms);
      const headers={Referer:'https://www.bilibili.com/','User-Agent':'Mozilla/5.0','Accept-Encoding':'identity'};
      if(offset>0)headers.Range=`bytes=${offset}-`;
      const response=await fetchMedia(url,{headers,redirect:'error',signal});
      attempt.http_status=response.status;
      if(!response.ok || !response.body){await response.body?.cancel();throw new Error('MEDIA_HTTP_'+response.status);}
      const length=response.headers.get('content-length');attempt.expected_bytes=length!==null && /^\d+$/.test(length)?Number(length):null;
      if(response.status===206){
       const range=/^bytes (\d+)-(\d+)\/(\d+)$/.exec(response.headers.get('content-range')??'');
       if(!range || Number(range[1])!==offset || Number(range[2])<offset || Number(range[3])<=Number(range[2]) || (expectedTotal!==null && Number(range[3])!==expectedTotal) || (attempt.expected_bytes!==null && attempt.expected_bytes!==Number(range[2])-offset+1)){await response.body.cancel();throw new Error('INVALID_MEDIA_RANGE');}
       expectedTotal=Number(range[3]);
      }else{offset=0;attempt.resumed_from=0;expectedTotal=attempt.expected_bytes;}
      if((expectedTotal??0)>maxBytes || (attempt.expected_bytes!==null && offset+attempt.expected_bytes>maxBytes)){await response.body.cancel();throw new Error('VIDEO_SIZE_LIMIT');}
      attempt.stage='download';
      await pipeline(Readable.fromWeb(response.body),new Transform({transform(chunk,enc,done){attempt.bytes+=chunk.length;done(offset+attempt.bytes>maxBytes?new Error('VIDEO_SIZE_LIMIT'):null,chunk);}}),createWriteStream(partial,{flags:offset>0?'a':'w'}),{signal});
      if(!attempt.bytes)throw new Error('EMPTY_VIDEO');
      if((attempt.expected_bytes!==null && attempt.bytes!==attempt.expected_bytes) || (expectedTotal!==null && offset+attempt.bytes!==expectedTotal))throw new Error('INCOMPLETE_VIDEO');
      attempt.stage='publish';
      await rename(partial,path);bytes=offset+attempt.bytes;
      await writeFile(path+'.json',JSON.stringify({bvid,page,cid:part.cid,source_url:`https://www.bilibili.com/video/${bvid}/?p=${page}`,video_only:true,quality:track.id,bytes}));
      attempt.status='DONE';status='DONE';return path;
     }catch(e){attempt.error_name=safeCode(e.name);attempt.error_code=errorCode(e);attempt.cause_code=safeCode(e.cause?.code);bytes=offset+attempt.bytes;if(!retryable(e)||i===schedule.length-1)throw e;}
     finally{attempt.elapsed_ms=performance.now()-t;attempt.finished_at=new Date().toISOString();download_ms=performance.now()-downloadStart;}
    }
   }catch(e){error_code=errorCode(e);throw e;}finally{
    if(downloadStart!==null)download_ms=performance.now()-downloadStart;
    await rm(partial,{force:true});
    await record({operation:'acquire_video',video_id:createHash('sha256').update(original).digest('hex').slice(0,16),bvid,page,started_at,finished_at:new Date().toISOString(),elapsed_ms:performance.now()-start,metadata_ms,download_ms,status,error_code,bytes,attempts});
   }
  })();
  jobs.set(key,job);
  try{return await job;}catch(e){if(jobs.get(key)===job)jobs.delete(key);throw e;}
 };
}
