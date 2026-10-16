import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import { createHash } from 'node:crypto';
import path from 'node:path';
import http from 'node:http';
import { API } from '../qq-probe/probe.mjs';
import { BridgeRouter } from '../src/qq-bridge.mjs';

test('group discovery exposes separate event and destination-free tools', async t => {
  const dir=fs.mkdtempSync(path.join(os.tmpdir(),'group-dot-'));
  t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));
  const router=new BridgeRouter(dir);
  const events=(await router.rpc('events/list')).events.map(e=>e.name);
  assert.deepEqual(events,['probe.message.created','qq.message.created','qq.group.message.created']);
  const tools=(await router.rpc('tools/list')).tools;
  assert.deepEqual(tools.filter(t=>t.name.startsWith('qq_group_')).map(t=>t.name),
    ['qq_group_list_pending_messages','qq_group_get_message','qq_group_reply_message']);
  assert.deepEqual(Object.keys(tools.find(t=>t.name==='qq_group_reply_message').inputSchema.properties),['message_id','text']);
});
const groupSubscription = () => ({ name:'qq.group.message.created', arguments:{channel_id:'qq-group-test'},
  delivery:{mode:'webhook',url:'https://group.example.com/events',secret:'whsec_'+Buffer.alloc(32,7).toString('base64')} });
function fixture(t, mode='success') {
  const dir=fs.mkdtempSync(path.join(os.tmpdir(),'group-dot-'));
  fs.mkdirSync(path.join(dir,'qq-auth'));
  fs.mkdirSync(path.join(dir,'qq-dot'));
  fs.mkdirSync(path.join(dir,'qq-group-receive'));
  fs.writeFileSync(path.join(dir,'qq-auth/config.json'),JSON.stringify({appId:'12345',appSecret:'secret'}));
  fs.writeFileSync(path.join(dir,'qq-dot/config.json'),JSON.stringify({appId:'12345',allowedRecipientHash:createHash('sha256').update('private-user').digest('hex')}));
  fs.writeFileSync(path.join(dir,'qq-group-receive/test-group.json'),JSON.stringify({group_openid:'bound-group'}));
  const callbacks=[], posts=[], tokens=[]; let socket;
  class Socket extends EventTarget {
    packet(p) { this.dispatchEvent(new MessageEvent('message',{data:JSON.stringify(p)})); }
    send(text) { const p=JSON.parse(text); queueMicrotask(()=>this.packet(p.op===2?{op:0,t:'READY',d:{session_id:'test-session'}}:{op:11})); }
    close() {}
  }
  const options={
    reconnectDelay:1,
    socketFactory:()=>{socket=new Socket();queueMicrotask(()=>socket.packet({op:10,d:{heartbeat_interval:60000}}));return socket;},
    fetchImpl:async(url,opts)=>{
      if(url===API+'/app/getAppAccessToken') {const id=JSON.parse(opts.body).appId;tokens.push(id);return {ok:true,status:200,json:async()=>({access_token:'test-token-'+id,expires_in:7200})};}
      if(url===API+'/gateway') return {ok:true,status:200,json:async()=>({url:'wss://api.bot.qq.com/websocket/'})};
      posts.push({url,body:JSON.parse(opts.body)});
      if(mode==='timeout') throw new Error('timeout');
      if(mode==='link-rejected') return {ok:false,status:400,json:async()=>({code:40001,message:'fixture: URL rejected'})};
      const untilAbort=()=>new Promise((resolve,reject)=>{
        if(opts.signal.aborted) reject(new Error('aborted'));
        else opts.signal.addEventListener('abort',()=>reject(new Error('aborted')),{once:true});
      });
      if(mode==='pending-post') return untilAbort();
      if(mode==='pending-json') return {ok:true,status:200,json:untilAbort};
      return {ok:true,status:200,json:async()=>({id:'sent-group-answer'})};
    },
    send:async(url,body)=>{ const p=JSON.parse(body);callbacks.push({url,p});return {status:200,body:JSON.stringify(p.type==='verification'?{challenge:p.challenge}:{})}; }};
  const router=new BridgeRouter(dir,options);
  t.after(async()=>{router.group?.stop();router.qq.stop();await router.group?.receiveTask;await router.qq.receiveTask;fs.rmSync(dir,{recursive:true,force:true});});
  return {dir,router,options,callbacks,posts,tokens, packet:p=>socket.packet(p)};
}
const call=(router,name,args)=>router.rpc('tools/call',{name,arguments:args});
test('group search instructions limit web.run to necessary public keywords',async t=>{
  const f=fixture(t);
  const tools=(await f.router.rpc('tools/list')).tools;
  const instructions=tools.find(tool=>tool.name==='qq_group_get_message').description;
  assert.match(instructions,/explicitly requests search.*web\.run.*public information/);
  assert.match(instructions,/necessary keywords only/);
  assert.match(instructions,/Never submit unrelated messages, member names or IDs, or whole group conversations/);
  assert.match(instructions,/Do not access private data, local files, accounts, or execute code/);
  assert.doesNotMatch(tools.find(tool=>tool.name==='qq_get_message').description,/web\.run/);
});
test('group search instructions require dated source-backed answers within the reply limit',async t=>{
  const f=fixture(t);
  const tools=(await f.router.rpc('tools/list')).tools;
  const instructions=tools.find(tool=>tool.name==='qq_group_get_message').description;
  assert.match(instructions,/1000 characters including accessible source URLs/);
  assert.match(instructions,/explicit location and absolute date/);
  assert.match(instructions,/current observations from forecasts/);
  assert.match(instructions,/Never silently remove sources/);
});
test('group search instructions report blockers without guessing or changing configuration',async t=>{
  const f=fixture(t);
  const tools=(await f.router.rpc('tools/list')).tools;
  const instructions=tools.find(tool=>tool.name==='qq_group_get_message').description;
  assert.match(instructions,/search or approval fails, report the direct blocker/);
  assert.match(instructions,/do not guess or switch providers/);
  assert.match(instructions,/Do not change subscriptions, recipient groups, or group settings/);
  assert.match(instructions,/If QQ rejects a source link, preserve the source and report the send result; do not retry/);
});
test('group subscription is isolated and survives reload',async t=>{
  const f=fixture(t);
  await f.router.rpc('events/subscribe',groupSubscription());
  assert.equal(f.router.status().group.subscription_active,true);
  assert.equal(f.router.status().qq.subscription_active,false);
  const restored=new BridgeRouter(f.dir,f.options);
  assert.equal(restored.status().group.subscription_active,true);
  await assert.rejects(restored.rpc('events/subscribe',{...groupSubscription(),arguments:{channel_id:'qq-test'}}));
  assert.deepEqual((await call(restored,'qq_group_list_pending_messages',{channel_id:'qq-group-test'})).structuredContent.messages,[]);
});

