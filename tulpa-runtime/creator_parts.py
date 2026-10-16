"""Discover timed CID updates within a bounded creator scan."""
import json
from contextlib import closing
import sqlite3

def expand_parts(dbpath,uid,candidates,provider,config,now,cutoff):
    latest=max(0,int(config.get('latest_video_check_limit',20)))
    total=max(0,int(config.get('video_check_limit',30)))
    videos=sorted((v for v in candidates.values() if v['id'].startswith('v:')),key=lambda x:(-x['published_at'],x['id']))
    chosen={v['id'][2:]:v for v in videos[:min(latest,total)]}
    with closing(sqlite3.connect(dbpath)) as d,d:
        d.execute('CREATE TABLE IF NOT EXISTS multipart_watch(uid TEXT,bvid TEXT,body TEXT,checked REAL,PRIMARY KEY(uid,bvid))')
        # Seed previously collected multi-part uploads without modifying old receipts.
        for body, in d.execute('SELECT body FROM seen WHERE uid=?',(uid,)):
            old=json.loads(body);meta=old.get('content',{}).get('metadata',{})
            if len(meta.get('pages',[]))>1 and meta.get('bvid'):
                bv=meta['bvid'];item=dict(id='v:'+bv,published_at=old['published_at'],row={'bvid':bv})
                d.execute('INSERT OR IGNORE INTO multipart_watch VALUES(?,?,?,?)',(uid,bv,json.dumps(item),0))
        for bv,body in d.execute('SELECT bvid,body FROM multipart_watch WHERE uid=? ORDER BY checked,bvid',(uid,)):
            if len(chosen)>=total:break
            chosen.setdefault(bv,json.loads(body))
    result={k:v for k,v in candidates.items() if not k.startswith('v:') and cutoff<=v['published_at']<=now}
    report=dict(checked=[],unknown_time=[],errors=[],latest_catalog_truncated=len(videos)>latest)
    for bv,upload in chosen.items():
        report['checked'].append(bv)
        with closing(sqlite3.connect(dbpath)) as d,d:
            d.execute('UPDATE multipart_watch SET checked=? WHERE uid=? AND bvid=?',(now,uid,bv))
        try:meta=provider.parts(bv)
        except Exception as exc:
            report['errors'].append(dict(bvid=bv,error=str(exc)));continue
        pages=meta.get('pages',[])
        if len(pages)>1:
            with closing(sqlite3.connect(dbpath)) as d,d:
                d.execute('INSERT OR REPLACE INTO multipart_watch VALUES(?,?,?,?)',(uid,bv,json.dumps(upload),now))
        for part in pages:
            cid=part.get('cid');page=part.get('page');stamp=part.get('ctime')
            if not isinstance(cid,int) or cid<=0 or not isinstance(page,int) or page<=0:
                report['errors'].append(dict(bvid=bv,error='invalid_part_identity'));continue
            if not isinstance(stamp,(int,float)) or isinstance(stamp,bool) or stamp<=0:
                report['unknown_time'].append(dict(bvid=bv,cid=cid,page=page,status='needs_verification'));continue
            if not cutoff<=stamp<=now:continue
            key=f'v:{bv}:cid:{cid}'
            result[key]=dict(id=key,published_at=stamp,page=page,cid=cid,time_source='part.ctime',
                row={**upload.get('row',{}),'bvid':bv,'source_url':f'https://www.bilibili.com/video/{bv}/?p={page}'},metadata=meta)
    return result,report
