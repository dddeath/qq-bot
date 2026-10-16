import {fetchWithoutWBI} from '@xzxzzx/bilibili-mcp/dist/bilibili/http.js';

export const commentThreadsSchema={name:'get_video_comment_threads',description:'Read one bounded page of original comments or replies to a root comment. Preserve reply targets and emoji. Keep page_size unchanged when following next_page. Comments cover the whole BV, not one part.',annotations:{readOnlyHint:true,destructiveHint:false,openWorldHint:true},inputSchema:{type:'object',properties:{bvid_or_url:{type:'string'},root_id:{type:'string',pattern:'^[1-9][0-9]*$'},page:{type:'integer',minimum:1,maximum:100,default:1},page_size:{type:'integer',minimum:1,maximum:20,default:10},sort:{type:'string',enum:['hot','time'],default:'hot'}},required:['bvid_or_url'],additionalProperties:false}};
const fail=code=>Object.assign(new Error(code),{code});
function id(v,key){const s=v[key+'_str'];if(typeof s==='string'&&/^\d+$/.test(s))return s;if(Number.isSafeInteger(v[key])&&v[key]>=0)return String(v[key]);return null;}
export async function readCommentThreads(args,api=fetchWithoutWBI){
 let bv=String(args.bvid_or_url??'');
 if(!/^BV[a-zA-Z0-9]{10}$/.test(bv)){
  let u;try{u=new URL(bv);}catch{throw fail('INVALID_COMMENT_ARGUMENT');}
  if(!['https:','http:'].includes(u.protocol)||!['www.bilibili.com','bilibili.com','m.bilibili.com'].includes(u.hostname))throw fail('INVALID_COMMENT_ARGUMENT');
  bv=u.pathname.match(/^\/video\/(BV[a-zA-Z0-9]{10})\/?$/)?.[1];
 }
 const page=args.page??1,size=args.page_size??10,root=args.root_id,sort=args.sort??'hot';
 if(!bv||!Number.isInteger(page)||page<1||page>100||!Number.isInteger(size)||size<1||size>20||!['hot','time'].includes(sort)||(root!==undefined&&!/^[1-9]\d*$/.test(root)))throw fail('INVALID_COMMENT_ARGUMENT');
 const view=await api('/x/web-interface/view',{bvid:bv});
 if(view.bvid!==bv||!Number.isSafeInteger(view.aid))throw fail('COMMENT_VIDEO_MISMATCH');
 const data=await api(root?'/x/v2/reply/reply':'/x/v2/reply',{type:1,oid:view.aid,pn:page,ps:size,...(root?{root}:{sort:sort==='hot'?2:0})});
 if(!Array.isArray(data.replies)&&data.replies!==null)throw fail('INVALID_COMMENT_RESPONSE');
 function normalize(v,isRoot=false){
  const rid=id(v,'rpid');if(!rid||typeof v.content?.message!=='string')throw fail('INVALID_COMMENT_RESPONSE');
  if(v.content.message.length>16000)throw fail('COMMENT_TEXT_LIMIT');
  return {id:rid,root_id:(id(v,'root') && id(v,'root')!=='0')?id(v,'root'):((isRoot||!root)?rid:root),parent_id:id(v,'parent'),
   author:{id:String(v.member?.mid??''),name:v.member?.uname??''},is_uploader:String(v.member?.mid)===String(view.owner?.mid),
   text:v.content.message,at:v.ctime??null,likes:v.like??null,reply_count:v.rcount??v.count??null};
 }
 const items=(data.replies??[]).slice(0,size).map(v=>normalize(v));
 const count=Number.isSafeInteger(data.page?.count)?data.page.count:null;
 const more=count===null?items.length===size:page*size<count;
 return {bvid:bv,scope:'whole_video_comment_threads',root:data.root?normalize(data.root,true):null,root_id:root??null,items,page,page_size:size,total:count,
  remaining:count===null?null:Math.max(0,count-((page-1)*size+items.length)),next_page:more&&page<100?page+1:null,truncated:more,complete:!more&&page===1};
}