const question={id:'question-1',group_openid:'bound-group',author:{member_openid:'member-one'},timestamp:'2026-10-11T04:00:00Z',content:'What is 17 plus 25?'};
async function prepare(f) {
  await f.router.rpc('events/subscribe',groupSubscription());
  f.router.group.start({expectedText:question.content,timeoutMs:30000});
  await new Promise(r=>setImmediate(r));
}
async function receive(f,data=question,type='GROUP_MESSAGE_CREATE') {
  f.packet({op:0,t:type,d:data}); await new Promise(r=>setImmediate(r));
}
test('group gateway message delivers group event and identity without history',async t=>{
  const f=fixture(t);await prepare(f);await receive(f);
  const events=f.callbacks.filter(c=>c.p.name==='qq.group.message.created');
  assert.equal(events.length,1);
  assert.equal(events[0].url,'https://group.example.com/events');
  const pending=(await call(f.router,'qq_group_list_pending_messages',{channel_id:'qq-group-test'})).structuredContent.messages;
  assert.equal(pending.length,1);
  const m=(await call(f.router,'qq_group_get_message',{message_id:pending[0].message_id})).structuredContent;
  assert.deepEqual(m,{message_id:pending[0].message_id,channel_id:'qq-group-test',text:question.content,created_at:m.created_at,
    qq_message_id:'question-1',group_openid:'bound-group',author:{member_openid:'member-one'},timestamp:'2026-10-11T04:00:00Z'});
  assert.equal(events[0].p.data.message_id,m.message_id);
  assert.equal(f.router.status().qq.messages.length,0);
});
test('group tool sends generated answer only to original group',async t=>{
  const f=fixture(t);await prepare(f);await receive(f);
  const id=(await call(f.router,'qq_group_list_pending_messages',{channel_id:'qq-group-test'})).structuredContent.messages[0].message_id;
  const answer='17 + 25 = 42.';
  const r=await call(f.router,'qq_group_reply_message',{message_id:id,text:answer});
  assert.equal(r.structuredContent.state,'confirmed');
  assert.deepEqual(f.posts,[{url:API+'/v2/groups/bound-group/messages',body:{msg_type:0,content:answer,msg_id:'question-1',msg_seq:1}}]);
  assert.deepEqual((await call(f.router,'qq_group_list_pending_messages',{channel_id:'qq-group-test'})).structuredContent.messages,[]);
  assert.equal(f.router.status().group.replies[0].text,answer);
});
test('public search answer preserves source URL at the length limit and keeps the group subscription',async t=>{
  const f=fixture(t);
  await f.router.rpc('events/subscribe',groupSubscription());
  const subscriptions=f.router.status().group.subscriptions;
  const query='请搜索台北市2026年10月11日天气';
  f.router.group.start({expectedText:query,timeoutMs:30000});
  await new Promise(r=>setImmediate(r));
  await receive(f,{...question,content:query});
  const id=(await call(f.router,'qq_group_list_pending_messages',{channel_id:'qq-group-test'})).structuredContent.messages[0].message_id;
  const summary='离线模拟：台北市，2026-10-11，全天预报；';
  const source='\n来源：https://weather.example.com/taipei?date=2026-10-11&kind=forecast';
  const answer=summary+'测'.repeat(1000-summary.length-source.length)+source;
  const sent=await call(f.router,'qq_group_reply_message',{message_id:id,text:answer});
  assert.equal(sent.structuredContent.state,'confirmed');
  assert.deepEqual(f.posts,[{url:API+'/v2/groups/bound-group/messages',body:{msg_type:0,content:answer,msg_id:'question-1',msg_seq:1}}]);
  assert.deepEqual(f.router.status().group.subscriptions,subscriptions);
  assert.equal(f.router.status().qq.subscription_active,false);
});
test('overlong source-backed answer is rejected intact before QQ send',async t=>{
  const f=fixture(t);await prepare(f);await receive(f);
  const id=f.router.status().group.messages[0].message_id;
  const source='\nhttps://weather.example.com/taipei';
  const answer='测'.repeat(1001-source.length)+source;
  const sent=await call(f.router,'qq_group_reply_message',{message_id:id,text:answer});
  assert.equal(sent.isError,true);
  assert.equal(sent.structuredContent.error,'Reply exceeds 1000 characters');
  assert.deepEqual(f.posts,[]);
  assert.deepEqual(f.router.status().group.replies,[]);
});
test('QQ link rejection retains source and error code without a source-free retry after reload',async t=>{
  const f=fixture(t,'link-rejected');await prepare(f);await receive(f);
  const id=f.router.status().group.messages[0].message_id;
  const answer='离线模拟来源：https://weather.example.com/taipei';
  const args={message_id:id,text:answer};
  const sent=await call(f.router,'qq_group_reply_message',args);
  assert.equal(sent.isError,true);
  assert.equal(sent.structuredContent.state,'rejected');
  assert.equal(sent.structuredContent.http_status,400);
  assert.equal(sent.structuredContent.api_error_code,40001);
  assert.equal(sent.structuredContent.text,answer);
  const restored=new BridgeRouter(f.dir,f.options);
  const retry=await call(restored,'qq_group_reply_message',{message_id:id,text:'删掉来源的回答'});
  assert.equal(retry.isError,true);
  assert.equal(retry.structuredContent.text,answer);
  assert.equal(f.posts.length,1);
  assert.equal(f.posts[0].body.content,answer);
});
test('group run accepts only one matching message in bound group',async t=>{
  const f=fixture(t);await prepare(f);
  await receive(f,{...question,id:'other-text',content:'unrelated conversation'});
  await receive(f,{...question,id:'other-group',group_openid:'other-group'});
  await receive(f,question,'C2C_MESSAGE_CREATE');
  assert.equal(f.router.status().group.messages.length,0);
  await receive(f);await receive(f,{...question,id:'second-question'});
  assert.equal(f.router.status().group.messages.length,1);
  assert.equal(f.callbacks.filter(c=>c.p.name==='qq.group.message.created').length,1);
});
test('group start requires explicit text and bounded timeout before receiving',async t=>{
  const f=fixture(t);await f.router.rpc('events/subscribe',groupSubscription());
  for(const args of [{},{expectedText:'x'},{expectedText:' ',timeoutMs:1000},{expectedText:'x',timeoutMs:600001},{expectedText:'x',timeoutMs:0}]) {
    assert.throws(()=>f.router.group.start(args),/bounded|text/);
  }
  assert.equal(f.router.status().group.receiving,false);
});
test('group run deadline stops receiving and blocks late replies',async t=>{
  const f=fixture(t);await f.router.rpc('events/subscribe',groupSubscription());
  f.router.group.start({expectedText:question.content,timeoutMs:50});
  await new Promise(r=>setImmediate(r));await receive(f);
  const id=f.router.status().group.messages[0].message_id;
  await new Promise(r=>setTimeout(r,80));
  assert.equal(f.router.status().group.enabled,false);
  assert.equal(f.router.status().group.receiving,false);
  assert.equal((await call(f.router,'qq_group_reply_message',{message_id:id,text:'42'})).isError,true);
  assert.equal(f.posts.length,0);
});
test('new group run does not expose or send unanswered messages from prior run',async t=>{
  const f=fixture(t);await prepare(f);await receive(f);
  const id=f.router.status().group.messages[0].message_id;
  f.router.group.stop();await f.router.group.receiveTask;
  f.router.group.start({expectedText:'new question',timeoutMs:30000});await new Promise(r=>setImmediate(r));
  assert.deepEqual((await call(f.router,'qq_group_list_pending_messages',{channel_id:'qq-group-test'})).structuredContent.messages,[]);
  assert.equal((await call(f.router,'qq_group_reply_message',{message_id:id,text:'late answer'})).isError,true);
  assert.equal(f.posts.length,0);
});
test('group subscription binds one callback and rejects a second chat',async t=>{
  const f=fixture(t);await f.router.rpc('events/subscribe',groupSubscription());
  const second=groupSubscription();second.delivery.url='https://second.example.com/events';
  await assert.rejects(f.router.rpc('events/subscribe',second),/bound/);
  const restored=new BridgeRouter(f.dir,f.options);
  await assert.rejects(restored.rpc('events/subscribe',second),/bound/);
  await restored.rpc('events/subscribe',groupSubscription());
  assert.equal(restored.status().group.subscriptions.length,1);
});
test('concurrent group subscriptions retain a single callback binding',async t=>{
  const f=fixture(t);
  const second=groupSubscription();second.delivery.url='https://second.example.com/events';
  const outcomes=await Promise.allSettled([f.router.rpc('events/subscribe',groupSubscription()),f.router.rpc('events/subscribe',second)]);
  assert.equal(outcomes.filter(o=>o.status==='fulfilled').length,1);
  assert.equal(f.router.status().group.subscriptions.length,1);
});
test('group duplicate events and concurrent replies stay single-send after reload',async t=>{
  const f=fixture(t);await prepare(f);await receive(f);await receive(f);
  const id=f.router.status().group.messages[0].message_id;
  const args={message_id:id,text:'42'};
  await Promise.all([call(f.router,'qq_group_reply_message',args),call(f.router,'qq_group_reply_message',args)]);
  const restored=new BridgeRouter(f.dir,f.options);
  assert.equal((await call(restored,'qq_group_reply_message',args)).structuredContent.duplicate,true);
  assert.equal((await call(restored,'qq_group_reply_message',{...args,text:'different'})).isError,true);
  assert.equal(f.posts.length,1);
  assert.equal(f.callbacks.filter(c=>c.p.name==='qq.group.message.created').length,1);
});
test('group unknown send result is retained and never retried after reload',async t=>{
  const f=fixture(t,'timeout');await prepare(f);await receive(f);
  const id=f.router.status().group.messages[0].message_id,args={message_id:id,text:'42'};
  const r=await call(f.router,'qq_group_reply_message',args);
  assert.equal(r.isError,true);assert.equal(r.structuredContent.state,'unknown');
  await call(f.router,'qq_group_reply_message',args);
  const restored=new BridgeRouter(f.dir,f.options);
  assert.equal((await call(restored,'qq_group_reply_message',args)).structuredContent.state,'unknown');
  assert.equal(f.posts.length,1);
});
test('group tools reject destination overrides and private message IDs',async t=>{
  const f=fixture(t);await prepare(f);await receive(f);
  const id=f.router.status().group.messages[0].message_id;
  await assert.rejects(call(f.router,'qq_group_reply_message',{message_id:id,text:'42',group_openid:'other-group'}));
  assert.equal((await call(f.router,'qq_get_message',{message_id:id})).isError,true);
  assert.equal((await call(f.router,'qq_group_get_message',{message_id:'private-id'})).isError,true);
  await assert.rejects(call(f.router,'qq_group_list_pending_messages',{channel_id:'qq-test'}));
  assert.equal(f.posts.length,0);
});
test('group status identifies bounded mode and actual channel',async t=>{
  const f=fixture(t);await f.router.rpc('events/subscribe',groupSubscription());
  const started=f.router.group.start({expectedText:question.content,timeoutMs:30000});
  assert.equal(started.channel_id,'qq-group-test');assert.equal(started.mode,'bounded');
  assert.equal(f.router.status().group.scope,'bound-qq-group-bounded');
  assert.equal(f.router.status().group.run.expected_text,question.content);
  assert.ok(Date.parse(f.router.status().group.run.deadline)>Date.now());
});
async function servers(t,f) {
  const {startServers}=await import('../src/server.mjs');
  const config={dir:f.dir,mcpPort:0,adminPort:0,mcpToken:'mcp-test-token',adminToken:'admin-test-token'};
  const servers=await startServers(config,f.router);
  t.after(()=>servers.close());
  const admin=async(route,body)=>fetch(`http://127.0.0.1:${servers.admin.address().port}${route}`,{
    method:body===undefined?'GET':'POST',headers:{Authorization:'Bearer '+config.adminToken,'Content-Type':'application/json'},
    ...(body===undefined?{}:{body:JSON.stringify(body)})});
  const mcp=async(name,args)=>{
    const response=await fetch(`http://127.0.0.1:${servers.mcp.address().port}/mcp`,{method:'POST',
      headers:{Authorization:'Bearer '+config.mcpToken,'Content-Type':'application/json'},
      body:JSON.stringify({jsonrpc:'2.0',id:'call',method:'tools/call',params:{name,arguments:args}})});
    return (await response.json()).result;
  };
  return {admin,mcp,servers,config};
}
test('admin group start status stop routes control bounded receiver',async t=>{
  const f=fixture(t);await f.router.rpc('events/subscribe',groupSubscription());
  const {admin}=await servers(t,f);
  const start=await admin('/qq/group/start',{expectedText:question.content,timeoutMs:30000});
  assert.equal(start.status,202);assert.equal((await start.json()).channel_id,'qq-group-test');
  assert.equal((await (await admin('/qq/group/status')).json()).enabled,true);
  assert.equal((await admin('/qq/group/stop',{})).status,200);
  await f.router.group.receiveTask;
  assert.equal((await (await admin('/qq/group/status')).json()).receiving,false);
});
test('admin prevents private receiver starting during group run',async t=>{
  const f=fixture(t);await prepare(f);
  const privateSub=groupSubscription();privateSub.name='qq.message.created';privateSub.arguments.channel_id='qq-test';privateSub.delivery.url='https://private.example.com/events';
  await f.router.rpc('events/subscribe',privateSub);
  const {admin}=await servers(t,f);
  const response=await admin('/qq/start',{});
  assert.equal(response.status,400);assert.match((await response.json()).error,/receiver.*running/);
  assert.equal(f.router.status().qq.receiving,false);
});
test('admin prevents group receiver starting during private run',async t=>{
  const f=fixture(t);
  const privateSub=groupSubscription();privateSub.name='qq.message.created';privateSub.arguments.channel_id='qq-test';privateSub.delivery.url='https://private.example.com/events';
  await f.router.rpc('events/subscribe',privateSub);f.router.qq.start();
  await f.router.rpc('events/subscribe',groupSubscription());
  const {admin}=await servers(t,f);
  const response=await admin('/qq/group/start',{expectedText:question.content,timeoutMs:30000});
  assert.equal(response.status,400);assert.match((await response.json()).error,/receiver.*running/);
  assert.equal(f.router.status().group.receiving,false);
});
test('MCP HTTP calls are distinguishable from local diagnostics',async t=>{
  const f=fixture(t);await prepare(f);await receive(f);
  const id=f.router.status().group.messages[0].message_id;
  await call(f.router,'qq_group_get_message',{message_id:id});
  const {servers:running,config}=await servers(t,f);
  const response=await fetch(`http://127.0.0.1:${running.mcp.address().port}/mcp`,{method:'POST',
    headers:{Authorization:'Bearer '+config.mcpToken,'Content-Type':'application/json'},
    body:JSON.stringify({jsonrpc:'2.0',id:'read-1',method:'tools/call',params:{name:'qq_group_get_message',arguments:{message_id:id}}})});
  assert.equal((await response.json()).result.structuredContent.qq_message_id,'question-1');
  const calls=f.router.status().group.calls.filter(c=>c.tool==='qq_group_get_message');
  assert.deepEqual(calls.map(c=>c.source),['local-diagnostic','mcp-http']);
});
test('persisted group mapping rejects a changed group binding',async t=>{
  const f=fixture(t);await f.router.rpc('events/subscribe',groupSubscription());
  fs.writeFileSync(path.join(f.dir,'qq-group-receive/test-group.json'),JSON.stringify({group_openid:'changed-group'}));
  const restored=new BridgeRouter(f.dir,f.options);
  try {
    assert.throws(()=>restored.group.start({expectedText:question.content,timeoutMs:30000}),/binding/);
    assert.equal(restored.status().group.receiving,false);
  } finally { restored.group.stop(); await restored.group.receiveTask; }
});
test('changing group binding during a run cannot reroute new messages',async t=>{
  const f=fixture(t);await prepare(f);
  fs.writeFileSync(path.join(f.dir,'qq-group-receive/test-group.json'),JSON.stringify({group_openid:'different-group'}));
  await receive(f,{...question,group_openid:'different-group'});
  assert.equal(f.router.status().group.messages.length,0);
});
test('discovery instructions distinguish group and private tool routes',async t=>{
  const f=fixture(t);
  for(const method of ['initialize','server/discover']) {
    const {instructions}=await f.router.rpc(method);
    assert.match(instructions,/qq_group_.*qq-group-test/);
    assert.match(instructions,/qq-test/);
  }
});
test('partial group start request cannot race private receiver start',async t=>{
  const f=fixture(t);await f.router.rpc('events/subscribe',groupSubscription());
  const privateSub=groupSubscription();privateSub.name='qq.message.created';privateSub.arguments.channel_id='qq-test';
  await f.router.rpc('events/subscribe',privateSub);
  const {admin,servers:running,config}=await servers(t,f);
  let request;
  const pending=new Promise((resolve,reject)=>{
    request=http.request({host:'127.0.0.1',port:running.admin.address().port,path:'/qq/group/start',method:'POST',
      headers:{Authorization:'Bearer '+config.adminToken,'Content-Type':'application/json'}},res=>{
      let body='';res.on('data',c=>body+=c);res.on('end',()=>resolve({status:res.statusCode,body}));
    });request.on('error',reject);request.write('{');
  });
  await new Promise(r=>setTimeout(r,30));
  assert.equal((await admin('/qq/start',{})).status,202);
  request.end(JSON.stringify({expectedText:question.content,timeoutMs:30000}).slice(1));
  const group=await pending;
  assert.equal(group.status,400);
  assert.equal(f.router.status().group.receiving,false);
  assert.equal(f.router.status().qq.receiving,true);
});
async function waitFor(predicate) {
  for(let i=0;i<200;i++){if(predicate())return;await new Promise(r=>setTimeout(r,5));}
  assert.fail('Expected observable state was not reached');
}

