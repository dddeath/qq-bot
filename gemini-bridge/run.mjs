import {readFileSync,mkdirSync,appendFileSync,writeFileSync} from 'node:fs';
import {join} from 'node:path';
import {randomUUID} from 'node:crypto';
import {FoxPilot} from './foxpilot.mjs';
import {GeminiPage} from './browser.mjs';

const config=JSON.parse(readFileSync(process.argv[2],'utf8'));
const dir=join(config.evidenceRoot,new Date().toISOString().replace(/[:.]/g,'-')+'-'+randomUUID().slice(0,8));
mkdirSync(dir,{recursive:true});
writeFileSync(join(dir,'pid.txt'),String(process.pid));
function log(stage,fields={}){const item={at:new Date().toISOString(),stage,...fields};appendFileSync(join(dir,'events.jsonl'),JSON.stringify(item)+'\n');console.log(JSON.stringify(item));}
async function api(path,body={}) {
  const r=await fetch(config.bridgeUrl+path,{method:'POST',headers:{'Content-Type':'application/json',Authorization:'Bearer '+config.bridgeToken},body:JSON.stringify(body),signal:AbortSignal.timeout(30000)});
  if(!r.ok)throw Error(`bridge ${path}: HTTP ${r.status}`);
  return r.json();
}
const fox=new FoxPilot(config.foxpilotServer);
const page=new GeminiPage(fox,config);
let active=null;
try {
  await fox.start();log('browser_ready',await page.connect());
  while(true) {
    const job=await api('/claim');
    if(!job){await new Promise(r=>setTimeout(r,1000));continue;}
    active=job.id;log('claimed',{id:active});
    await page.submit(job);await api('/submitted',{id:active});log('submitted',{id:active});
    const deadline=Date.now()+(config.timeoutSeconds||300)*1000;
    while(true) {
      if(Date.now()>deadline)throw Error('Gemini generation timeout');
      const p=await page.inspect(active);
      const current=await api('/observe',{id:active,request_seen:p.request_seen,text:p.text,complete:p.complete});
      log('observation',{id:active,request_seen:p.request_seen,complete:p.complete,characters:p.text.length,state:current.state});
      if(current.state==='UNKNOWN')throw Error('Remote bridge stopped this job');
      if(current.state==='READY')break;
      await new Promise(r=>setTimeout(r,1500));
    }
    const result=await api('/send');log('send_result',result||{});
    if(result?.state!=='SENT')throw Error('QQ send not confirmed');
    active=null;
    if(config.once)break;
  }
}catch(e){
  log('stopped',{id:active,error:String(e)});
  if(active)try{await api('/unknown',{id:active,reason:String(e)});}catch{}
  process.exitCode=1;
}finally{fox.close();}
