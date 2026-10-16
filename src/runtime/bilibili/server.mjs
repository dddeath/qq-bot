import {Server} from '@modelcontextprotocol/sdk/server/index.js';
import {StdioServerTransport} from '@modelcontextprotocol/sdk/server/stdio.js';
import {ListToolsRequestSchema,CallToolRequestSchema} from '@modelcontextprotocol/sdk/types.js';
import {toolSchemas} from '@xzxzzx/bilibili-mcp/dist/server/tool-schemas.js';
import {handleToolCall} from '@xzxzzx/bilibili-mcp/dist/server/tool-handlers.js';
import {buildGenericErrorPayload,toErrorTextContent} from '@xzxzzx/bilibili-mcp/dist/server/error-response.js';
import {runWithOperationSignal} from '@xzxzzx/bilibili-mcp/dist/security/operation-context.js';
import {createAdapter,allowedTools} from './adapter.mjs';
import {danmakuSchema} from './danmaku.mjs';
import {commentThreadsSchema} from './comment-threads.mjs';
import {videoContextSchema} from './video-context.mjs';
import {mkdir,appendFile} from 'node:fs/promises';
import {join} from 'node:path';
import {randomUUID} from 'node:crypto';

const server=new Server({name:'qq-bilibili-readonly',version:'1.0.0'},{capabilities:{tools:{}}});
const schemas=toolSchemas.filter(t=>allowedTools.includes(t.name)).map(t=>{
  const s=structuredClone(t);
  delete s.outputSchema;
  s.annotations={readOnlyHint:true,destructiveHint:false,openWorldHint:true};
  if(s.name==='get_video_transcript') {
    for(const k of ['force_asr','fallback_to_asr','fallback_to_description']) delete s.inputSchema.properties[k];
    s.description='Read platform subtitles for the requested BV and part, with timestamps or keyword matches. No speech transcription or description fallback. Missing subtitles return an error. Subtitles are not visual observation.';
  }
  return s;
});
schemas.push(danmakuSchema,videoContextSchema,commentThreadsSchema);
const evidence=process.env.QQ_BILIBILI_EVIDENCE;
const logPath=evidence?join(evidence,`${new Date().toISOString().replaceAll(':','-')}-${randomUUID()}.jsonl`):null;
if(evidence) await mkdir(evidence,{recursive:true});
server.setRequestHandler(ListToolsRequestSchema,async()=>({tools:schemas}));
server.setRequestHandler(CallToolRequestSchema,async(req,extra)=>{
  const callId=randomUUID(),startedAt=new Date().toISOString();
  const adapter=createAdapter(async(name,args)=>{
    try {return await runWithOperationSignal(extra.signal,()=>handleToolCall(name,args,extra.signal));}
    catch(e){return toErrorTextContent(buildGenericErrorPayload(e));}
  });
  let r;
  try {r=await runWithOperationSignal(extra.signal,()=>adapter.call(req.params.name,req.params.arguments??{}));}
  catch(e){r={platform:'bilibili',status:'error',error:{code:e.message==='asr_disabled'?'ASR_DISABLED':'TOOL_NOT_ALLOWED'},elapsed_ms:0};}
  r.call_id=callId;r.started_at=startedAt;r.finished_at=new Date().toISOString();
  if(logPath) {
    try {await appendFile(logPath,JSON.stringify({call_id:callId,operation:req.params.name,started_at:startedAt,finished_at:r.finished_at,elapsed_ms:r.elapsed_ms,status:r.status,error_code:r.error?.code??null,bvid:r.source?.bvid??null})+'\n');}
    catch {r.timing_log_status='write_failed';}
  }
  return {content:[{type:'text',text:JSON.stringify(r)}],structuredContent:r,isError:r.status==='error'};
});
await server.connect(new StdioServerTransport());
