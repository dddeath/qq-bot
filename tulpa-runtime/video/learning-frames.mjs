import {mkdir,writeFile} from 'node:fs/promises';
import {join,resolve} from 'node:path';

// The daily reader consumes the existing frames-only MCP boundary.
export async function readLearningFrames({video,output,count=2,timeout_ms=180000,kind="grids",at_seconds,start_seconds,end_seconds,interval_seconds},call,{now=()=>performance.now(),sleep=ms=>new Promise(r=>setTimeout(r,ms))}={}) {
 const root=resolve(output);
 await mkdir(resolve(root,'..'),{recursive:true});
 await mkdir(root); // One run owns these files; never overwrite earlier evidence.
 const calls=[],start=now();
 const invoke=async(name,args)=>{
  const began=now(),at=new Date().toISOString();
  const remaining=timeout_ms-(began-start);
  if(remaining<=0)throw Error('video_readiness_timeout');
  const response=await call(name,args,remaining);
  const texts=(response.content??[]).filter(x=>x.type==='text').map(x=>x.text);
  calls.push({name,args,at,elapsed_ms:now()-began,isError:!!response.isError,texts,
   image_count:(response.content??[]).filter(x=>x.type==='image').length});
  await writeFile(join(root,'calls.json'),JSON.stringify(calls,null,2));
  if(response.isError||texts.some(t=>/^ERROR:/m.test(t)))throw Error(texts.join('\n')||'video_tool_failed');
  return response;
 };
 let result;
 try{
  if(!Number.isInteger(count)||count<1)throw Error('invalid_frame_count');
  if(kind==='frames'&&(![start_seconds,end_seconds,interval_seconds].every(Number.isFinite)||start_seconds<0||end_seconds>=86400||end_seconds<start_seconds||interval_seconds<0.25||end_seconds-start_seconds>12||Math.floor((end_seconds-start_seconds)/interval_seconds)+1>8))throw Error('segment_budget_exceeded');
  while(true){
   const r=await invoke('watch_video',{video});
   const text=(r.content??[]).filter(x=>x.type==='text').map(x=>x.text).join('\n');
   if(!/^RUNNING/m.test(text))break;
   if(now()-start>=timeout_ms)throw Error('video_readiness_timeout');
   await sleep(Math.min(1000,timeout_ms-(now()-start)));
  }
  if(!['grids','chapter_grid','frame','frames'].includes(kind))throw Error('invalid_frame_kind');
  const times=kind==='frames'?Array.from({length:Math.floor((end_seconds-start_seconds)/interval_seconds)+1},(_,i)=>start_seconds+i*interval_seconds):kind==='frame'?[at_seconds]:[];
  const responses=[];
  if(kind==='grids'||kind==='chapter_grid'){
   const grids=kind==='chapter_grid'?1:count;
   const sampled=await invoke('sample_video_frames',{video,frame_count:grids*9,...(kind==='chapter_grid'?{start_seconds,end_seconds}:{}),timeout_ms:Math.max(1,Math.min(90000,Math.floor(timeout_ms-(now()-start))))});
   const meta=JSON.parse(sampled.content.find(x=>x.type==='text').text);
   responses.push({response:await invoke('get_frames',{sample_id:meta.sample_id,kind:'grids',start:1,count:grids})});
  }
  else for(const time of times){
   if(!Number.isFinite(time)||time<0||time>=86400)throw Error('invalid_frame_time');
   responses.push({requested_at_seconds:time,response:await invoke('get_frame_at',{video,time:new Date(time*1000).toISOString().slice(11,23)})});
  }
  const images=[],timeline=[];let truncated=false;
  for(const {response,requested_at_seconds} of responses){
   const all=(response.content??[]).filter(x=>x.type==='image');
   if(!all.length)throw Error('no_frame_images');
   const texts=(response.content??[]).filter(x=>x.type==='text').map(x=>x.text);
   timeline.push(...texts);truncated ||= all.length>(kind==='grids'?count:1);
   for(const item of all.slice(0,kind==='grids'?count:1)){
    const ext={'image/png':'png','image/jpeg':'jpg','image/webp':'webp'}[item.mimeType];
    if(!ext)throw Error('unsupported_frame_image');
    const path=join(root,`grid-${images.length+1}.${ext}`),bytes=Buffer.from(item.data,'base64');
    if(!bytes.length)throw Error('empty_frame_image');
    await writeFile(path,bytes,{flag:'wx'});
    images.push({path,mimeType:item.mimeType,bytes:bytes.length,...(requested_at_seconds===undefined?{}:{requested_at_seconds,source_timeline:texts})});
   }
  }
  result={status:'ok',video,images,truncated,timeline};
 }catch(error){result={status:'error',video,error:String(error.message??error),images:[]};}
 result.elapsed_ms=now()-start;
 await writeFile(join(root,'result.json'),JSON.stringify(result,null,2),{flag:'wx'});
 return result;
}
