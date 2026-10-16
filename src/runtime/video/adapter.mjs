import {createHash,randomUUID} from 'node:crypto';
export const allowedTools=['watch_video','sample_video_frames','get_frames','get_frame_at'];

export function createVideoAdapter(dispatch,record=()=>{},prepareVideo=async v=>v) {
  const sources=new Map();
  return {async call(name,args={}) {
    if(!allowedTools.includes(name)) throw new Error('TOOL_NOT_ALLOWED');
    const input={...args};
    if(name==='watch_video') {
      delete input.mode;
      delete input.refresh;
      delete input.wait_seconds;
      delete input.model;
      delete input.output_dir;
      delete input.cookies_from_browser;
    }
    const started_at=new Date().toISOString(),start=performance.now();
    let result,status='ERROR';
    try {
      if(name==='get_frames') {
        result=await dispatch(name,input);status=result.isError?'ERROR':'OK';return result;
      }
      if(!sources.has(args.video)) sources.set(args.video,Promise.resolve().then(()=>prepareVideo(args.video)).then(video=>({video}),()=>({error:'VIDEO_ACQUISITION_FAILED'})));
      const sourceJob=sources.get(args.video);
      let timer;
      const prepared=await Promise.race([sourceJob,new Promise(resolve=>{timer=setTimeout(()=>resolve(null),5000);})]);
      clearTimeout(timer);
      if(!prepared) {
        status='RUNNING';
        result={content:[{type:'text',text:'RUNNING: acquiring video; poll watch_video with the identical video argument.'}]};
        return result;
      }
      if(prepared.error) {
        if(sources.get(args.video)===sourceJob)sources.delete(args.video);
        result={isError:true,content:[{type:'text',text:'ERROR: VIDEO_ACQUISITION_FAILED. Bounded acquisition attempts ended. Check acquisition evidence and report the failure; do not loop automatically. A later explicit request may start a fresh acquisition.'}]};
        return result;
      }
      input.video=prepared.video;
      result=await dispatch(name,input);
      if(name==='watch_video' && input.video!==args.video) result={...result,content:result.content.map(x=>x.type==='text'?{...x,text:x.text+'\nThe input is a video-only track. Read original platform subtitles separately with bilibili_readonly; this extraction does not determine subtitle availability.'}:x)};
      const text=(result.content??[]).filter(x=>x.type==='text').map(x=>x.text).join('\n');
      status=result.isError || /^ERROR:/m.test(text)?'ERROR':/^RUNNING/m.test(text)?'RUNNING':name==='watch_video'?'DONE':'OK';
      if(status==='ERROR') result={...result,isError:true};
      return result;
    } finally {
      await record({call_id:randomUUID(),operation:name,video_id:createHash('sha256').update(String(args.video??'')).digest('hex').slice(0,16),started_at,finished_at:new Date().toISOString(),elapsed_ms:performance.now()-start,status,image_count:(result?.content??[]).filter(x=>x.type==='image').length});
    }
  }};
}
