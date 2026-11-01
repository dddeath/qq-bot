const video={type:'string',description:'Original video link/path used in a completed watch_video call; keep the argument unchanged across sampling calls.'};

export function frameToolSchemas(maxFrames=18,maxSeconds=90){

 const tool=(name,description,properties,required)=>({name,description,annotations:{readOnlyHint:true,destructiveHint:false},inputSchema:{type:'object',properties,required,additionalProperties:false}});

 return [

 tool('watch_video','Prepare a video source and return its duration. Returns RUNNING while downloading; poll with the same video. Does not generate frames.',{video},['video']),

 tool('sample_video_frames',`Generate overview frames and contact sheets; first prepare with watch_video. frame_count: integer 1–${maxFrames}, default ${Math.min(18,maxFrames)}. timeout_ms: >0 and <=${maxSeconds*1000}, default ${maxSeconds*1000}. start_seconds/end_seconds are absolute seconds: 0 <= start < end <= prepared duration. Omit range for whole video. Returns sample_id for get_frames.`,{video,start_seconds:{type:'number',minimum:0,description:'Absolute range start in seconds, inclusive; omit both bounds for a whole-video overview.'},end_seconds:{type:'number',exclusiveMinimum:0,description:'Absolute range end in seconds; greater than start and no later than prepared duration.'},frame_count:{type:'integer',minimum:1,maximum:maxFrames,default:Math.min(18,maxFrames),description:'Maximum uniformly spaced samples within the selected range, not contact sheets; short ranges may yield fewer frames, as reported by frame_count.'},timeout_ms:{type:'number',exclusiveMinimum:0,maximum:maxSeconds*1000,description:'Maximum sampling wait in milliseconds for this call. The surrounding reading executor separately controls its task budget.'}},['video']),

 tool('get_frames','View existing sampled images. Use sample_id from sample_video_frames. start/count select image numbers; for a specific time use get_frame_at.',{sample_id:{type:'string',description:'Opaque ID returned by sample_video_frames; reuse this to read existing images without resampling.'},kind:{type:'string',enum:['grids','frames'],default:'grids',description:'grids reads contact sheets; frames reads individual sampled images. start/count address the chosen image list.'},start:{type:'integer',minimum:1,default:1,description:'1-based image number in this sample; grid number or frame number.'},count:{type:'integer',minimum:1,maximum:3,default:2,description:'Number of existing images to read.'}},['sample_id']),

 tool('get_frame_at','Extract one frame at a specified time from a video prepared by watch_video. Use the identical video argument after preparation completes. Returns actual pixels and the sampled time; call separately for another moment.',{video,time:{type:'string',description:'Video time in seconds, mm:ss or h:mm:ss.'}},['video','time'])

 ];

}

