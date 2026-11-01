import {checkArguments,argumentError} from './argument-errors.mjs';
import {fork} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {load} from 'cheerio';
import {mkdir,writeFile} from 'node:fs/promises';
import {join} from 'node:path';
import {tmpdir} from 'node:os';
import {randomUUID} from 'node:crypto';
const fail=argumentError;
export const rssSchema={
  "name": "read_rss_subscription",
  "description": "Read a Bilibili UP RSS directory using the existing Bilibili credentials. uid is a numeric account ID; lookback_days defaults to 7 (1–30), start is a zero-based item offset, count is 1–20. Returns titles, feed text, paragraph positions, image references and article/video links. Follow next_start for more returned items; RSS is a bounded recent feed, not complete account history. Article bodies require get_bilibili_article; image references have NOT been visually read.",
  "annotations": {
    "readOnlyHint": true,
    "destructiveHint": false,
    "openWorldHint": true
  },
  "inputSchema": {
    "type": "object",
    "properties": {
      "uid": {
        "type": "string",
        "pattern": "^[1-9][0-9]{0,19}$",
        "description": "Bilibili creator UID as a decimal string, from the creator directory/search result."
      },
      "lookback_days": {
        "type": "integer",
        "minimum": 1,
        "maximum": 30,
        "default": 7,
        "description": "Keep items published within this many days, 1–30. Result reports route/coverage status."
      },
      "start": {
        "type": "integer",
        "minimum": 0,
        "default": 0,
        "description": "Zero-based item offset in the filtered RSS result."
      },
      "count": {
        "type": "integer",
        "minimum": 1,
        "maximum": 20,
        "default": 20,
        "description": "Maximum RSS items in this page, 1–20."
      }
    },
    "required": [
      "uid"
    ],
    "additionalProperties": false
  }
};
export async function fetchFeed(uid){
 return new Promise((resolve,reject)=>{
  const child=fork(fileURLToPath(new URL('./rsshub-worker.mjs',import.meta.url)),[],{stdio:['ignore','ignore','ignore','ipc']});
  let done=false;const end=(error,value)=>{if(done)return;done=true;clearTimeout(timer);child.kill('SIGKILL');error?reject(error):resolve(value);};
  const timer=setTimeout(()=>end(fail('RSS_TIMEOUT')),70000);
  child.once('error',()=>end(fail('RSS_WORKER_FAILED')));child.once('exit',()=>end(fail('RSS_WORKER_EXITED')));
  child.once('message',result=>{
   if(result.status!=='completed')return end(fail(result.error==='RSS_CREDENTIAL_MISSING'?'RSS_CREDENTIAL_MISSING':result.error==='RSS_TIMEOUT'?'RSS_TIMEOUT':'RSS_REQUEST_FAILED'));
   if(Buffer.byteLength(JSON.stringify(result.feed))>2097152)return end(fail('RSS_SIZE_LIMIT'));
   end(null,result.feed);
  });child.send({uid});
 });
}
function itemView(row){
 const url=row.link??'',id=url.match(/(?:t\.bilibili\.com\/|\/opus\/)(\d+)/)?.[1];if(!id)return null;
 const $=load(row.description??'');$('script,style').remove();$('br').replaceWith('\n');
 const links=$('a[href]').map((_,el)=>({title:$(el).text(),url:$(el).attr('href')})).get();
 const text=$.root().text().trim();const images=$('img[src]').map((i,el)=>({id:`image${i}`,url:$(el).attr('src')})).get();
 const bv=text.includes('视频地址')?links.map(x=>x.url.match(/BV[a-zA-Z0-9]{10}/)?.[0]).find(Boolean):null;
 const article=text.includes('专栏地址')?links.map(x=>x.url.match(/\/opus\/(\d+)/)?.[1]).find(Boolean):null;
 const stamp=Date.parse(row.pubDate);const title=row.title??'';
 return {dynamic_id:id,title,published_at:Number.isFinite(stamp)?new Date(stamp).toISOString():null,type:bv?'video':article?'article':'dynamic',text,paragraphs:text.split(/\n+/).filter(Boolean).map((text,index)=>({index,text})),images,links,source_url:url,...(bv?{referenced_bvids:[bv],bvid:bv}:{}),...(article&&!bv?{opus_id:article}:{}),coverage:{body_complete:false,visual_read_completed:false,scope:'feed_content'}};
}
export async function readRss(args,getFeed=fetchFeed){
 const {uid,lookback_days=7,start=0,count=20}=args;
 checkArguments('INVALID_RSS_ARGUMENT',[
 ['arguments',!Object.keys(args).some(k=>!['uid','lookback_days','start','count'].includes(k)),'Only uid, lookback_days, start and count are accepted.'],
 ['uid',typeof uid==='string'&&/^[1-9][0-9]{0,19}$/.test(uid),'Positive numeric UID string.'],
 ['lookback_days',Number.isInteger(lookback_days)&&lookback_days>=1&&lookback_days<=30,'Expected integer 1–30.'],
 ['start',Number.isSafeInteger(start)&&start>=0,'Expected nonnegative item offset.'],['count',Number.isInteger(count)&&count>=1&&count<=20,'Expected integer 1–20.']]);
 const feed=await getFeed(uid);if(!Array.isArray(feed.item))throw fail('RSS_INVALID_FEED');
 const now=Date.now(),cutoff=now-lookback_days*86400000,parsed=feed.item.map(itemView),missing=parsed.filter(x=>!x||!x.published_at).length;
 const rows=parsed.filter(x=>x?.published_at&&Date.parse(x.published_at)>=cutoff&&Date.parse(x.published_at)<=now).sort((a,b)=>Date.parse(b.published_at)-Date.parse(a.published_at));
 const items=rows.slice(start,start+count),callId=randomUUID();let evidence;
 try{const directory=process.env.QQ_BILIBILI_EVIDENCE??join(tmpdir(),'qq-bilibili-rss-evidence');await mkdir(directory,{recursive:true});const path=join(directory,callId+'.rss-raw.json');await writeFile(path,JSON.stringify({uid,feed}),{flag:'wx'});evidence={stored:true,id:callId,path};}catch{evidence={stored:false,error:'RSS_EVIDENCE_WRITE_FAILED'};}
 return {uid,source_url:`https://space.bilibili.com/${uid}/dynamic`,items,start,count,total_in_window:rows.length,next_start:start+items.length<rows.length?start+items.length:null,coverage:{history_complete:false,scope:'returned_feed_window',feed_items:feed.item.length,missing_identity_or_time:missing,visual_read_completed:false,window_start:new Date(cutoff).toISOString(),window_end:new Date(now).toISOString()},evidence};
}
