"""Bounded model-directed material reading before final learning or answering."""

import json, math, time

import datetime as dt

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'sessions'))
from run_records import recorded



DEFAULTS = json.loads((Path(__file__).resolve().parents[2]/'config/video-reading-policy.json').read_text(encoding='utf-8'))



def explore_video(video, context, run, settings, decide, read, *, now=time.monotonic):
    run=Path(run);run.mkdir(parents=True,exist_ok=False)
    with recorded(run, purpose='research', harness='codex') as execution:
        result=_explore_video(video, context, run, settings, decide, read, now=now)
        execution['result']={'stop_reason':result['stop_reason'],'report':str(run/'report.json')}
        if result.get('error') or result['stop_reason'] in ('decision_failed','invalid_decision'):
            execution.update(status='failed',error=result.get('error',result['stop_reason']))
        return result


def _explore_video(video, context, run, settings, decide, read, *, now=time.monotonic):

    cfg=DEFAULTS | settings

    if (type(cfg['max_read_units']) is not int or not 0<=cfg['max_read_units']<=100 or

        not isinstance(cfg['exploration_budget_ratio'],(int,float)) or not 0<=cfg['exploration_budget_ratio']<=1 or

        not isinstance(cfg['timeout_seconds'],(int,float)) or not 0<cfg['timeout_seconds']<=1800 or

        type(cfg['max_decisions']) is not int or not 1<=cfg['max_decisions']<=100 or

        type(cfg['comment_page_size']) is not int or not 1<=cfg['comment_page_size']<=20 or

        type(cfg['max_grids']) is not int or not 1<=cfg['max_grids']<=2):

        raise ValueError('invalid_exploration_budget')

    for key,ceiling in [('max_segment_seconds',12),('max_frames_per_segment',8),('max_sampled_frames',24),('max_grid_reads',1),('max_chapter_reads',2)]:

        if type(cfg[key]) is not int or not 1<=cfg[key]<=ceiling:raise ValueError('invalid_visual_budget')

    run=Path(run)

    state=dict(video=video,context=context,reads=[],decisions=[])

    budget=dict(total=cfg['max_read_units'],exploration_limit=math.floor(cfg['max_read_units']*cfg['exploration_budget_ratio']),

                exploration_used=0,targeted_used=0)

    budget['targeted_limit']=budget['total']-budget['exploration_limit']

    budget.update(chapter_reads_used=0,chapter_reads_limit=cfg['max_chapter_reads'],sampled_frames_used=0,sampled_frames_limit=cfg['max_sampled_frames'],grid_reads_used=0,grid_reads_limit=cfg['max_grid_reads'],max_segment_seconds=cfg['max_segment_seconds'],max_frames_per_segment=cfg['max_frames_per_segment'])

    started=now()-cfg.get('initial_elapsed_seconds',0);stop='decision_limit';seen=set()

    for _ in range(cfg['max_decisions']):

        if budget['targeted_used']+budget['exploration_used']>=budget['total']:

            stop='read_budget_exhausted';break

        remaining=cfg['timeout_seconds']-(now()-started)

        if remaining<=0:stop='timeout';break

        budget.update(remaining_seconds=remaining,remaining_decisions=cfg['max_decisions']-len(state['decisions']),targeted_remaining=budget['targeted_limit']-budget['targeted_used'],exploration_remaining=budget['exploration_limit']-budget['exploration_used'])

        began=now()

        try:decision=decide({**state,'budget':budget},remaining)

        except Exception as exc:

            state['error']=str(exc);stop='decision_failed';break

        if not isinstance(decision,dict):stop='invalid_decision';break

        state['decisions'].append({**decision,'elapsed_seconds':now()-began})

        if now()-started>=cfg['timeout_seconds']:stop='timeout';break

        action=decision.get('action')

        if action is None:

            if budget['exploration_limit'] and not budget['exploration_used'] and not decision.get('no_unread_material',False):

                state['exploration_required']=True;continue

            stop=decision.get('stop_reason') if decision.get('stop_reason') in ('sufficient','low_expected_gain','materials_unavailable') else ('sufficient' if decision.get('sufficient') else 'no_next_action');break

        state.pop('exploration_required',None)

        if not valid_action(action):stop='invalid_action';break

        purpose_record=decision.get('purpose_record')

        if cfg.get('purpose_contract'):

            if not isinstance(purpose_record,dict) or any(not isinstance(purpose_record.get(k),str) or not purpose_record[k].strip() for k in ('question','relation_reason','expected_gain')):

                stop='missing_purpose_record';break

            parent=purpose_record.get('parent_read')

            if parent is not None and (type(parent) is not int or not 1<=parent<=len(state['reads'])):

                stop='invalid_parent_read';break

            if purpose_record.get('relation') not in ('high','partial','unrelated'):

                stop='invalid_relation';break

            if action['purpose']=='targeted' and (purpose_record['relation']!='high' or not context.get('purpose_anchor')):

                stop='purpose_mismatch';break

        purpose='exploration' if action['purpose']=='explore' else 'targeted'

        if budget[purpose+'_used']>=budget[purpose+'_limit']:

            stop='purpose_budget_exhausted';break

        frame_cost=1 if action['kind']=='frame' else math.floor((action['end_seconds']-action['start_seconds'])/action['interval_seconds'])+1 if action['kind']=='frames' else 0

        if (action['kind']=='frames' and (action['end_seconds']-action['start_seconds']>cfg['max_segment_seconds'] or frame_cost>cfg['max_frames_per_segment']) or

            budget['sampled_frames_used']+frame_cost>cfg['max_sampled_frames'] or

            action['kind']=='grids' and budget['grid_reads_used']>=cfg['max_grid_reads'] or

            action['kind']=='chapter_grid' and budget['chapter_reads_used']>=cfg['max_chapter_reads']):

            stop='visual_budget_exhausted';break

        duration=context.get('preflight',{}).get('duration_seconds')

        if duration and ((action.get('end_seconds',0)>duration if action['kind']=='chapter_grid' else action.get('end_seconds',0)>=duration) or action.get('at_seconds',0)>=duration):stop='invalid_action';break

        key=json.dumps({k:v for k,v in action.items() if k!='purpose'},sort_keys=True)

        if key in seen:stop='duplicate_read';break

        seen.add(key)

        remaining=cfg['timeout_seconds']-(now()-started)

        if remaining<=0:stop='timeout';break

        budget['exploration_used' if action['purpose']=='explore' else 'targeted_used']+=1

        budget['sampled_frames_used']+=frame_cost

        if action['kind']=='grids':budget['grid_reads_used']+=1

        if action['kind']=='chapter_grid':budget['chapter_reads_used']+=1

        began=now()

        try:result=read(action,remaining)

        except Exception as exc:result=dict(status='error',error=str(exc))

        state['reads'].append(dict(read_id=len(state['reads'])+1,action=action,result=result,purpose_record=purpose_record))

        state['reads'][-1]['elapsed_seconds']=now()-began

        (run/f'read-{len(state["reads"]):02d}.json').write_text(json.dumps(state['reads'][-1],ensure_ascii=False,indent=2),encoding='utf-8')

    budget.update(remaining_seconds=max(0,cfg['timeout_seconds']-(now()-started)),remaining_decisions=cfg['max_decisions']-len(state['decisions']),targeted_remaining=budget['targeted_limit']-budget['targeted_used'],exploration_remaining=budget['exploration_limit']-budget['exploration_used'])

    result={**state,'record_origin':'exploration_executor','task_id':run.name,'recorded_at':dt.datetime.now(dt.timezone.utc).isoformat(),'budget':budget,'stop_reason':stop,'elapsed_seconds':now()-started}

    (run/'report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')

    return result



