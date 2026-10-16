import {execFile} from 'node:child_process';
import {mkdir,readFile,writeFile} from 'node:fs/promises';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createHash,randomUUID} from 'node:crypto';
const text=value=>({type:'text',text:JSON.stringify(value)});
const image=async path=>({type:'image',mimeType:'image/jpeg',data:(await readFile(path)).toString('base64')});
export function runFrameProcess(request){
 return new Promise((resolve,reject)=>{
  const child=execFile(process.env.QQ_VIDEO_PYTHON,[fileURLToPath(new URL('./frame_service.py',import.meta.url))],{timeout:(request.timeout_seconds??90)*1000+2000,maxBuffer:2*1024*1024},(error,stdout)=>{
   if(error)return reject(error);try{resolve(JSON.parse(stdout));}catch(e){reject(e);}
  });
  child.stdin.on('error',()=>{});child.stdin.end(JSON.stringify(request));
 });
}
export function createFrameDispatch({root,run=runFrameProcess,maxFrames=18,maxSeconds=90}){
 if(!Number.isInteger(maxFrames)||maxFrames<1||!Number.isFinite(maxSeconds)||maxSeconds<=0)throw Error('invalid_sample_limits');
 const key=video=>createHash('sha256').update(video).digest('hex');
 const load=async video=>JSON.parse(await readFile(join(root,'videos',key(video)+'.json'),'utf8'));
 return async(name,args)=>{
  await mkdir(join(root,'videos'),{recursive:true});await mkdir(join(root,'samples'),{recursive:true});
  if(name==='watch_video'){
   let manifest;
   try{manifest=await load(args.video);}catch(e){if(e.code!=='ENOENT')throw e;
    manifest=await run({operation:'prepare',video:args.video,timeout_seconds:Math.min(30,maxSeconds)});
    await writeFile(join(root,'videos',key(args.video)+'.json'),JSON.stringify(manifest));
   }
   return {content:[text({status:'DONE',video:args.video,duration_seconds:manifest.duration})]};
  }
  if(name==='get_frames'){
   if(!/^[a-f0-9-]{36}$/.test(args.sample_id??''))throw Error('sample_id_required');
   const sample=JSON.parse(await readFile(join(root,'samples',args.sample_id+'.json'),'utf8'));
   const kind=args.kind??'grids',start=args.start??1,count=args.count??2;
   if(!['grids','frames'].includes(kind)||!Number.isInteger(start)||start<1||!Number.isInteger(count)||count<1||count>3)throw Error('image_index');
   const items=kind==='grids'?sample.images:sample.selection;
   if(start>items.length)throw Error('image_index');
   const content=[text({sample_id:args.sample_id,kind,start,count:Math.min(count,items.length-start+1),range:sample.range})];
   for(const item of items.slice(start-1,start-1+count)){
    content.push(text(item));if(item.status!=='missing')content.push(await image(kind==='grids'?item.path:item.source_path));
   }
   return {content};
  }
  const manifest=await load(args.video);
  if(name==='sample_video_frames'){
   const frame_count=args.frame_count??Math.min(18,maxFrames),begin=args.start_seconds??0,end=args.end_seconds??manifest.duration,timeout_seconds=(args.timeout_ms??maxSeconds*1000)/1000;
   if(!Number.isInteger(frame_count)||frame_count<1||frame_count>maxFrames)throw Error(`sample_budget: frame_count must be an integer in 1–${maxFrames}; default ${Math.min(18,maxFrames)}`);
   if(!Number.isFinite(timeout_seconds)||timeout_seconds<=0||timeout_seconds>maxSeconds)throw Error(`sample_budget: timeout_ms must be >0 and <=${maxSeconds*1000}; default ${maxSeconds*1000}`);
   if(!Number.isFinite(begin)||!Number.isFinite(end)||begin<0||end<=begin||end>manifest.duration)throw Error('sample_range');
   const sample_id=randomUUID(),output=join(root,'samples',sample_id);
   const result=await run({operation:'sample',manifest,output,frame_count,start_seconds:begin,end_seconds:end,timeout_seconds});
   await writeFile(join(root,'samples',sample_id+'.json'),JSON.stringify(result),{flag:'wx'});
   return {content:[text({sample_id,status:result.status,range:result.range,frame_count:result.selection.length,grid_count:result.images.length,selection:result.selection.map(({source_path,...entry})=>entry)})]};
  }
  if(name==='get_frame_at'){
   const parts=String(args.time).split(':');if(parts.length>3||parts.some(p=>!/^\d+(?:\.\d+)?$/.test(p)))throw Error('invalid_time');
   const time=parts.reduce((a,p)=>a*60+Number(p),0);if(!Number.isFinite(time)||time<0||time>=manifest.duration)throw Error('invalid_time');
   const output=join(root,'moments',randomUUID());
   const result=await run({operation:'at',manifest,output,time,timeout_seconds:maxSeconds});
   return {content:[text(result),await image(result.path)]};
  }
  throw Error('TOOL_NOT_ALLOWED');
 };
}
