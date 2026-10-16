"""Video preparation and bounded frame generation; JSON stdin/stdout process seam."""
import json,sys,math,re
from pathlib import Path
from sparse_overview import build_overview

def extract(video,seconds,path,remaining):
 from yueying import ffm
 ffm.run(['-ss',str(seconds),'-i',video,'-frames:v','1','-vf','scale=min(1280\\,iw):-2',path],timeout=max(.001,remaining))
 return Path(path).is_file()

def execute(req):
 operation=req['operation'];timeout=req.get('timeout_seconds',90)
 if operation=='prepare':
  source=str(Path(req['video']).resolve(strict=True))
  from yueying import ffm
  result=ffm.run(['-i',source],check=False,timeout=timeout)
  match=re.search(r'Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)',result.stderr)
  if not match:raise ValueError('video_duration_unavailable')
  duration=int(match[1])*3600+int(match[2])*60+float(match[3])
  if not math.isfinite(duration) or duration<=0:raise ValueError('invalid_video_duration')
  return {'source':source,'duration':duration,'frames':[]}
 manifest=req['manifest']
 if operation=='sample':
  return build_overview(manifest,req['output'],frame_count=req['frame_count'],start_seconds=req['start_seconds'],end_seconds=req['end_seconds'],timeout_seconds=timeout,extract=extract)
 if operation=='at':
  root=Path(req['output']);root.mkdir(parents=True,exist_ok=False);path=root/'frame.jpg';extract(manifest['source'],req['time'],str(path),timeout)
  return {'requested_seconds':req['time'],'extraction_seek_seconds':req['time'],'method':'source_time_seek','path':str(path)}
 raise ValueError('unknown_frame_operation')
if __name__=='__main__':print(json.dumps(execute(json.load(sys.stdin))))
