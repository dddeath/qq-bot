import {checkArguments,argumentError} from './argument-errors.mjs';
import {credentialManager} from '@xzxzzx/bilibili-mcp/dist/utils/credentials.js';
const fail=argumentError;
export const articleSchema={
  "name": "get_bilibili_article",
  "description": "Read a bounded page of an article body. opus_id is the numeric ID in /opus/ URLs. start is a zero-based paragraph offset, not a time; count is 1–40 (default 20). Follow next_start for more. Returns concise text, paragraph positions, image references and coverage. Original structure is saved to evidence. Images have NOT been visually read.",
  "annotations": {
    "readOnlyHint": true,
    "destructiveHint": false,
    "openWorldHint": true
  },
  "inputSchema": {
    "type": "object",
    "properties": {
      "opus_id": {
        "type": "string",
        "pattern": "^[1-9][0-9]{0,24}$",
        "description": "Numeric opus identifier from /opus/<id> or a creator dynamic result; not a BV or cv identifier."
      },
      "start": {
        "type": "integer",
        "minimum": 0,
        "default": 0,
        "description": "Zero-based paragraph offset in the article body; use the returned continuation to expand more paragraphs."
      },
      "count": {
        "type": "integer",
        "minimum": 1,
        "maximum": 40,
        "default": 20,
        "description": "Maximum article paragraphs to read, 1–40. Image references are not pixel observations."
      }
    },
    "required": [
      "opus_id"
    ],
    "additionalProperties": false
  }
};

async function fetchPage(url){
 const response=await fetch(url,{headers:credentialManager.getAuthHeaders(),redirect:'error',signal:AbortSignal.timeout(20000)});
 if(!response.ok)throw fail('ARTICLE_HTTP_'+response.status);
 const reader=response.body.getReader();let total=0,chunks=[];
 while(true){const {done,value}=await reader.read();if(done)break;total+=value.length;if(total>2097152){await reader.cancel();throw fail('ARTICLE_SIZE_LIMIT');}chunks.push(value);}
 return Buffer.concat(chunks).toString('utf8');
}
function readState(html){
 const marker='window.__INITIAL_STATE__=';let start=html.indexOf(marker);if(start<0)throw fail('ARTICLE_STATE_MISSING');start+=marker.length;
 while(start<html.length&&/\s/.test(html[start]))start++;
 if(html[start]!=='{')throw fail('ARTICLE_STATE_INVALID');let depth=0,string=false,escape=false;
 for(let i=start;i<html.length;i++){const c=html[i];if(string){if(escape)escape=false;else if(c==='\\')escape=true;else if(c==='"')string=false;continue;}if(c==='"')string=true;else if(c==='{')depth++;else if(c==='}'&&--depth===0){try{return JSON.parse(html.slice(start,i+1));}catch{throw fail('ARTICLE_STATE_INVALID');}}}
 throw fail('ARTICLE_STATE_INVALID');
}
export async function readArticle(args,load=fetchPage){
 const {opus_id,start=0,count=20}=args;
 checkArguments('INVALID_ARTICLE_ARGUMENT',[
 ['arguments',!Object.keys(args).some(k=>!['opus_id','start','count'].includes(k)),'Only opus_id, start and count are accepted.'],
 ['opus_id',typeof opus_id==='string'&&/^[1-9][0-9]{0,24}$/.test(opus_id),'Numeric opus ID string from /opus/<id>.'],
 ['start',Number.isSafeInteger(start)&&start>=0,'Expected nonnegative paragraph offset.'],['count',Number.isInteger(count)&&count>=1&&count<=40,'Expected integer 1–40.']]);
 const source_url='https://www.bilibili.com/opus/'+opus_id;const html=await load(source_url);if(Buffer.byteLength(html)>2097152)throw fail('ARTICLE_SIZE_LIMIT');const state=readState(html);
 if(String(state.id)!==opus_id)throw fail('ARTICLE_ID_MISMATCH');
 if(!Array.isArray(state.detail?.modules))throw fail('ARTICLE_STATE_INVALID');
 const bodies=state.detail.modules.filter(m=>m.module_type==='MODULE_TYPE_CONTENT'&&Array.isArray(m.module_content?.paragraphs));if(!bodies.length)throw fail('ARTICLE_BODY_MISSING');
 const all=bodies.flatMap(m=>m.module_content.paragraphs);const paragraphs=all.slice(start,start+count).map((data,i)=>({index:start+i,data}));
 const images=paragraphs.flatMap(p=>(p.data.pic?.pics??[]).map(im=>({...im,paragraph_index:p.index,visual_read_completed:false})));
 const next=start+paragraphs.length<all.length?start+paragraphs.length:null;
 return {opus_id,source_url,title:state.detail.basic?.title??null,start,count,total_paragraphs:all.length,paragraphs,images,next_start:next,coverage:{body_complete:start===0&&next===null,visual_read_completed:false,all_semantic_content_read:false}};
}
