export const videoContextSchema={name:'get_video_context',description:'Collect video description, native subtitles, bounded comments and timestamped danmaku for a background video task. Missing sources remain explicit. comment_limit: integer 1–50 (default 10); danmaku_limit: integer 1–200 (default 80). Zero is invalid; omit for defaults. page is a positive integer. start_seconds/end_seconds are nonnegative absolute seconds with end >= start. Visual reading uses watch_video, sample_video_frames, then get_frames. Audience comments are not author statements or subtitles.',annotations:{readOnlyHint:true,destructiveHint:false,openWorldHint:true},inputSchema:{type:'object',properties:{structured_comments:{type:'boolean',default:false},bvid_or_url:{type:'string'},page:{type:'integer',minimum:1},comment_limit:{type:'integer',minimum:1,maximum:50,default:10},danmaku_limit:{type:'integer',minimum:1,maximum:200,default:80},start_seconds:{type:'number',minimum:0},end_seconds:{type:'number',minimum:0}},required:['bvid_or_url'],additionalProperties:false}};

import {readFile} from 'node:fs/promises';
export async function collectVideoContext(args,call){
 const value=String(args.bvid_or_url??'');let bvid=value,page=args.page??1;
 const invalid=(detail='bvid_or_url/page must identify a valid matching video part')=>Object.assign(new Error(detail),{code:'INVALID_VIDEO_CONTEXT_ARGUMENT',argumentDetail:detail});
 if(!/^BV[\da-zA-Z]{10}$/.test(value)){
  let u;try{u=new URL(value);}catch{throw invalid();}
  if(!['http:','https:'].includes(u.protocol)||!['www.bilibili.com','m.bilibili.com','bilibili.com'].includes(u.hostname))throw invalid();
  bvid=u.pathname.match(/^\/video\/(BV[\da-zA-Z]{10})\/?$/)?.[1];
  const p=u.searchParams.get('p');
  if(p && args.page!==undefined && Number(p)!==args.page)throw invalid();
  page=args.page??Number(p??1);
 }
 const comments=args.comment_limit??10,danmaku=args.danmaku_limit??80;
 if(!Number.isInteger(comments)||comments<1||comments>50)throw invalid('comment_limit must be an integer in 1–50; default 10; zero is invalid');
 if(!Number.isInteger(danmaku)||danmaku<1||danmaku>200)throw invalid('danmaku_limit must be an integer in 1–200; default 80; zero is invalid');
 if(!bvid||!Number.isInteger(page)||page<1||!Number.isInteger(comments)||comments<1||comments>50||!Number.isInteger(danmaku)||danmaku<1||danmaku>200)throw invalid();
 for(const k of ['start_seconds','end_seconds'])if(args[k]!==undefined&&(!Number.isFinite(args[k])||args[k]<0))throw invalid();
 if(args.end_seconds!==undefined&&args.end_seconds<(args.start_seconds??0))throw invalid();
 const url=`https://www.bilibili.com/video/${bvid}/?p=${page}`;
 const common={bvid_or_url:url,page};
 for(const k of ['start_seconds','end_seconds'])if(args[k]!==undefined)common[k]=args[k];
 const requests=[['chapters','get_video_chapters',{bvid_or_url:url,page},'selected_part_chapters'],['description','get_video_metadata',{bvid_or_url:bvid},'whole_video_author_description'],['subtitles','get_video_transcript',common,'selected_part_subtitles'],['comments',args.structured_comments?'get_video_comment_threads':'get_video_comments',args.structured_comments?{bvid_or_url:bvid,page:1,page_size:Math.min(comments,20)}:{bvid_or_url:bvid,limit:comments,include_replies:false},'whole_video_comment_sample'],['danmaku','get_video_danmaku',{...common,limit:danmaku},'selected_part_current_pool']];
 const materials=Object.fromEntries(await Promise.all(requests.map(async([key,name,input,scope])=>{
  const r=await call(name,input);
  return [key,{status:r.status,scope,error:r.error,data:r.data,source:r.source,fetched_at:r.fetched_at,elapsed_ms:r.elapsed_ms}];
 })));
 const missing=Object.keys(materials).filter(k=>materials[k].status!=='ok');
 const reading_policy=JSON.parse(await readFile(process.env.QQ_VIDEO_EXPLORATION_CONFIG??new URL('../video-reading-policy.json',import.meta.url),'utf8'));
 return {bvid,page,source_url:url,materials,missing,reading_policy,complete:false,text_materials_complete:missing.length===0,frames:{status:'not_requested',video:url,next_tools:['video_frames.watch_video','video_frames.sample_video_frames','video_frames.get_frames']}};
}
