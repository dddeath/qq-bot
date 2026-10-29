"""Daily video reading through the shared, evidence-recording research executor."""
from copy import deepcopy
import json
from pathlib import Path
import time

from daily_learning import write


def overview(item):
    content = item.get('content', {})
    meta = content.get('metadata', {})
    page = content.get('page', 1)
    parts = meta.get('pages', [])
    selected = next((p for p in parts if content.get('cid') and p.get('cid') == content['cid']), None)
    selected = selected or next((p for p in parts if p.get('page') == page), {})
    page = selected.get('page', page)
    bvid = item['content_id'][2:].split(':')[0]
    description = meta.get('description', '')
    return {'video': f'https://www.bilibili.com/video/{bvid}/?p={page}',
            'bvid': bvid, 'page': page, 'cid': selected.get('cid', content.get('cid')),
            'title': meta.get('title'), 'part_title': selected.get('title'),
            'author': meta.get('author', item.get('creator', {}).get('name')),
            'published_at': item.get('published_at', meta.get('pubdate')),
            'duration_seconds': selected.get('duration', meta.get('duration') if len(parts) <= 1 else None),
            'description': description[:1500], 'description_truncated': len(description) > 1500,
            'basis': 'collected_video_metadata', 'metadata_available': bool(meta)}


def visual_coverage(reads):
    """Count viewed pixels, not merely generated samples or returned file names."""
    samples = {}; times = []; ranges = []; views = []; image_count = 0
    for read in reads:
        result = read.get('result', {}); tool = read.get('tool'); args = read.get('arguments', {})
        if result.get('status') != 'ok': continue
        metadata = []
        for line in result.get('text', '').splitlines():
            try:
                value = json.loads(line)
                if isinstance(value, dict): metadata.append(value)
            except ValueError: pass
        if tool == 'sample_video_frames':
            for value in metadata:
                if value.get('sample_id') and isinstance(value.get('selection'), list):
                    samples[value['sample_id']] = value
        images = result.get('images', [])
        if not images: continue
        image_count += len(images)
        observed = []
        if tool == 'get_frames':
            sample = samples.get(args.get('sample_id'))
            if sample:
                step = 9 if args.get('kind', 'grids') == 'grids' else 1
                start = (args.get('start', 1)-1)*step
                # Failed individual frames do not return pixels; their status remains missing.
                slots = sample['selection'][start:start+args.get('count', 2)*step]
                observed = [x['time'] for x in slots if x.get('status') == 'ok']
                ranges.append(sample.get('range'))
        elif tool == 'get_frame_at':
            observed = [x['requested_seconds'] for x in metadata if 'requested_seconds' in x]
        times.extend(observed)
        views.append({'read_id': read.get('read_id'), 'tool': tool, 'image_count': len(images),
                      'sampled_times': observed})
    return {'status': 'sparse' if times else 'unknown' if image_count else 'missing',
            'continuous': False, 'sampled_times': sorted(set(times)), 'ranges': ranges,
            'image_count': image_count, 'views': views}


def enrich(batch, run, settings, *, execute=None):
    if execute is None:
        from learning_research import autonomous_research
        execute = autonomous_research
    run = Path(run); options = settings.get('autonomous', {})
    per_video = float(options.get('timeout_seconds', 600))
    batch_seconds = float(options.get('batch_timeout_seconds', 1800))
    max_videos = int(settings.get('max_videos_per_batch', 3))
    if per_video <= 0 or batch_seconds <= 0 or max_videos < 0:
        raise ValueError('invalid_daily_video_budget')
    deadline = time.monotonic()+batch_seconds
    records = []; attachments = []
    for item in batch.get('creators', []):
        if not item.get('content_id', '').startswith('v:'): continue
        original_item = deepcopy({k: v for k, v in item.items() if k != 'video_reading'})
        base = overview(item); index = len(records)
        record = {'source_id': item['id'], 'video': base['video'], 'overview': base,
                  'mode': 'unified_research', 'started_at': time.time()}
        records.append(record); item['video_reading'] = record
        remaining = min(per_video, deadline-time.monotonic())
        if index >= max_videos or remaining <= 0:
            record.update(status='skipped_budget', missing=['autonomous_reading']); continue
        if not settings.get('tool_snapshot'):
            record.update(status='error', error='daily_video_tool_snapshot_required'); continue
        folder = run/'input/video'/str(index)/'reading'
        limits = {'timeout_seconds': remaining, 'max_read_units': int(options.get('max_read_units', 23)),
                  'exploration_budget_ratio': options.get('exploration_budget_ratio', .2)}
        goal = f"阅读并理解视频《{base.get('title') or base['bvid']}》" + (
            f"第 {base['page']} P《{base['part_title']}》" if base.get('part_title') else f"第 {base['page']} P") + '的主要内容，供每日学习提炼。'
        original = {'user_request': goal, 'video': base['video'], 'creator_material': original_item,
                    'source': {'kind': 'daily_video', 'source_id': item['id']},
                    'context': {'audit_scope': f"qq:{settings.get('account','')}:group:{settings.get('group','')}"}}
        context = {'entry': 'daily_video_learning', 'overview': base, 'source_id': item['id']}
        began = time.monotonic()
        try:
            result = execute(original, folder, limits, settings, task_mode='learning',
                             task_context=context, needs=['reference'], deadline=time.time()+remaining)
            report_path = folder/'report.json'
            # Use the executor's exact report; other consumers disclose it progressively.
            if not report_path.is_file(): write(report_path, result)
            coverage = visual_coverage(result.get('reads', []))
            record.update(status=result.get('status', 'partial'), summary=result.get('summary', ''),
                          stop_reason=result.get('stop_reason'), stop_record=result.get('stop_record'),
                          report_path=str(report_path), coverage=coverage,
                          missing=[] if coverage['sampled_times'] else ['visual_coverage'])
            if record['missing']: record['status'] = 'partial'
            initial_images = []
            for read in result.get('reads', []):
                if read.get('tool') != 'get_frames' or read.get('arguments', {}).get('kind', 'grids') != 'grids': continue
                for image in read.get('result', {}).get('images', []):
                    path = Path(image['path']).resolve()
                    if not path.is_relative_to(folder.resolve()) or not path.is_file():
                        raise ValueError('frame_file_missing_or_outside_run')
                    if len(initial_images) < 2:
                        attachments.append(str(path))
                        initial_images.append({'path': str(path), 'read_id': read.get('read_id'),
                                               'attachment_number': len(attachments)})
                if initial_images: break
            record['frames'] = {'images': initial_images, 'coverage': coverage}
        except Exception as exc:
            record.update(status='error', error=str(exc))
            if (folder/'report.json').is_file(): record['report_path'] = str(folder/'report.json')
        record['elapsed_seconds'] = time.monotonic()-began
    write(run/'input/video-reading.json', records)
    return attachments
