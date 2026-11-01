import {checkArguments} from './argument-errors.mjs';
export const videoContextSchema={
  "name": "get_video_context",
  "description": "Collect video description, native subtitles, bounded comments and timestamped danmaku for a background video task. Missing sources remain explicit. comment_limit: integer 1–50 (default 10); danmaku_limit: integer 1–200 (default 80). Zero is invalid; omit for defaults. page is a positive integer. start_seconds/end_seconds are nonnegative absolute seconds with end >= start. Visual reading uses watch_video, sample_video_frames, then get_frames. Audience comments are not author statements or subtitles.",
  "annotations": {
    "readOnlyHint": true,
    "destructiveHint": false,
    "openWorldHint": true
  },
  "inputSchema": {
    "type": "object",
    "properties": {
      "structured_comments": {
        "type": "boolean",
        "default": false,
        "description": "Return root/reply structure when true, capped at 20 roots. Preserve the returned page_size for continuation."
      },
      "bvid_or_url": {
        "type": "string",
        "description": "BV identifier or full/short Bilibili video URL. A URL-selected part is retained; an explicit page must match that part."
      },
      "page": {
        "type": "integer",
        "minimum": 1,
        "description": "1-based video part (P). Omit to retain the part selected by the URL; plain BV defaults to P1."
      },
      "comment_limit": {
        "type": "integer",
        "minimum": 1,
        "maximum": 50,
        "default": 10,
        "description": "Maximum comments, 1–50 in flat mode. structured_comments caps the root page at 20; continue with its returned page_size and next_page."
      },
      "danmaku_limit": {
        "type": "integer",
        "minimum": 1,
        "maximum": 200,
        "default": 80,
        "description": "Maximum timestamped danmaku items to request, 1–200."
      },
      "start_seconds": {
        "type": "number",
        "minimum": 0,
        "description": "Inclusive start of the time filter, in absolute seconds within the selected video part."
      },
      "end_seconds": {
        "type": "number",
        "minimum": 0,
        "description": "Inclusive end of the time filter in the selected part; must be at least start_seconds."
      }
    },
    "required": [
      "bvid_or_url"
    ],
    "additionalProperties": false
  }
};



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

 checkArguments('INVALID_VIDEO_CONTEXT_ARGUMENT',[
 ['bvid_or_url',!!bvid,'Expected BV or Bilibili video URL.'],['page',Number.isInteger(page)&&page>=1,'Expected positive integer video part.'],
 ['comment_limit',Number.isInteger(comments)&&comments>=1&&comments<=50,'Expected integer 1–50; zero is invalid.'],
 ['danmaku_limit',Number.isInteger(danmaku)&&danmaku>=1&&danmaku<=200,'Expected integer 1–200; zero is invalid.'],
 ...['start_seconds','end_seconds'].map(k=>[k,args[k]===undefined||(Number.isFinite(args[k])&&args[k]>=0),'Expected nonnegative finite seconds.']),
 ['end_seconds',args.end_seconds===undefined||args.end_seconds>=(args.start_seconds??0),'Expected end_seconds >= start_seconds.']]);

 const url=`https://www.bilibili.com/video/${bvid}/?p=${page}`;

 const common={bvid_or_url:url,page};

 for(const k of ['start_seconds','end_seconds'])if(args[k]!==undefined)common[k]=args[k];

 const requests=[['chapters','get_video_chapters',{bvid_or_url:url,page},'selected_part_chapters'],['description','get_video_metadata',{bvid_or_url:bvid},'whole_video_author_description'],['subtitles','get_video_transcript',common,'selected_part_subtitles'],['comments',args.structured_comments?'get_video_comment_threads':'get_video_comments',args.structured_comments?{bvid_or_url:bvid,page:1,page_size:Math.min(comments,20)}:{bvid_or_url:bvid,limit:comments,include_replies:false},'whole_video_comment_sample'],['danmaku','get_video_danmaku',{...common,limit:danmaku},'selected_part_current_pool']];

 const materials=Object.fromEntries(await Promise.all(requests.map(async([key,name,input,scope])=>{

  const r=await call(name,input);

  return [key,{status:r.status,scope,error:r.error,data:r.data,source:r.source,fetched_at:r.fetched_at,elapsed_ms:r.elapsed_ms}];

 })));

 const missing=Object.keys(materials).filter(k=>materials[k].status!=='ok');

 const reading_policy=JSON.parse(await readFile(process.env.QQ_VIDEO_EXPLORATION_CONFIG??new URL('../../../config/video-reading-policy.json',import.meta.url),'utf8'));

 return {bvid,page,source_url:url,materials,missing,reading_policy,complete:false,text_materials_complete:missing.length===0,frames:{status:'not_requested',video:url,next_tools:['video_frames.watch_video','video_frames.sample_video_frames','video_frames.get_frames']}};

}
