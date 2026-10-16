export const allowedTools = ['search_bilibili_videos','get_video_metadata','get_video_transcript','get_video_comments','get_video_chapters','search_bilibili_creators','get_bilibili_creator_content','check_bilibili_credentials','get_video_danmaku','get_video_context','get_video_comment_threads'];

import {resolveVideoInput} from './short-link.mjs';

export function createAdapter(dispatch) {
  return {async call(name,args={}) {
    if(!allowedTools.includes(name)) throw new Error('tool_not_allowed');
    args={...args};
    if(name==='get_video_transcript') {
      if(args.force_asr || args.fallback_to_asr) throw new Error('asr_disabled');
      args.force_asr=false; args.fallback_to_asr=false;
      args.fallback_to_description=false;
      args.include_timestamps=true;
    }
    const start=performance.now();
    let data, error=null;
    try {
      if(args.bvid_or_url) {
        try {args.bvid_or_url=await resolveVideoInput(args.bvid_or_url);}
        catch {error={code:'B23_RESOLUTION_FAILED',message:'Could not resolve the Bilibili short link to a video.'};throw new Error('short_link_failed');}
      }
      const raw=name==='get_video_comment_threads'?{structuredContent:await (await import('./comment-threads.mjs')).readCommentThreads(args)}:name==='get_video_context'?{structuredContent:await (await import('./video-context.mjs')).collectVideoContext(args,(n,a)=>this.call(n,a))}:name==='get_video_danmaku'?{structuredContent:await (await import('./danmaku.mjs')).readDanmaku(args)}:await dispatch(name,args);
      data=raw.structuredContent ?? JSON.parse(raw.content.find(x=>x.type==='text').text);
      if(raw.isError || data.error) error={code:data.code??data.error?.code??'UPSTREAM_ERROR',message:data.message??data.error?.message??'Upstream returned an error'};
    } catch(e) {data=null;error??={code:['get_video_danmaku','get_video_context','get_video_comment_threads'].includes(name)&&/^[A-Z][A-Z_0-9]+$/.test(e.code??'')?e.code:'UPSTREAM_FAILURE',message:e.code==='INVALID_VIDEO_CONTEXT_ARGUMENT'&&e.argumentDetail?e.argumentDetail:'Upstream request failed'};}
    const bvid=String(args.bvid_or_url??'').match(/BV[a-zA-Z0-9]{10}/)?.[0]??null;
    if(!error && name==='get_bilibili_creator_content' && args.section==='dynamics' && data?.dynamics?.length===0 && data.skipped_count>0) {
      error={code:'DYNAMIC_PARSE_EMPTY',message:`All ${data.skipped_count} upstream dynamics were skipped during parsing; this is not an empty feed.`};
    }
    const completeness=name==='get_video_danmaku'?'bounded_current_danmaku_pool':name.startsWith('search_')?'first_page_only':name==='get_video_transcript'?'returned_subtitle_scope':name==='get_video_comments'?'bounded_comment_sample':name==='get_bilibili_creator_content'?'returned_page_only':'returned_fields_only';
    if(!error && bvid && data?.bvid && data.bvid!==bvid) {error={code:'BV_MISMATCH',message:'Returned BV differs from request'};data=null;}
    return {platform:'bilibili',operation:name,status:error?'error':'ok',error,fetched_at:new Date().toISOString(),elapsed_ms:performance.now()-start,source:{bvid,page:data?.page??args.page??1,url:data?.source_url??(bvid?`https://www.bilibili.com/video/${bvid}/`:null)},completeness:error?'unavailable':completeness,scope:{requested_limit:args.limit??null,complete:false},data};
  }};
}
