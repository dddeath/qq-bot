"""Bounded whole-video contact sheets; preserve one slot per time bin."""
import json,math,time,sys
from pathlib import Path
from PIL import Image,ImageOps,ImageDraw

def build_overview(manifest,output,*,count=2,frame_count=None,timeout_seconds=180,start_seconds=0,end_seconds=None,extract,now=time.monotonic):
    duration=manifest['duration']
    if type(count) is not int or not 1<=count<=2 or not isinstance(duration,(int,float)) or not math.isfinite(duration) or duration<=0:
        raise ValueError('invalid_overview_budget')
    end_seconds=duration if end_seconds is None else end_seconds
    if frame_count is not None and (type(frame_count) is not int or frame_count<1):raise ValueError('invalid_frame_count')
    if not all(type(x) in (int,float) and math.isfinite(x) for x in (start_seconds,end_seconds)) or not 0<=start_seconds<end_seconds<=duration:raise ValueError('invalid_overview_range')
    span=end_seconds-start_seconds
    root=Path(output);root.mkdir(parents=True,exist_ok=False)
    started=now();bins=min(frame_count if frame_count is not None else count*9,max(1,math.ceil(span)));selection=[];tiles=[]
    candidates=[f for f in manifest.get('frames',[]) if isinstance(f.get('time'),(int,float)) and math.isfinite(f['time']) and Path(f['file']).is_file()]
    for i in range(bins):
        lo=start_seconds+span*i/bins;hi=start_seconds+span*(i+1)/bins;mid=(lo+hi)/2
        pool=[f for f in candidates if lo<=f['time']<hi]
        found=min(pool,key=lambda f:(abs(f['time']-mid),f['time'])) if pool else None
        timestamp=found['time'] if found else mid
        path=Path(found['file']) if found else root/f'fill-{i+1:02d}.jpg'
        remaining=timeout_seconds-(now()-started);error=None
        tile=Image.new('RGB',(640,380),(20,20,20))
        try:
            if remaining<=0:raise TimeoutError('overview_deadline')
            if not found and not extract(manifest['source'],timestamp,str(path),remaining):raise RuntimeError('frame_unavailable')
            with Image.open(path) as image:thumbnail=ImageOps.contain(image.convert('RGB'),(640,350))
            tile.paste(thumbnail,((640-thumbnail.width)//2,30+(350-thumbnail.height)//2))
        except Exception as exc:error=type(exc).__name__+': '+str(exc)
        ImageDraw.Draw(tile).text((10,8),f'{i+1:02d}  {timestamp:.3f}s'+(' MISSING' if error else ''),fill='yellow')
        tiles.append(tile);selection.append(dict(bin=i+1,start_seconds=lo,end_seconds=hi,time=timestamp,origin='keyframe' if found else 'midpoint',status='missing' if error else 'ok',error=error,source_path=str(path)))
    images=[]
    for offset in range(0,len(tiles),9):
        chunk=tiles[offset:offset+9];sheet=Image.new('RGB',(1920,380*math.ceil(len(chunk)/3)),(20,20,20))
        for j,tile in enumerate(chunk):sheet.paste(tile,((j%3)*640,(j//3)*380))
        path=root/f'overview-{len(images)+1}.jpg';sheet.save(path,quality=85)
        images.append(dict(path=str(path),mimeType='image/jpeg'))
    result=dict(status='partial' if any(x['status']=='missing' for x in selection) else 'ok',duration_seconds=duration,range={'start_seconds':start_seconds,'end_seconds':end_seconds},selection=selection,images=images,elapsed_seconds=now()-started)
    (root/'overview.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result

if __name__=='__main__':
    from yueying import store,frames
    req=json.load(sys.stdin);entry=store.resolve(req['video'])
    if entry is None:raise ValueError('video_manifest_missing')
    manifest=json.loads((entry/'manifest.json').read_text())
    def extract(video,t,path,remaining):
        return frames.extract_one(video,t,path,timeout=min(60,remaining))
    print(json.dumps(build_overview(manifest,req['output'],count=req.get('count',2),timeout_seconds=req.get('timeout_seconds',180),start_seconds=req.get('start_seconds',0),end_seconds=req.get('end_seconds'),extract=extract)))