def valid_action(action):

    if not isinstance(action,dict) or action.get('purpose') not in ('targeted','explore'):return False

    fields={'chapter_grid':{'start_seconds','end_seconds','chapter_title','chapter_source'},'description':set(),'chapters':set(),'comments':{'page','root_id'},'subtitles':{'start_seconds','end_seconds'},

            'danmaku':{'start_seconds','end_seconds'},'grids':set(),'frame':{'at_seconds'},'frames':{'start_seconds','end_seconds','interval_seconds'}}

    kind=action.get('kind')

    if kind not in fields or set(action)-fields[kind]-{'kind','purpose'}:return False

    if 'page' in action and (type(action['page']) is not int or not 1<=action['page']<=100):return False

    if 'root_id' in action and (not isinstance(action['root_id'],str) or not action['root_id'].isdigit() or int(action['root_id'])<=0):return False

    for k in ('start_seconds','end_seconds','at_seconds','interval_seconds'):

        if k in action and (not isinstance(action[k],(int,float)) or not math.isfinite(action[k]) or action[k]<0):return False

    if kind=='chapter_grid' and (not {'start_seconds','end_seconds','chapter_title','chapter_source'}<=set(action) or action['end_seconds']<=action['start_seconds'] or action['chapter_source'] not in ('platform','inferred') or not isinstance(action['chapter_title'],str) or not action['chapter_title'].strip()):return False

    if kind=='frames' and (not {'start_seconds','end_seconds','interval_seconds'}<=set(action) or action['interval_seconds']<0.25):return False

    if kind=='frame' and 'at_seconds' not in action:return False

    if 'end_seconds' in action and action['end_seconds']<action.get('start_seconds',0):return False

    return True
