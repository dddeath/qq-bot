// Real MCP transport probe. Every invocation preserves its own record and images.
import {Client} from '@modelcontextprotocol/sdk/client/index.js';
import {StdioClientTransport} from '@modelcontextprotocol/sdk/client/stdio.js';
import {mkdir,writeFile} from 'node:fs/promises';
import {join,dirname} from 'node:path';
import {fileURLToPath} from 'node:url';
import {randomUUID} from 'node:crypto';
const here=dirname(fileURLToPath(import.meta.url));
const video=process.argv[2];
if(!video)throw new Error('Usage: node probe.mjs VIDEO');
const run=join(process.env.QQ_VIDEO_EVIDENCE,'probe-'+new Date().toISOString().replaceAll(':','-')+'-'+randomUUID());
await mkdir(run,{recursive:true});
const client=new Client({name:'video-acceptance',version:'1.0.0'});
const calls=[];
async function call(name,args){
  const start=performance.now(),at=new Date().toISOString();
  const r=await client.callTool({name,arguments:args},undefined,{timeout:120000});
  const out=[];
  for(const item of r.content??[]) {
    if(item.type==='image'){
      const path=join(run,`call-${calls.length}-image-${out.length}.jpg`);
      await writeFile(path,Buffer.from(item.data,'base64'));
      out.push({type:'image',mimeType:item.mimeType,path,bytes:Buffer.from(item.data,'base64').length});
    }else out.push(item);
  }
  calls.push({name,args,started_at:at,elapsed_ms:performance.now()-start,isError:r.isError??false,content:out});
  await writeFile(join(run,'calls.json'),JSON.stringify(calls,null,2));
  return r;
}
try{
  await client.connect(new StdioClientTransport({command:process.execPath,args:[join(here,'server.mjs')],env:{...process.env},stderr:'inherit'}));
  const tools=await client.listTools();
  await writeFile(join(run,'tools.json'),JSON.stringify(tools,null,2));
  if(tools.tools.length!==4 || 'mode' in tools.tools.find(t=>t.name==='watch_video').inputSchema.properties)throw new Error('unexpected tool schema');
  let ready=false;
  for(let i=0;i<120;i++){
    const r=await call('watch_video',{video});
    const text=r.content.filter(x=>x.type==='text').map(x=>x.text).join('\n');
    if(r.isError)throw new Error(text);
    if(!text.startsWith('RUNNING')){ready=true;break;}
    await new Promise(r=>setTimeout(r,1000));
  }
  if(!ready)throw new Error('video readiness timeout');
  const sample=await call('sample_video_frames',{video,frame_count:18});
  const sample_id=JSON.parse(sample.content.find(x=>x.type==='text').text).sample_id;
  const frames=await call('get_frames',{sample_id,kind:'grids',start:1,count:2});
  if(!frames.content.some(x=>x.type==='image'))throw new Error('no image content received');
  const frame=await call('get_frame_at',{video,time:'00:05'});
  if(!frame.content.some(x=>x.type==='image'))throw new Error('no timestamp image received');
  await writeFile(join(run,'result.json'),JSON.stringify({status:'passed',video,run}));
  console.log(run);
}catch(e){await writeFile(join(run,'result.json'),JSON.stringify({status:'failed',error:String(e)}));console.error(String(e));console.log(run);process.exitCode=1;}
finally{await client.close();}
