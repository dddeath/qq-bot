"""Real Bilibili read-only boundary, using the existing patched MCP server."""
import datetime as dt
import json
import subprocess

class BilibiliProvider:
    def __init__(self,config):self.config=config
    def call(self,name,args):
        p=subprocess.run([self.config['node'],self.config['call_script']],
            input=json.dumps(dict(name=name,arguments=args)),capture_output=True,
            text=True,encoding='utf-8',timeout=self.config.get('request_timeout_seconds',120))
        if p.returncode:raise RuntimeError('bilibili_transport_failed')
        r=json.loads(p.stdout)
        if r.get('status')!='ok':raise RuntimeError(r.get('error',{}).get('code','bilibili_read_failed'))
        return r
    def catalog(self,account,section,cursor=None):
        args=dict(mid=int(account['uid']),section=section)
        if cursor:args['cursor']=cursor
        r=self.call('get_bilibili_creator_content',args);d=r['data'];items=[]
        for row in d.get(section,[]):
            published=row.get('published_at')
            if not published:continue
            stamp=dt.datetime.fromisoformat(published.replace('Z','+00:00')).timestamp()
            key=('v:'+row['bvid']) if section=='videos' else ('d:'+row['dynamic_id'])
            # A video's feed announcement and upload are one content item.
            if section=='dynamics' and row.get('type')=='video' and row.get('referenced_bvids'):
                key='v:'+row['referenced_bvids'][0]
                row={**row,'bvid':row['referenced_bvids'][0]}
            items.append(dict(id=key,published_at=stamp,row=row))
        return dict(items=items,next_cursor=d.get('next_cursor'))
    def parts(self,bvid):
        return self.call('get_video_metadata',{'bvid_or_url':bvid})['data']
    def read(self,item):
        row=item['row'];url=row.get('source_url');cap=int(self.config.get('max_text_chars',16000))
        if item['id'].startswith('d:'):
            text=row.get('text','')
            return dict(status='ok',text=text[:cap],sources=[url],scope='dynamic_text',
                        truncated=len(text)>cap,images_read=False,original=row.get('original'))
        bv=item['id'][2:].split(':')[0];meta=item.get('metadata') or self.parts(bv)
        page=item.get('page',1)
        content=dict(status='ok',metadata=meta,sources=[url],scope='metadata_only',page=page,cid=item.get('cid'),time_source=item.get('time_source'))
        try:
            r=self.call('get_video_transcript',dict(bvid_or_url=bv,page=page))
            raw=r['data'].get('transcript','');text=raw if isinstance(raw,str) else json.dumps(raw,ensure_ascii=False)
            content.update(text=text[:cap],truncated=len(text)>cap,scope='selected_part_subtitles',data_source=r['data'].get('data_source'))
        except Exception as exc:content['transcript_status']=str(exc)
        return content
