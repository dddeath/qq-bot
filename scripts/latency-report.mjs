import fs from 'node:fs';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
const duration=(a,b)=>{const d=Date.parse(b)-Date.parse(a);return Number.isFinite(d)&&d>=0?d:null;};
function sample(s){
 const status=s.dot??{};
 const m=status.messages?.find(m=>m.message_id===s.message_id);
 const deliveries=(status.deliveries??[]).filter(d=>d.message_id===s.message_id);
 const accepted=deliveries.find(d=>d.accepted);
 const calls=(status.calls??[]).filter(c=>c.message_id===s.message_id&&c.source==='mcp-http');
 const read=calls.find(c=>c.tool==='qq_group_get_message'&&c.read_succeeded);
 const call=calls.find(c=>c.tool==='qq_group_reply_message');
 const reply=status.replies?.find(r=>r.message_id===s.message_id);
 const fixed=s.fixed;
 const attempts=accepted?deliveries.slice(0,deliveries.indexOf(accepted)+1):deliveries;
 const requestTimes=attempts.map(d=>duration(d.started_at,d.at));
 const requestMs=requestTimes.length&&requestTimes.every(t=>t!==null)?requestTimes.reduce((a,b)=>a+b,0):null;
 const deliveryMs=duration(attempts[0]?.started_at,accepted?.at);
 const retryWait=deliveryMs!==null&&requestMs!==null&&deliveryMs>=requestMs?deliveryMs-requestMs:null;
 const received=s.mode==='fixed'?fixed?.receive?.records?.find(r=>r.stage==='matching_ordinary_group_message')?.at:m?.created_at;
 const started=s.mode==='fixed'?fixed?.timing?.send_started_at:reply?.at;
 const finished=s.mode==='fixed'?fixed?.timing?.send_finished_at:reply?.finished_at;
 if ((received!=null&&duration(s.started_at,received)===null)||
     (finished!=null&&duration(s.started_at,finished)===null)) throw new Error('Invalid sample timing: record predates sampling window');
 if ((received!=null&&(duration(received,s.deadline_at)===null||duration(received,s.observed_at)===null))||
     (finished!=null&&duration(finished,s.observed_at)===null)) throw new Error('Invalid sample timing: receive outside window or record after snapshot');
 if (received!=null&&finished!=null&&duration(received,finished)===null) throw new Error('Invalid sample timing: completion precedes reception');
 const confirmed=s.mode==='fixed'?fixed?.send_state==='confirmed':reply?.state==='confirmed';
 const late=confirmed&&Date.parse(finished)>Date.parse(s.deadline_at);
 const expired=Date.parse(s.observed_at)>=Date.parse(s.deadline_at);
 const failed=s.mode==='fixed'?fixed?.success===false:reply&&['unknown','rejected'].includes(reply.state);
 const outcome=s.timed_out===true||late||fixed?.receive?.records?.some(r=>r.stage==='receive_timeout')?'timeout':confirmed?'success':failed?'failed':expired?'timeout':'pending';
 return {id:s.id,mode:s.mode,group_openid:s.group_openid,measurement_version:s.measurement_version??null,outcome,local_ms:confirmed?duration(received,finished):null,client_ms:s.client?.same_clock===true?duration(s.client.sent_at,s.client.received_at):null,client:s.client??null,
  late_reply_at:outcome==='timeout'&&confirmed?finished:null,
  points:{received_at:received??null,delivery_started_at:deliveries[0]?.started_at??null,delivery_accepted_at:accepted?.at??null,first_read_at:read?.at??null,reply_called_at:call?.at??null,send_started_at:started??null,send_finished_at:finished??null},
  delivery_attempts:deliveries,
  stages:{receive_to_delivery_ms:duration(received,deliveries[0]?.started_at),delivery_requests_ms:requestMs,delivery_retry_wait_ms:retryWait,delivery_ms:duration(deliveries[0]?.started_at,accepted?.at),wait_first_read_ms:duration(accepted?.at,read?.at),read_to_reply_ms:duration(read?.at,call?.at),qq_send_ms:duration(started,finished),probe_overhead_ms:s.mode==='fixed'?duration(received,started):null}};
}
const median=xs=>{const a=xs.toSorted((x,y)=>x-y);return a.length?(a[Math.floor((a.length-1)/2)]+a[Math.floor(a.length/2)])/2:null;};
function group(samples){
 const counts={total:samples.length,success:0,failed:0,timeout:0,pending:0};for(const s of samples)counts[s.outcome]++;
 const times=samples.filter(s=>s.outcome==='success'&&s.local_ms!==null).map(s=>s.local_ms);
 const local_target=counts.failed||counts.timeout||times.some(t=>t>10000)?'未达到':samples.length===5&&times.length===5&&new Set(samples.map(s=>s.group_openid)).size===1?'达到':'证据不足';
 const client=samples.map(s=>s.client_ms);
 const target=local_target==='未达到'||client.some(t=>t!==null&&t>10000)?'未达到':local_target==='达到'&&client.every(t=>t!==null)?'达到':'证据不足';
 const labels={receive_to_delivery_ms:'接收至事件投递',delivery_ms:'事件投递及重试',wait_first_read_ms:'等待首次读取',read_to_reply_ms:'读取后至回复调用',qq_send_ms:'QQ 请求',probe_overhead_ms:'固定探针收尾及发送前开销'};
 const stages=Object.entries(labels).map(([key,label])=>({label,median:median(samples.map(s=>s.stages[key]).filter(x=>x!==null))})).filter(s=>s.median!==null).sort((a,b)=>b.median-a.median);
 const investigate=stages.length?'优先核对'+stages[0].label+'阶段，中位数 '+stages[0].median+' ms；需结合平台轨迹定位，不等同于模型思考时间。':'时间点不足，先补齐观测。';
 return {counts,local_target,stage_medians:stages,investigate,median_success_ms:median(times),slowest_success_ms:times.length?Math.max(...times):null,
  target,conclusion_scope:'仅描述本组样本，不证明持续性能；客户端时间仅同端相减。'};
}

