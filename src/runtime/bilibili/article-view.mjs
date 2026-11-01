import {mkdir,writeFile} from 'node:fs/promises';
import {join} from 'node:path';
import {tmpdir} from 'node:os';
import {randomUUID} from 'node:crypto';

export async function createArticleView(raw,{directory,callId=randomUUID()}={}) {
 const images=[],unparsed=[];
 function nodes(values,index,path) {
  return (values??[]).map((node,i)=>{
   if(node.type==='TEXT_NODE_TYPE_WORD'&&typeof node.word?.words==='string'){
    const text=node.word.words;
    return node.word.style?.strikethrough?`~~${text}~~`:text;
   }
   unparsed.push({paragraph_index:index,path:`${path}.${i}`,type:node.type??'unknown_text_node'});
   return '[未解析文本节点]';
  }).join('');
 }
 function body(p,index,path,refs) {
  if(p.para_type===1)return nodes(p.text?.nodes,index,path);
  if(p.para_type===8)return nodes(p.heading?.nodes,index,path);
  if(p.para_type===3)return '---';
  if(p.para_type===2){
   return (p.pic?.pics??[]).map((im,i)=>{
    const id=`${path}.image${i}`;refs.push(id);
    images.push({id,url:im.url,width:im.width,height:im.height,paragraph_index:index,...(im.comment?{caption:im.comment}:{})});
    return im.comment??'';
   }).filter(Boolean).join('\n');
  }
  if(p.para_type===4)return (p.blockquote?.children??[]).map((x,i)=>body(x,index,`${path}.quote${i}`,refs)).join('\n');
  if(p.para_type===5)return (p.list?.children??[]).map((item,i)=>{
   const text=(item.children??[]).map((x,j)=>body(x,index,`${path}.list${i}.${j}`,refs)).join('\n');
   const prefix=p.list.theme==='dot'?'-':`${item.order??i+1}.`;
   return `${prefix} ${text}`;
  }).join('\n');
  unparsed.push({paragraph_index:index,path,type:p.para_type??'unknown_paragraph'});
  return '[未解析段落]';
 }
 const kinds={1:'text',2:'image',3:'separator',4:'quote',5:'list',8:'heading'};
 const paragraphs=raw.paragraphs.map(({index,data})=>{
  const image_refs=[];const text=body(data,index,`p${index}`,image_refs);
  return {index,type:kinds[data.para_type]??'unknown',text,image_refs};
 });
 let evidence;
 try{
  const dir=directory??join(tmpdir(),'qq-bilibili-article-evidence');await mkdir(dir,{recursive:true});
  const path=join(dir,`${callId}.article-raw.json`);
  await writeFile(path,JSON.stringify({schema_version:1,call_id:callId,article:raw}),{encoding:'utf8',flag:'wx'});
  evidence={stored:true,id:callId,path};
 }catch{evidence={stored:false,id:callId,error:'ARTICLE_EVIDENCE_WRITE_FAILED'};}
 return {opus_id:raw.opus_id,source_url:raw.source_url,title:raw.title,start:raw.start,count:raw.count,total_paragraphs:raw.total_paragraphs,paragraphs,images,next_start:raw.next_start,coverage:{...raw.coverage,text_projection_complete:unparsed.length===0,...(unparsed.length?{unparsed}:{})},evidence};
}