test('two sequential group events expose only the current question and reply to the original group',async t=>{
  const f=fixture(t);
  await f.router.rpc('events/subscribe',groupSubscription());
  const {admin,mcp}=await servers(t,f);
  const questions=[
    {...question,id:'context-1',content:'请记住本群代号：蓝杉-731。'},
    {...question,id:'context-2',content:'刚才的本群代号是什么？',author:{member_openid:'member-two'},timestamp:'2026-10-11T04:01:00Z'}
  ];
  // These are transport inputs, not generated dot answers or a memory assertion.
  const answers=['第一轮传输回答','第二轮传输回答'];
  const ids=[];
  for(const [index,q] of questions.entries()) {
    const started=await admin('/qq/group/start',{expectedText:q.content,timeoutMs:30000});
    assert.equal(started.status,202);
    await waitFor(()=>f.router.status().group.receiver?.stage==='heartbeat_ack');
    const pending=async()=> (await mcp('qq_group_list_pending_messages',{channel_id:'qq-group-test'})).structuredContent.messages;
    assert.deepEqual(await pending(),[]);
    await receive(f,{...q,id:'foreign-'+index,group_openid:'other-group'});
    await receive(f,{...q,id:'private-'+index},'C2C_MESSAGE_CREATE');
    if(index===1) await receive(f,questions[0]);
    assert.deepEqual(await pending(),[]);
    await receive(f,q);
    await waitFor(()=>f.router.status().group.deliveries.length===index+1);
    const listed=await pending();
    assert.equal(listed.length,1);
    const id=listed[0].message_id;ids.push(id);
    const read=await mcp('qq_group_get_message',{message_id:id});
    assert.deepEqual(read.structuredContent,{
      message_id:id,channel_id:'qq-group-test',text:q.content,created_at:read.structuredContent.created_at,
      qq_message_id:q.id,group_openid:'bound-group',author:q.author,timestamp:q.timestamp
    });
    assert.deepEqual(JSON.parse(read.content[0].text),read.structuredContent);
    const sent=await mcp('qq_group_reply_message',{message_id:id,text:answers[index]});
    assert.equal(sent.structuredContent.state,'confirmed');
    assert.deepEqual(await pending(),[]);
    assert.equal((await admin('/qq/group/stop',{})).status,200);
    await waitFor(()=>!f.router.status().group.receiving);
  }
  assert.notEqual(ids[0],ids[1]);
  const events=f.callbacks.filter(c=>c.p.name==='qq.group.message.created');
  assert.equal(events.length,2);
  assert.notEqual(events[0].p.eventId,events[1].p.eventId);
  assert.deepEqual(events.map(c=>({url:c.url,data:c.p.data})),questions.map((q,i)=>({
    url:'https://group.example.com/events',data:{channel_id:'qq-group-test',message_id:ids[i],text:q.content}
  })));
  assert.deepEqual(f.posts,questions.map((q,i)=>({url:API+'/v2/groups/bound-group/messages',
    body:{msg_type:0,content:answers[i],msg_id:q.id,msg_seq:1}})));
  const status=f.router.status();
  assert.deepEqual(status.group.calls.filter(c=>c.tool==='qq_group_get_message').map(c=>({id:c.message_id,source:c.source})),
    ids.map(id=>({id,source:'mcp-http'})));
  assert.equal(status.group.subscriptions.length,1);
  assert.ok(status.group.deliveries.every(d=>d.accepted && d.subscription_id===status.group.subscriptions[0].id));
  assert.equal(status.qq.messages.length,0);
  assert.equal(status.qq.calls.filter(c=>c.method==='tools/call').length,0);
});
test('failed group run timer does not stop its replacement',async t=>{
  const f=fixture(t),router=f.router;
  await router.rpc('events/subscribe',groupSubscription());
  const {admin}=await servers(t,f);
  await admin('/qq/group/start',{expectedText:question.content,timeoutMs:300});
  await waitFor(()=>router.status().group.receiver?.stage==='heartbeat_ack');
  const file=path.join(f.dir,'qq-group-receive/test-group.json');
  fs.renameSync(file,file+'.parked');f.packet({op:7});
  await waitFor(()=>!router.status().group.receiving);
  fs.renameSync(file+'.parked',file);
  await admin('/qq/group/start',{expectedText:question.content,timeoutMs:900});
  await new Promise(r=>setTimeout(r,350));
  assert.equal(router.status().group.enabled,true);
  assert.equal(router.status().group.receiving,true);
  await receive(f);assert.equal(router.status().group.messages.length,1);
  await waitFor(()=>!router.status().group.receiving);
});
test('group reconnect rejects another bot before token acquisition',async t=>{
  const f=fixture(t);await prepare(f);await receive(f);
  const file=path.join(f.dir,'qq-auth/config.json');
  fs.writeFileSync(file,JSON.stringify({appId:'98765',appSecret:'other-secret'}));
  f.packet({op:7});
  await waitFor(()=>!f.router.status().group.receiving || f.tokens.includes('98765'));
  assert.equal(f.router.status().group.receiving,false);
  assert.deepEqual(f.tokens,['12345']);
  fs.writeFileSync(file,JSON.stringify({appId:'12345',appSecret:'secret'}));
  const id=f.router.status().group.messages[0].message_id;
  assert.equal((await call(f.router,'qq_group_reply_message',{message_id:id,text:'42'})).isError,true);
  assert.equal(f.posts.length,0);
});
test('admin stop aborts pending group POST and preserves one send across reload',async t=>{
  const f=fixture(t,'pending-post');await prepare(f);await receive(f);
  const {admin,mcp}=await servers(t,f);
  const args={message_id:f.router.status().group.messages[0].message_id,text:'42'};
  const pending=mcp('qq_group_reply_message',args);
  await waitFor(()=>f.posts.length===1);
  const reserved=new BridgeRouter(f.dir,f.options);
  const duplicate=await call(reserved,'qq_group_reply_message',args);
  assert.equal(duplicate.structuredContent.state,'reserved');assert.equal(duplicate.isError,true);
  assert.equal((await call(reserved,'qq_group_reply_message',{...args,text:'different'})).isError,true);
  await admin('/qq/group/stop',{});
  const outcome=await pending;assert.equal(outcome.structuredContent.state,'unknown');
  const reloaded=new BridgeRouter(f.dir,f.options);
  assert.equal((await call(reloaded,'qq_group_reply_message',args)).structuredContent.state,'unknown');
  assert.equal(reloaded.status().group.replies[0].attempts,1);assert.equal(f.posts.length,1);
});
test('group deadline aborts pending response JSON without resending',async t=>{
  const f=fixture(t,'pending-json');await f.router.rpc('events/subscribe',groupSubscription());
  const {admin,mcp}=await servers(t,f);
  await admin('/qq/group/start',{expectedText:question.content,timeoutMs:200});await receive(f);
  const args={message_id:f.router.status().group.messages[0].message_id,text:'42'};
  const pending=mcp('qq_group_reply_message',args);
  await waitFor(()=>f.posts.length===1);
  const outcome=await pending;
  assert.equal(outcome.isError,true);assert.equal(outcome.structuredContent.state,'unknown');
  assert.equal(outcome.structuredContent.http_status,200);
  const reloaded=new BridgeRouter(f.dir,f.options);
  assert.equal((await call(reloaded,'qq_group_reply_message',args)).structuredContent.state,'unknown');
  assert.equal((await call(reloaded,'qq_group_reply_message',{...args,text:'different'})).isError,true);
  assert.equal(reloaded.status().group.replies[0].attempts,1);assert.equal(f.posts.length,1);
});

test('group timing exposes delivery start and successful MCP read without diagnostic contamination', async t => {
  const f=fixture(t); await prepare(f); await receive(f);
  await waitFor(()=>f.router.status().group.deliveries.length===1);
  const id=f.router.status().group.messages[0].message_id;
  await call(f.router,'qq_group_get_message',{message_id:id});
  const {mcp}=await servers(t,f);
  await mcp('qq_group_get_message',{message_id:id});
  await mcp('qq_group_reply_message',{message_id:id,text:'42'});
  const status=f.router.status().group;
  assert.ok(Number.isFinite(Date.parse(status.deliveries[0].started_at)));
  assert.ok(Date.parse(status.deliveries[0].started_at)<=Date.parse(status.deliveries[0].at));
  assert.equal(status.calls.filter(c=>c.read_succeeded && c.source==='mcp-http').length,1);
  assert.ok(Date.parse(status.replies[0].finished_at)>=Date.parse(status.replies[0].at));
});
