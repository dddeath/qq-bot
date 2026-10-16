import {Client} from '@modelcontextprotocol/sdk/client/index.js';
import {StdioClientTransport} from '@modelcontextprotocol/sdk/client/stdio.js';
import {fileURLToPath} from 'node:url';
import {readLearningFrames} from './learning-frames.mjs';

let input='';for await(const chunk of process.stdin)input+=chunk;
const request=JSON.parse(input);
const client=new Client({name:'daily-learning-video',version:'1.0.0'});
try{
 await client.connect(new StdioClientTransport({command:process.execPath,
  args:[fileURLToPath(new URL('./server.mjs',import.meta.url))],env:{...process.env},stderr:'inherit'}));
 const result=await readLearningFrames(request,(name,args,timeout)=>client.callTool({name,arguments:args},undefined,{timeout}));
 console.log(JSON.stringify(result));
}finally{await client.close();}
