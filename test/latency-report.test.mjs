import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
const iso=ms=>new Date(Date.UTC(2026,9,11)+ms).toISOString();
function dot(id, elapsed=8000) {
 return {id,mode:'dot',group_openid:'g',started_at:iso(0),deadline_at:iso(120000),observed_at:iso(130000),message_id:id,
  dot:{messages:[{message_id:id,group_openid:'g',created_at:iso(1000)}],deliveries:[{message_id:id,started_at:iso(1100),at:iso(2100),accepted:true,attempt:1}],
   calls:[{message_id:id,tool:'qq_group_get_message',source:'local-diagnostic',at:iso(2200),read_succeeded:true},{message_id:id,tool:'qq_group_get_message',source:'mcp-http',at:iso(4000),read_succeeded:true},{message_id:id,tool:'qq_group_reply_message',source:'mcp-http',at:iso(7000)}],
   replies:[{message_id:id,state:'confirmed',at:iso(7100),finished_at:iso(1000+elapsed)}]}};
}
function run(t,samples){
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'latency-')); t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));
 const input=path.join(dir,'input.json');fs.writeFileSync(input,JSON.stringify({samples}));
 const p=spawnSync(process.execPath,['scripts/latency-report.mjs',input,path.join(dir,'reports')],{encoding:'utf8'});
 assert.equal(p.status,0,p.stderr); const out=p.stdout.trim();
 return {report:JSON.parse(fs.readFileSync(path.join(out,'report.json'))),out,input};
}
test('offline CLI derives dot stages from saved records and keeps raw input',t=>{
 const {report,out,input}=run(t,[dot('a')]);const s=report.samples[0];
 assert.equal(s.outcome,'success');assert.equal(s.local_ms,8000);
 assert.equal(s.stages.delivery_ms,1000);assert.equal(s.stages.wait_first_read_ms,1900);
 assert.equal(s.stages.read_to_reply_ms,3000);assert.equal(s.stages.qq_send_ms,1900);
 assert.equal(s.client_ms,null);assert.equal(report.groups.dot.target,'证据不足');
 assert.equal(fs.readFileSync(path.join(out,'raw-input.json'),'utf8'),fs.readFileSync(input,'utf8'));
});

test('offline CLI retains timeout and late confirmation and separates fixed overhead and search',t=>{
 const late=dot('late',125000);
 const failed=dot('failed');failed.dot.replies[0].state='rejected';
 const fixed={id:'fixed',mode:'fixed',group_openid:'g',started_at:iso(0),deadline_at:iso(120000),observed_at:iso(130000),
  fixed:{success:true,send_state:'confirmed',group_openid:'g',receive:{matched_event:{d:{group_openid:'g'}},records:[{stage:'matching_ordinary_group_message',at:iso(1000)}]},
   timing:{receive_finished_at:iso(2000),send_started_at:iso(2100),send_finished_at:iso(3000)}}};
 const {report}=run(t,[dot('ok'),late,failed,fixed,{...dot('search'),mode:'search'}]);
 assert.equal(report.samples[1].outcome,'timeout');assert.equal(report.samples[1].late_reply_at,iso(126000));
 assert.equal(report.samples[2].outcome,'failed');assert.equal(report.samples[3].local_ms,2000);
 assert.equal(report.samples[3].stages.probe_overhead_ms,1100);
 assert.deepEqual(report.groups.dot.counts,{total:3,success:1,failed:1,timeout:1,pending:0});
 assert.equal(report.groups.dot.median_success_ms,8000);assert.equal(report.groups.dot.slowest_success_ms,8000);
 assert.equal(report.groups.dot.target,'未达到');assert.equal(report.groups.search.counts.total,1);
 assert.equal(report.samples[3].client_ms,null);
});

test('offline CLI reports client-clock evidence separately and requires five complete samples for local target',t=>{
 const samples=Array.from({length:5},(_,i)=>dot(String(i),2000+i*1000));
 for (const s of samples) s.client={sent_at:iso(3600000),received_at:iso(3609000),same_clock:true};
 const {report}=run(t,samples);
 assert.equal(report.groups.dot.local_target,'达到');assert.equal(report.groups.dot.target,'达到');
 assert.equal(report.groups.dot.median_success_ms,4000);assert.equal(report.groups.dot.slowest_success_ms,6000);
 assert.equal(report.samples[0].client_ms,9000);
 assert.equal(report.samples[0].local_ms,2000);
 const missing=dot('missing');delete missing.dot.messages[0].created_at;missing.client={sent_at:iso(0),received_at:iso(1000)};
 const r=run(t,[missing]).report;assert.equal(r.samples[0].local_ms,null);assert.equal(r.samples[0].client_ms,null);
 assert.equal(r.groups.dot.target,'证据不足');
});

