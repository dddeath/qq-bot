import {readFile,writeFile,mkdir} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {join} from 'node:path';
import {randomUUID} from 'node:crypto';

const base=fileURLToPath(new URL('./node_modules/@xzxzzx/bilibili-mcp/',import.meta.url));
const pkg=JSON.parse(await readFile(join(base,'package.json'),'utf8'));
if(pkg.version!=='1.14.2') throw new Error('Expected upstream 1.14.2');
const changes={
 'dist/bilibili/video-api.js':[
   ['duration: entry.duration,','duration: entry.duration,\n                ctime: Number.isSafeInteger(entry.ctime) && entry.ctime > 0 ? entry.ctime : undefined,'],
 ],
 'dist/bilibili/navigation.js':[
   ['duration: p.duration,','duration: p.duration,\n        ctime: p.ctime,'],
 ],
 'dist/bilibili/creator-content.js':[
   ['const publishedAt = toIsoFromUnixSeconds(author.pub_ts);','const publishedAt = toIsoFromUnixSeconds(typeof author.pub_ts === "string" && /^\\d+$/.test(author.pub_ts) ? Number(author.pub_ts) : author.pub_ts);'],
   ['if (url.protocol !== "https:" ||','if (url.protocol === "http:") url.protocol = "https:";\n        if (url.protocol !== "https:" ||'],
   ['toOptionalPositiveInteger(value.width)','toOptionalPositiveInteger(typeof value.width === "string" && /^\\d+$/.test(value.width) ? Number(value.width) : value.width)'],
   ['toOptionalPositiveInteger(value.height)','toOptionalPositiveInteger(typeof value.height === "string" && /^\\d+$/.test(value.height) ? Number(value.height) : value.height)'],
 ],
 'dist/bilibili/wbi.js':[
   ['return saltTable.map((i) => mixKey[i]).join("");','return saltTable.map((i) => mixKey[i]).join("").slice(0, 32);'],
   ['`${key}=${value}`','`${encodeURIComponent(key)}=${encodeURIComponent(String(value).replace(/[!\x27()*]/g, ""))}`'],
 ],
 'dist/bilibili/http.js':[
   ['timestamp: Math.floor(Date.now() / 1000),','wts: Math.floor(Date.now() / 1000),'],
   ['...baseParams,\n                    wts:', '...Object.fromEntries(Object.entries(baseParams).map(([k,v]) => [k, String(v).replace(/[!\x27()*]/g, "")])),\n                    wts:'],
   ['Accept: "application/json",\n                        ...additionalHeaders,','Accept: "application/json",\n                        ...credentialManager.getAuthHeaders(),\n                        ...additionalHeaders,'],
 ],
};
const pending=[];
for(const [path,replacements] of Object.entries(changes)) {
 const original=await readFile(join(base,path),'utf8');let modified=original;
 for(const [before,after] of replacements) {
   if(modified.includes(after)) continue;
   if(modified.split(before).length!==2) throw new Error(`Unexpected upstream content: ${path}`);
   modified=modified.replace(before,after);
 }
 if(modified!==original) pending.push({path,original,modified});
}
if(!pending.length){console.log('Upstream patches already applied');process.exit(0);}
const evidence=process.env.QQ_BILIBILI_PATCH_EVIDENCE;
if(!evidence) throw new Error('Set QQ_BILIBILI_PATCH_EVIDENCE to preserve originals');
const run=join(evidence,new Date().toISOString().replaceAll(':','-')+'-'+randomUUID().slice(0,8));
await mkdir(run,{recursive:true});
for(const x of pending){await writeFile(join(run,x.path.replaceAll('/','__')),x.original);}
await writeFile(join(run,'manifest.json'),JSON.stringify({base,files:pending.map(x=>x.path)},null,2));
for(const x of pending){await writeFile(join(base,x.path),x.modified);if(await readFile(join(base,x.path),'utf8')!==x.modified)throw new Error('write verification failed');}
console.log(JSON.stringify({patched:pending.map(x=>x.path),backup:run}));
