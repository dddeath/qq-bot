// Single bounded read-only call for the daily collector; credentials stay upstream.
import {Client} from '@modelcontextprotocol/sdk/client/index.js';
import {StdioClientTransport} from '@modelcontextprotocol/sdk/client/stdio.js';
import {fileURLToPath} from 'node:url';
let input='';for await(const chunk of process.stdin) input+=chunk;
const request=JSON.parse(input);
const c=new Client({name:'daily-creator-collector',version:'1'});
const t=new StdioClientTransport({command:process.execPath,args:[fileURLToPath(new URL('./server.mjs',import.meta.url))],env:{...process.env},stderr:'pipe'});
try {
  await c.connect(t);
  const r=await c.callTool(request,undefined,{timeout:90000});
  console.log(JSON.stringify(r.structuredContent??JSON.parse(r.content[0].text)));
} finally {await c.close();}
