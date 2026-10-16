import {inflateRawSync} from 'node:zlib';
import {XMLParser,XMLValidator} from 'fast-xml-parser';
import {fetchWithoutWBI,throttledFetch} from '@xzxzzx/bilibili-mcp/dist/bilibili/http.js';
import {credentialManager} from '@xzxzzx/bilibili-mcp/dist/utils/credentials.js';
import {config} from '@xzxzzx/bilibili-mcp/dist/config.js';

export const danmakuSchema={name:'get_video_danmaku',description:'Read a bounded sample from the current Bilibili danmaku pool, tied to BV, part and video timestamps. Not all historical danmaku. Audience comments are interpretation, not subtitles. No ASR.',annotations:{readOnlyHint:true,destructiveHint:false,openWorldHint:true},inputSchema:{type:'object',properties:{bvid_or_url:{type:'string'},page:{type:'integer',minimum:1},limit:{type:'integer',minimum:1,maximum:200,default:80},start_seconds:{type:'number',minimum:0},end_seconds:{type:'number',minimum:0}},required:['bvid_or_url'],additionalProperties:false}};
const fail=code=>Object.assign(new Error(code),{code});
const MAX_WIRE=2*1024*1024,MAX_XML=8*1024*1024;
async function readPool(cid){
 return throttledFetch(async controller=>{
  const r=await fetch(`https://api.bilibili.com/x/v1/dm/list.so?oid=${cid}`,{headers:{'User-Agent':config.userAgent,Referer:config.referer,...credentialManager.getAuthHeaders()},redirect:'error',signal:controller.signal});
  if(!r.ok)throw fail(r.status===412?'RISK_CONTROL':r.status===403?'ACCESS_DENIED':`DANMAKU_HTTP_${r.status}`);
  if(Number(r.headers.get('content-length'))>MAX_WIRE)throw fail('DANMAKU_SIZE_LIMIT');
  const chunks=[];let bytes=0;
  if(!r.body)throw fail('DANMAKU_INVALID_RESPONSE');
  for await(const c of r.body){bytes+=c.length;if(bytes>MAX_WIRE)throw fail('DANMAKU_SIZE_LIMIT');chunks.push(c);}
  let b=Buffer.concat(chunks);
  if(!b.toString('utf8',0,100).trimStart().startsWith('<')){
   if(b.toString('utf8',0,100).trimStart().startsWith('{')){
    const code=JSON.parse(b.toString()).code;
    throw fail(code===-101?'COOKIE_EXPIRED':code===-403?'ACCESS_DENIED':code===-412?'RISK_CONTROL':'DANMAKU_INVALID_RESPONSE');
   }
   try{b=inflateRawSync(b,{maxOutputLength:MAX_XML});}catch{throw fail('DANMAKU_INVALID_RESPONSE');}
  }
  if(b.length>MAX_XML)throw fail('DANMAKU_SIZE_LIMIT');
  return b.toString('utf8');
 });
}
export async function readDanmaku(args){
 const limit=args.limit??80,start=args.start_seconds??0,end=args.end_seconds??Infinity;
 if(!Number.isInteger(limit)||limit<1||limit>200||!Number.isFinite(start)||start<0||!(end===Infinity||Number.isFinite(end))||end<start)throw fail('INVALID_DANMAKU_ARGUMENT');
 const value=String(args.bvid_or_url??'');let bvid=value,page=args.page??1;
 if(!/^BV[\da-zA-Z]{10}$/.test(value)){
  let u;try{u=new URL(value);}catch{throw fail('INVALID_BILIBILI_VIDEO');}
  if(!['https:','http:'].includes(u.protocol)||!['www.bilibili.com','bilibili.com','m.bilibili.com'].includes(u.hostname))throw fail('INVALID_BILIBILI_VIDEO');
  bvid=u.pathname.match(/^\/video\/(BV[\da-zA-Z]{10})\/?$/)?.[1];
  const urlPage=u.searchParams.get('p');
  if(urlPage && args.page!==undefined && Number(urlPage)!==args.page)throw fail('VIDEO_PART_CONFLICT');
  page=args.page??Number(urlPage??1);
 }
 if(!bvid||!Number.isInteger(page)||page<1)throw fail('INVALID_BILIBILI_VIDEO');
 const view=await fetchWithoutWBI('/x/web-interface/view',{bvid});
 if(view.bvid!==bvid)throw fail('BV_MISMATCH');
 const part=view.pages?.find(x=>x.page===page);
 if(!Number.isSafeInteger(part?.cid)||part.cid<1)throw fail('VIDEO_PART_NOT_FOUND');
 const xml=await readPool(part.cid);
 if(/<!DOCTYPE|<!ENTITY/i.test(xml)||XMLValidator.validate(xml)!==true)throw fail('DANMAKU_INVALID_RESPONSE');
 const parsed=new XMLParser({ignoreAttributes:false,parseTagValue:false,parseAttributeValue:false,isArray:name=>name==='d'}).parse(xml);
 if(!parsed.i || Number(parsed.i.chatid)!==part.cid)throw fail('DANMAKU_CID_MISMATCH');
 const pool=(parsed.i.d??[]).map(d=>({at_seconds:Number(String(d['@_p']??'').split(',')[0]),text:String(d['#text']??'')}));
 if(pool.some(x=>!Number.isFinite(x.at_seconds)||x.at_seconds<0||!x.text))throw fail('DANMAKU_INVALID_RESPONSE');
 const filtered=pool.filter(x=>x.at_seconds>=start&&x.at_seconds<=end).sort((a,b)=>a.at_seconds-b.at_seconds);
 // Spread a limited sample across the requested window rather than keeping only the opening.
 const items=filtered.length<=limit?filtered:Array.from({length:limit},(_,i)=>filtered[limit===1?0:Math.floor(i*(filtered.length-1)/(limit-1))]);
 return {bvid,page,cid:part.cid,source_url:`https://www.bilibili.com/video/${bvid}/?p=${page}`,items,pool_size:pool.length,available_in_window:filtered.length,truncated:filtered.length>limit,window:{start_seconds:start,end_seconds:Number.isFinite(end)?end:null},coverage:'current_pool_not_full_history'};
}
