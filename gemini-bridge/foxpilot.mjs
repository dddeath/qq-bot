import {spawn} from 'node:child_process';
import {createInterface} from 'node:readline';

export class FoxPilot {
  constructor(serverPath) {
    this.seq=0; this.pending=new Map();
    this.child=spawn(process.execPath,[serverPath],{stdio:['pipe','pipe','pipe'],windowsHide:true});
    createInterface({input:this.child.stdout}).on('line',line=>{
      let r;try{r=JSON.parse(line);}catch{return;}
      const p=this.pending.get(r.id);if(!p)return;
      this.pending.delete(r.id);clearTimeout(p.timer);
      r.error?p.reject(new Error(r.error.message)):p.resolve(r.result);
    });
    this.child.stderr.on('data',()=>{});
    const fail=()=>{for(const p of this.pending.values()){clearTimeout(p.timer);p.reject(new Error('FoxPilot disconnected'));}this.pending.clear();};
    this.child.on('exit',fail);this.child.on('error',fail);
  }
  request(method,params) {
    return new Promise((resolve,reject)=>{
      const id=++this.seq;
      const timer=setTimeout(()=>{this.pending.delete(id);reject(new Error('FoxPilot request timed out'));},45000);
      this.pending.set(id,{resolve,reject,timer});
      this.child.stdin.write(JSON.stringify({jsonrpc:'2.0',id,method,params})+'\n');
    });
  }
  async start() {
    await this.request('initialize',{protocolVersion:'2024-11-05',capabilities:{},clientInfo:{name:'qq-gemini-probe',version:'0.1'}});
    this.child.stdin.write(JSON.stringify({jsonrpc:'2.0',method:'notifications/initialized'})+'\n');
  }
  async call(name,args={}) {
    const r=await this.request('tools/call',{name,arguments:args});
    if(r.isError)throw Error(r.content?.map(x=>x.text||'').join('\n')||'FoxPilot tool failed');
    return r;
  }
  close(){this.child.kill();}
}

export function unpack(r) {
  if(r.structuredContent)return r.structuredContent;
  const text=r.content?.filter(x=>x.type==='text').map(x=>x.text).join('\n')||'';
  try{return JSON.parse(text);}catch{return text;}
}