const [input,output]=process.argv.slice(2);
const raw=fs.readFileSync(input,'utf8');const data=JSON.parse(raw.replace(/^\uFEFF/,''));
if (!Array.isArray(data.samples)) throw new Error('Invalid samples array');
const ids=new Set();
for(const s of data.samples){
 const group=s.mode==='fixed'?s.fixed?.receive?.matched_event?.d?.group_openid:s.dot?.messages?.find(m=>m.message_id===s.message_id)?.group_openid;
 if(!s.id||ids.has(s.id)||!['fixed','dot','search'].includes(s.mode)||!s.group_openid||
  !['started_at','deadline_at','observed_at'].every(k=>Number.isFinite(Date.parse(s[k])))||
  duration(s.started_at,s.deadline_at)!==120000||duration(s.started_at,s.observed_at)===null||
  (group!==undefined&&group!==s.group_openid)) throw new Error('Invalid sample identity, group or 120-second observation window');
 ids.add(s.id);
}
const samples=data.samples.map(sample);
const measured=data.samples.filter(s=>s.mode!=='search');
const comparison={eligible:measured.length===10&&new Set(measured.map(s=>s.group_openid)).size===1&&
 measured.every((s,i)=>s.mode===(i%2===0?'fixed':'dot')&&(i===0||duration(measured[i-1].ended_at,s.started_at)>=30000)),
 requirement:'同群固定/dot 交替各5条，上一条结束至下一条开始至少30秒；相近环境仍须主控核验。'};
const report={samples,comparison,groups:Object.fromEntries(['fixed','dot','search'].map(mode=>[mode,group(samples.filter(s=>s.mode===mode))])),command:[process.execPath,...process.argv.slice(1)],exit_status:0,node:process.version,
 git_head:execFileSync('git',['rev-parse','HEAD'],{encoding:'utf8'}).trim()};
fs.mkdirSync(output,{recursive:true});const dir=fs.mkdtempSync(path.join(path.resolve(output),new Date().toISOString().replaceAll(':','-')+'-'));
fs.writeFileSync(path.join(dir,'raw-input.json'),raw);fs.writeFileSync(path.join(dir,'report.json'),JSON.stringify(report,null,2));console.log(dir);
