const video={type:'string',description:'Prepared video path returned by watch_video, or the same original video link.'};
export function frameToolSchemas(maxFrames=18,maxSeconds=90){
 const tool=(name,description,properties,required)=>({name,description,annotations:{readOnlyHint:true,destructiveHint:false},inputSchema:{type:'object',properties,required,additionalProperties:false}});
 return [
 tool('watch_video','Prepare a video source and return its duration. Returns RUNNING while downloading; poll with the same video. Does not generate frames.',{video},['video']),
 tool('sample_video_frames',`Generate overview frames and contact sheets; first prepare with watch_video. frame_count: integer 1–${maxFrames}, default ${Math.min(18,maxFrames)}. timeout_ms: >0 and <=${maxSeconds*1000}, default ${maxSeconds*1000}. start_seconds/end_seconds are absolute seconds: 0 <= start < end <= prepared duration. Omit range for whole video. Returns sample_id for get_frames.`,{video,start_seconds:{type:'number',minimum:0},end_seconds:{type:'number',exclusiveMinimum:0},frame_count:{type:'integer',minimum:1,maximum:maxFrames,default:Math.min(18,maxFrames)},timeout_ms:{type:'number',exclusiveMinimum:0,maximum:maxSeconds*1000}},['video']),
 tool('get_frames','View existing sampled images. Use sample_id from sample_video_frames. start/count select image numbers; for a specific time use get_frame_at.',{sample_id:{type:'string'},kind:{type:'string',enum:['grids','frames'],default:'grids'},start:{type:'integer',minimum:1,default:1,description:'1-based image number in this sample; grid number or frame number.'},count:{type:'integer',minimum:1,maximum:3,default:2,description:'Number of existing images to read.'}},['sample_id']),
 tool('get_frame_at','Extract a frame at a specified video time, including moments before and after a change.',{video,time:{type:'string',description:'Video time in seconds, mm:ss or h:mm:ss.'}},['video','time'])
 ];
}
