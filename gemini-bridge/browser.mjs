import {unpack} from './foxpilot.mjs';

// Only the visible conversation DOM is read; no cookies or internal APIs.
export const inspectPage = `(requestId) => {
 const users=[...document.querySelectorAll('user-query')];
 const responses=[...document.querySelectorAll('model-response')];
 const lastUser=users.at(-1), last=responses.at(-1);
 const after=!!lastUser && !!last && !!(lastUser.compareDocumentPosition(last)&Node.DOCUMENT_POSITION_FOLLOWING);
 const buttons=[...document.querySelectorAll('button[aria-label]')];
 const busy=buttons.some(e=>/^(Stop response|Stop generating|停止回答|停止生成)$/i.test(e.getAttribute('aria-label')||''));
 const text=last?.querySelector('message-content')?.innerText?.trim()||'';
 const copy=!!last?.querySelector('button[aria-label="Copy"],button[aria-label="复制"]');
 return {url:location.href,model:document.querySelector('[data-test-id="bard-mode-menu-button"]')?.innerText,
 users:users.length,responses:responses.length,request_seen:!!lastUser?.innerText.includes(requestId),
 text,complete:after && !busy && copy && !!text,busy};
}`;

export class GeminiPage {
  constructor(fox,{tabId,browserId}) {this.fox=fox;this.tabId=tabId;this.browserId=browserId;}
  async connect() {
    const list=unpack(await this.fox.call('list-browsers',{}));
    if(typeof list!=='string'||!list.includes(this.browserId)||!list.includes('firefox'))throw Error('Expected Firefox not connected');
    await this.fox.call('select-browser',{browserId:this.browserId});
    const p=await this.inspect('');
    if(!p.url?.startsWith('https://gemini.google.com/')||!p.model?.includes('Argon'))throw Error('Gemini Argon page not ready');
    return p;
  }
  async evaluate(fn,args=[]) {
    const r=unpack(await this.fox.call('evaluate-script',{tabId:this.tabId,world:'isolated',function:fn,args}));
    if(!r||typeof r!=='object')throw Error('Unrecognized browser result');
    return r;
  }
  inspect(requestId) {return this.evaluate(inspectPage,[requestId]);}
  async submit(job) {
    await this.fox.call('select-tab',{tabId:this.tabId});
    const before=await this.inspect(job.id);
    if(before.busy||before.request_seen)throw Error('Browser busy or request already present');
    const prompt=JSON.stringify({request_id:job.id,sender_qq:job.sender,message:job.text});
    const filled=await this.evaluate(`(text) => {
      const e=document.querySelector('[contenteditable][role="textbox"]');
      if(!e||e.innerText.trim())throw Error('Composer unavailable or not empty');
      e.focus();e.innerHTML='';const p=document.createElement('p');p.textContent=text;e.appendChild(p);
      e.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertText',data:text}));
      return {filled:e.innerText===text};
    }`,[prompt]);
    if(!filled.filled)throw Error('Composer did not accept text');
    const snap=await this.fox.call('take-snapshot',{tabId:this.tabId,activateTab:true,selector:'button[aria-label="Send message"],button[aria-label="发送消息"]'});
    const text=snap.content?.map(x=>x.text||'').join('\n')||'';
    if(!text.includes('[uid='))throw Error('Send button missing');
    await this.evaluate(`()=>{const b=document.querySelector('button[aria-label="Send message"],button[aria-label="发送消息"]');
      if(!b||b.disabled)throw Error('Send button unavailable');b.click();return {clicked:true};}`);
    // A click acknowledgement is not submission proof. Never click twice.
    for(let i=0;i<10;i++) {
      await new Promise(r=>setTimeout(r,1000));
      if((await this.inspect(job.id)).request_seen)return;
    }
    throw Error('Submission unconfirmed; no automatic retry');
  }
}
