// Resolve only public Bilibili short links; never forward account credentials.
export async function resolveVideoInput(input) {
 if(typeof input!=='string') return input;
 let url;
 try {url=new URL(input.trim());} catch {return input;}
 if(url.hostname!=='b23.tv' && url.hostname!=='www.b23.tv') return input;
 const signal=AbortSignal.timeout(10000);
 for(let i=0;i<4;i++) {
  if(!['http:','https:'].includes(url.protocol)||url.username||url.password||url.port) throw new Error('B23_RESOLUTION_FAILED');
  if(url.hostname!=='b23.tv' && url.hostname!=='www.b23.tv') {
   if(url.hostname==='bilibili.com'||url.hostname.endsWith('.bilibili.com')) {
    const match=url.pathname.match(/^\/video\/(BV[a-zA-Z0-9]{10})(?:\/|$)/);
    if(match) {
     if(!url.searchParams.has('p')) return match[1];
     const target=new URL(`https://www.bilibili.com/video/${match[1]}/`);
     target.searchParams.set('p',url.searchParams.get('p'));
     return target.href;
    }
   }
   throw new Error('B23_RESOLUTION_FAILED');
  }
  url.protocol='https:';
  const response=await fetch(url.href,{redirect:'manual',signal});
  await response.body?.cancel();
  const location=response.headers.get('location');
  if(![301,302,303,307,308].includes(response.status)||!location) throw new Error('B23_RESOLUTION_FAILED');
  url=new URL(location,url);
 }
 throw new Error('B23_RESOLUTION_FAILED');
}
