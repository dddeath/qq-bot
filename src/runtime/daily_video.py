"""Bounded video material for one daily batch; no model or publication writes."""
import json
import os
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse
from daily_learning import write


def frame_coverage(frames):
    records=[]
    for text in frames.get('timeline',[]):
        try: meta=json.loads(text)
        except (ValueError,TypeError): continue
        if isinstance(meta,dict) and isinstance(meta.get('selection'),list):records.append(meta)
    if not records:
        times=[image['requested_at_seconds'] for image in frames.get('images',[]) if 'requested_at_seconds' in image]
        if times:return {'status':'sparse','continuous':False,'sampled_times':times,'missing_slots':None,'timestamp_basis':'requested_sample_positions'}
        return {'status':'missing' if not frames.get('images') else 'unknown','continuous':False,'sampled_times':[],'missing_slots':None}
    slots=[slot for meta in records for slot in meta['selection']]
    missing=sum(slot.get('status')!='ok' for slot in slots)
    return {'status':'partial' if missing or frames.get('truncated') else 'sparse', 'continuous':False,
            'ranges':[meta.get('range') for meta in records], 'sampled_times':[slot.get('time') for slot in slots if slot.get('status')=='ok'],
            'missing_slots':missing,'total_slots':len(slots),'note':'Sparse samples only; intervals between samples were not viewed.'}


def enrich_videos(batch, run, settings, *, context_reader=None, frame_reader=None, decision_maker=None, exploration_reader=None):
    if not settings.get('enabled'):
        return []
    if context_reader is None:
        from bilibili_creator_provider import BilibiliProvider
        provider = BilibiliProvider(settings['bilibili_provider'])
        context_reader = lambda video: provider.call('get_video_context', {
            'bvid_or_url':video, 'comment_limit':settings.get('comment_limit',10),
            'danmaku_limit':settings.get('danmaku_limit',80),
            'structured_comments':settings.get('exploration',{}).get('enabled',False)})['data']
    if frame_reader is None:
        def frame_reader(video, folder, count):
            request = dict(video=video, output=str(folder), count=count,
                           timeout_ms=settings.get('video_timeout_seconds',180)*1000)
            result = subprocess.run([settings.get('node','node'), str(Path(__file__).with_name('video')/'learning-call.mjs')],
                input=json.dumps(request), capture_output=True, text=True, encoding='utf-8',
                timeout=settings.get('video_timeout_seconds',180)+15,
                env=os.environ | settings.get('env',{}))
            if result.returncode:
                raise RuntimeError('video_frames_failed')
            return json.loads(result.stdout)
    attachments=[]; records=[]
    limit=max(0,int(settings.get('max_videos_per_batch',3)))
    grids=max(0,int(settings.get('max_grids_per_video',2)))
    for item in batch.get('creators',[]):
        key=item.get('content_id','')
        if not key.startswith('v:'):
            continue
        bvid=key[2:].split(':')[0]
        video='https://www.bilibili.com/video/'+bvid+'/'
        for source in item.get('content',{}).get('sources',[]):
            parsed=urlparse(source or '')
            if parsed.hostname in ('b23.tv','www.b23.tv') or (parsed.hostname in ('bilibili.com','www.bilibili.com','m.bilibili.com') and parsed.path.rstrip('/')=='/video/'+bvid):
                video=source
                break
        index=len(records)
        record=dict(source_id=item['id'],video=video,started_at=time.time())
        item['video_reading']=record
        records.append(record)
        if index>=limit:
            record.update(status='skipped_budget',missing=['text_context','frames'])
            continue
        missing=[]
        started=time.monotonic()
        try:
            record['context']=context_reader(video)
            missing.extend(record['context'].get('missing',[]))
            video=record['context'].get('source_url') or video
        except Exception as exc:
            record['context']={'status':'error','error':str(exc)}
            missing.append('text_context')
        record['context_elapsed_seconds']=time.monotonic()-started
        if settings.get('exploration',{}).get('enabled'):
            from video_exploration_runtime import read_exploration
            exploration=read_exploration(video,record['context'],run/'input/video'/str(index)/'exploration',{**settings,'task_mode':'learning','force_sparse_overview':True,'base_elapsed_seconds':record['context_elapsed_seconds']},
                decide=decision_maker,reader=exploration_reader)
            record['exploration']=exploration
            images=[]
            for read in exploration['reads']:
                for image in read['result'].get('images',[]):
                    attachments.append(image['path']);image['attachment_number']=len(attachments);images.append(image)
            record['frames']={'status':'ok' if images else 'not_requested','images':images, 'coverage':[frame_coverage(read['result']) for read in exploration['reads'] if read['action']['kind'] in ('grids','chapter_grid','frame','frames')]}
            if not images:missing.append('frames')
            if any(c['status'] in ('partial','unknown','missing') for c in record['frames']['coverage']):missing.append('frame_coverage')
            record.update(status='partial' if missing or exploration['stop_reason'] not in ('sufficient','no_next_action','low_expected_gain') else 'ok',
                missing=missing,elapsed_seconds=time.time()-record['started_at'])
            continue
        started=time.monotonic()
        try:
            frames=frame_reader(video,run/'input/video'/str(index),grids) if grids else {'status':'skipped_budget','images':[]}
            raw=frames.get('images',[])
            selected=raw[:grids]
            # Validate all returned paths before attaching any of this video's images.
            folder=(run/'input/video'/str(index)).resolve()
            for image in selected:
                path=Path(image['path']).resolve()
                if not path.is_relative_to(folder) or not path.is_file():raise ValueError('frame_file_missing_or_outside_run')
            frames={**frames,'images':selected,'truncated':len(raw)>grids or frames.get('truncated',False)}
            for image in selected:
                attachments.append(str(Path(image['path']).resolve()))
                image['attachment_number']=len(attachments)
            frames['coverage']=frame_coverage(frames)
            record['frames']=frames
            if not selected or frames.get('status')!='ok':missing.append('frames')
            elif frames['coverage']['status'] in ('partial','unknown'):missing.append('frame_coverage')
        except Exception as exc:
            record['frames']={'status':'error','error':str(exc),'images':[]}
            missing.append('frames')
        record.update(status='partial' if missing else 'ok',missing=missing,
                      frames_elapsed_seconds=time.monotonic()-started,
                      elapsed_seconds=time.time()-record['started_at'])
    write(run/'input/video-reading.json',records)
    return attachments