test('retry timing separates request time from backoff and reports data-based investigation direction',t=>{
 const s=dot('retry');s.dot.deliveries=[{message_id:'retry',started_at:iso(1100),at:iso(1300),accepted:false,attempt:1},
 {message_id:'retry',started_at:iso(2300),at:iso(2500),accepted:true,attempt:2}];
 const {report}=run(t,[s]);assert.equal(report.samples[0].stages.delivery_requests_ms,400);
 assert.equal(report.samples[0].stages.delivery_retry_wait_ms,1000);
 assert.match(report.groups.dot.investigate,/读取后至回复调用/);
 assert.equal(report.samples[0].stages.receive_to_delivery_ms,100);
});

test('CLI rejects ambiguous sample identity and missing deadline rather than silently claiming success',t=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'latency-invalid-'));t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));
 const a=dot('a');const missing=dot('missing');delete missing.deadline_at;
 const mismatch=dot('mismatch');mismatch.dot.messages[0].group_openid='other';
 for(const samples of [[a,a],[{...a,mode:'typo'}],[missing],[mismatch]]){
  const input=path.join(dir,'input.json');fs.writeFileSync(input,JSON.stringify({samples}));
  const p=spawnSync(process.execPath,['scripts/latency-report.mjs',input,path.join(dir,'reports')],{encoding:'utf8'});
  assert.notEqual(p.status,0);assert.match(p.stderr,/Invalid sample/);
 }
});

test('receive timeout stays timeout and mixed groups do not yield a comparable target',t=>{
 const timeout={id:'timeout',mode:'fixed',group_openid:'g',started_at:iso(0),deadline_at:iso(120000),observed_at:iso(120001),fixed:{success:false,receive:{success:false,records:[{stage:'receive_timeout',at:iso(120000)}]}}};
 assert.equal(run(t,[timeout]).report.samples[0].outcome,'timeout');
 const samples=Array.from({length:5},(_,i)=>dot('g'+i));
 samples[4].group_openid='other';samples[4].dot.messages[0].group_openid='other';
 const {report}=run(t,samples);assert.equal(report.groups.dot.local_target,'证据不足');
 assert.equal(report.comparison.eligible,false);
});

function rejectTiming(t, samples) {
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'latency-time-'));t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));
 const input=path.join(dir,'input.json'),output=path.join(dir,'reports');fs.writeFileSync(input,JSON.stringify({samples}));
 const p=spawnSync(process.execPath,['scripts/latency-report.mjs',input,output],{encoding:'utf8'});
 assert.notEqual(p.status,0);assert.match(p.stderr,/Invalid sample timing/);
 assert.equal(fs.existsSync(output),false);
}
function fixedTiming(id, received, finished) {
 return {id,mode:'fixed',group_openid:'g',started_at:iso(0),deadline_at:iso(120000),observed_at:iso(130000),
  fixed:{success:true,send_state:'confirmed',receive:{records:[{stage:'matching_ordinary_group_message',at:received}]},timing:{send_finished_at:finished}}};
}
test('sample timing rejects old replies outside the current sampling window',t=>{
 const samples=Array.from({length:5},(_,i)=>({...dot('old'+i),started_at:iso(3600000),deadline_at:iso(3720000),observed_at:iso(3730000)}));
 rejectTiming(t,samples);
 rejectTiming(t,[fixedTiming('old-fixed',iso(-9000),iso(-4000))]);
});

test('sample timing rejects receive or finish after snapshot and receive after the window',t=>{
 const futureReceive=dot('future-receive');futureReceive.observed_at=iso(500);delete futureReceive.dot.replies;
 const futureFinish=dot('future-finish');futureFinish.observed_at=iso(5000);
 const outside=dot('outside');outside.dot.messages[0].created_at=iso(121000);outside.dot.replies[0].finished_at=iso(125000);
 for(const s of [futureReceive,futureFinish,outside,fixedTiming('outside-fixed',iso(121000),iso(125000)),fixedTiming('future-fixed',iso(1000),iso(131000))])rejectTiming(t,[s]);
});

test('sample timing rejects completion before reception while retaining legal late replies',t=>{
 const reversed=dot('reversed');reversed.dot.replies[0].finished_at=iso(500);
 rejectTiming(t,[reversed]);rejectTiming(t,[fixedTiming('reversed-fixed',iso(1000),iso(500))]);
 const {report}=run(t,[dot('late',125000),fixedTiming('late-fixed',iso(1000),iso(125000))]);
 for(const s of report.samples){assert.equal(s.outcome,'timeout');assert.notEqual(s.late_reply_at,null);}
 assert.equal(report.groups.dot.counts.success,0);assert.equal(report.groups.fixed.counts.success,0);
 assert.equal(report.groups.dot.median_success_ms,null);
});
