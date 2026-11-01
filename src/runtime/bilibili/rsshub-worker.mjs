import {credentialManager} from '@xzxzzx/bilibili-mcp/dist/utils/credentials.js';
import {readSubscription} from './rsshub-reader.mjs';
process.once('disconnect',()=>process.exit(0));
process.once('message',async({uid})=>{
 let result;
 try{const {init,request}=await import('rsshub');result=await readSubscription({uid},{getCookie:()=>credentialManager.getAuthHeaders().Cookie,init,request});}
 catch{result={status:'failed',error:'RSS_REQUEST_FAILED'};}
 if(process.send)process.send(result,()=>process.exit(result.status==='completed'?0:1));
});
