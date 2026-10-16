import {readFile,writeFile} from 'node:fs/promises';
import {join,resolve} from 'node:path';
const dir=resolve(process.argv[2]??'');
const manifest=JSON.parse(await readFile(join(dir,'manifest.json'),'utf8'));
const allowed=new Set(['dist/bilibili/wbi.js','dist/bilibili/http.js','dist/bilibili/creator-content.js']);
if(!Array.isArray(manifest.files)||manifest.files.some(p=>!allowed.has(p)))throw new Error('Unexpected backup paths');
const originals=await Promise.all(manifest.files.map(async p=>({path:p,text:await readFile(join(dir,p.replaceAll('/','__')),'utf8')})));
if(process.argv.includes('--apply')){
 for(const f of originals){await writeFile(join(manifest.base,f.path),f.text);if(await readFile(join(manifest.base,f.path),'utf8')!==f.text)throw new Error('Restore verification failed');}
 console.log(JSON.stringify({restored:manifest.files}));
}else console.log(JSON.stringify({rollback_ready:true,files:manifest.files,changed:false}));
