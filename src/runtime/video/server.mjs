import {Server} from '@modelcontextprotocol/sdk/server/index.js';
import {StdioServerTransport} from '@modelcontextprotocol/sdk/server/stdio.js';
import {ListToolsRequestSchema,CallToolRequestSchema} from '@modelcontextprotocol/sdk/types.js';
import {mkdir,appendFile} from 'node:fs/promises';
import {join} from 'node:path';
import {randomUUID} from 'node:crypto';
import {pathToFileURL} from 'node:url';
import {allowedTools,createVideoAdapter} from './adapter.mjs';
import {createVideoSource} from './source.mjs';

import {createFrameDispatch} from './frame-tools.mjs';
import {frameToolSchemas} from './tool-schemas.mjs';
const maxFrames=Number(process.env.QQ_VIDEO_MAX_SAMPLE_FRAMES??18);
const maxSeconds=Number(process.env.QQ_VIDEO_SAMPLE_TIMEOUT_SECONDS??90);
const schemas=frameToolSchemas(maxFrames,maxSeconds);
const evidence=process.env.QQ_VIDEO_EVIDENCE;
if(!evidence) throw new Error('QQ_VIDEO_EVIDENCE is required');
await mkdir(evidence,{recursive:true});
const log=join(evidence,`${new Date().toISOString().replaceAll(':','-')}-${randomUUID()}.jsonl`);
const record=r=>appendFile(log,JSON.stringify(r)+'\n');
const bili=process.env.QQ_VIDEO_BILIBILI;
const {fetchWithoutWBI}=await import(pathToFileURL(join(bili,'node_modules/@xzxzzx/bilibili-mcp/dist/bilibili/http.js')));
const {resolveVideoInput}=await import(pathToFileURL(join(bili,'short-link.mjs')));
const prepare=createVideoSource({root:join(process.env.YUEYING_OUT_DIR,'sources'),api:fetchWithoutWBI,resolveShort:resolveVideoInput,record,maxBytes:Number(process.env.QQ_VIDEO_MAX_BYTES??536870912)});
const adapter=createVideoAdapter(createFrameDispatch({root:join(evidence,'frame-store'),maxFrames,maxSeconds}),record,prepare);
const server=new Server({name:'qq-video-frames',version:'1.0.0'},{capabilities:{tools:{}}});
server.setRequestHandler(ListToolsRequestSchema,async()=>({tools:schemas}));
server.setRequestHandler(CallToolRequestSchema,async(req)=>{try{return await adapter.call(req.params.name,req.params.arguments??{});}catch(e){return {isError:true,content:[{type:'text',text:'ERROR: '+e.message}]};}});
await server.connect(new StdioServerTransport());
let closing=false;
async function close(){if(closing)return;closing=true;process.exit(0);}
process.stdin.on('end',close);
process.on('SIGTERM',close);
process.on('SIGINT',close);
