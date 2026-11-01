// Dependencies are supplied by the host; credential values never become results.
export async function readSubscription(source,{getCookie,init,request}) {
 const started=performance.now();const {uid,timeout_ms=60000}=source;let timer;
 const base={uid,route:`/bilibili/user/dynamic/${uid}`};
 if(typeof uid!=='string'||!/^[1-9][0-9]{0,19}$/.test(uid)||!Number.isInteger(timeout_ms)||timeout_ms<1||timeout_ms>60000)return {...base,status:'failed',error:'INVALID_RSS_ARGUMENT'};
 let error='RSS_REQUEST_FAILED';
 try {
  const cookie=await getCookie();if(typeof cookie!=='string'||!cookie){error='RSS_CREDENTIAL_MISSING';throw Error();}
  const work=async()=>{await init({CACHE_TYPE:'memory',REQUEST_TIMEOUT:'15000',REQUEST_RETRY:'0',BILIBILI_COOKIE_0:cookie,LOGGER_LEVEL:'error',UA:'qq-bot-learning-experiment/1.0 (RSSHub)',NO_RANDOM_UA:'true'});const result=await request(base.route);const feed=result.data??result;if(!Array.isArray(feed.item))throw Error();return feed;};
  const feed=await Promise.race([work(),new Promise((_,reject)=>{timer=setTimeout(()=>{error='RSS_TIMEOUT';reject(Error());},timeout_ms);})]);
  return {...base,status:'completed',feed,coverage:'feed_content',elapsed_seconds:(performance.now()-started)/1000};
 }catch{return {...base,status:'failed',error,elapsed_seconds:(performance.now()-started)/1000};}
 finally{clearTimeout(timer);}
}

