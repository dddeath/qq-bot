import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';

// Only the external HTTP service and its public credentials are substituted.
process.env.BILIBILI_SESSDATA='fixture-session';
process.env.BILIBILI_BILI_JCT='fixture-csrf';
process.env.BILIBILI_DEDEUSERID='42';
process.env.BILIBILI_RATE_LIMIT_MS='1';
const {handleToolCall}=await import('@xzxzzx/bilibili-mcp/dist/server/tool-handlers.js');
const response=data=>new Response(JSON.stringify(data),{headers:{'content-type':'application/json'}});
const mix='ea1db124af3c7062474693fa704f4ff8'; // Published community test vector.
test('video metadata uses configured login instead of an anonymous request rejected with 412',async()=>{
  const original=globalThis.fetch;
  globalThis.fetch=async(input,options)=>{
    const u=new URL(input);assert.equal(u.pathname,'/x/web-interface/view');
    if(!new Headers(options.headers).get('cookie')?.includes('SESSDATA=fixture-session')) return new Response(JSON.stringify({code:-412}),{status:412});
    return response({code:0,data:{bvid:'BV1234567890',aid:1,cid:2,title:'Fixture metadata',duration:90,pages:[{cid:2,page:1,part:'P1',duration:90}],owner:{name:'Fixture'},stat:{}}});
  };
  try{
    const r=await handleToolCall('get_video_metadata',{bvid_or_url:'BV1234567890'});
    const data=r.structuredContent??JSON.parse(r.content[0].text);
    assert.equal(data.title,'Fixture metadata');assert.equal(data.pages[0].cid,2);
  }finally{globalThis.fetch=original;}
});
test('WBI signs the same normalized Chinese and reserved characters that are sent',async()=>{
  const {fetchWithWBI}=await import('@xzxzzx/bilibili-mcp/dist/bilibili/http.js');
  const original=globalThis.fetch;
  globalThis.fetch=async(input)=>{
    const u=new URL(input);
    if(u.pathname==='/x/web-interface/nav') return response({code:0,data:{wbi_img:{img_url:'https://i0.hdslb.com/bfs/wbi/7cd084941338484aae1ad9425b84077c.png',sub_url:'https://i0.hdslb.com/bfs/wbi/4932caff0ff746eab6f01bf08b70ac45.png'}}});
    assert.equal(u.searchParams.get('keyword'),'明日 方舟&+%');
    const query=`keyword=%E6%98%8E%E6%97%A5%20%E6%96%B9%E8%88%9F%26%2B%25&wts=${u.searchParams.get('wts')}`;
    assert.equal(u.searchParams.get('w_rid'),createHash('md5').update(query+mix).digest('hex'));
    return response({code:0,data:{accepted:true}});
  };
  try{assert.deepEqual(await fetchWithWBI('/x/space/wbi/arc/search',{keyword:"明日 方舟&+%!'()*"}),{accepted:true});}
  finally{globalThis.fetch=original;}
});

test('creator read signs the request using the documented 32-character key and wts',async()=>{
  const original=globalThis.fetch;
  globalThis.fetch=async(input)=>{
    const u=new URL(input);
    if(u.pathname==='/x/web-interface/nav') return response({code:0,data:{isLogin:true,wbi_img:{img_url:'https://i0.hdslb.com/bfs/wbi/7cd084941338484aae1ad9425b84077c.png',sub_url:'https://i0.hdslb.com/bfs/wbi/4932caff0ff746eab6f01bf08b70ac45.png'}}});
    assert.equal(u.pathname,'/x/space/wbi/acc/info');
    assert.ok(u.searchParams.has('wts'),'wts_required');
    const query=`mid=4168597&wts=${u.searchParams.get('wts')}`;
    const expected=createHash('md5').update(query+mix).digest('hex');
    if(u.searchParams.get('w_rid')!==expected) return response({code:-403,message:'signature rejected'});
    return response({code:0,data:{mid:4168597,name:'ZipZipPipe',sign:'作者简介',level:6,videos:12}});
  };
  try {
    const r=await handleToolCall('get_bilibili_creator_content',{mid:4168597,section:'overview'});
    const data=r.structuredContent??JSON.parse(r.content[0].text);
    assert.equal(data.name,'ZipZipPipe');assert.equal(data.video_count,12);
  }finally{globalThis.fetch=original;}
});
