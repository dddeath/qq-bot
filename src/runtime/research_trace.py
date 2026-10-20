"""Opt-in tool-boundary evidence for scoped research tasks."""
import base64
import datetime as dt
import json
import time
import uuid
from pathlib import Path
from learning_research import ReadBudget


CONTROL_TOOLS = ['begin_reading_task', 'finish_reading_task']

def write_record(path, value):
    staging = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    staging.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    staging.replace(path)


class ResearchTrace:
    def __init__(self, config):
        self.config = config
        self.root = Path(config['root'])
        self.root.mkdir(parents=True, exist_ok=True)

    def folder(self, task_id):
        if not isinstance(task_id, str) or len(task_id) != 32 or any(c not in '0123456789abcdef' for c in task_id):
            raise ValueError('invalid_reading_task_id')
        folder = self.root / task_id
        if not (folder / 'context.json').is_file():
            raise ValueError('unknown_reading_task')
        return folder

    def begin(self, goal, video=None):
        if not isinstance(goal, str) or not goal.strip():
            raise ValueError('reading_goal_required')
        task_id = uuid.uuid4().hex
        folder = self.root / task_id
        folder.mkdir()
        limits = {k: self.config.get(k, default) for k, default in
                  [('max_read_units', 10), ('exploration_budget_ratio', .2), ('timeout_seconds', 300)]}
        if (type(limits['max_read_units']) is not int or limits['max_read_units'] < 1
                or not 0 <= limits['exploration_budget_ratio'] <= 1 or limits['timeout_seconds'] <= 0):
            raise ValueError('invalid_reading_budget')
        context = dict(goal=goal, video=video, task_mode='reading', audit_scope=self.config['scope'],
                       task_source='model_declared_at_task_entry', budget=limits,
                       recorded_at=dt.datetime.now(dt.timezone.utc).isoformat())
        (folder / 'context.json').write_text(json.dumps(context, ensure_ascii=False), encoding='utf-8')
        ReadBudget(folder / 'budget.db', limits['max_read_units'],
                   limits['exploration_budget_ratio'], limits['timeout_seconds'])
        return task_id

    def remaining(self, folder):
        with ReadBudget(folder / 'budget.db').db() as db:
            units, explore, deadline = db.execute('select units,explore,deadline from settings').fetchone()
            rows = db.execute('select purpose,overview from calls').fetchall()
        return dict(read_units=max(0, units-sum(not r[1] for r in rows)),
                    exploration_units=max(0, explore-sum(r[0] == 'explore' for r in rows)),
                    seconds=max(0, deadline-time.time()))

    def prepare(self, tool, arguments):
        args = dict(arguments)
        purpose = args.pop('_reading', None)
        if not isinstance(purpose, dict):
            raise ValueError('reading_context_required')
        folder = self.folder(purpose.get('task_id'))
        if (folder / 'completion.json').exists():
            raise ValueError('reading_task_closed')
        relation = purpose.get('relation')
        if not isinstance(relation, str) or not relation.strip():
            raise ValueError('reading_relation_required')
        before = self.remaining(folder)
        index = ReadBudget(folder / 'budget.db').reserve(tool, purpose.get('purpose'), purpose.get('reason'))
        record = dict(read_id=index, tool=tool, arguments=args,
                      action={'kind': tool, 'purpose': purpose['purpose']},
                      purpose_record={'question': purpose['reason'], 'relation_reason': relation,
                                      'prior_observation': purpose.get('prior_observation'),
                                      'source': 'model_declared_before_call'},
                      budget_before=before, started_at=time.time(),
                      result={'status': 'pending', 'images': []})
        path = folder / f'read-{index:03d}.json'
        write_record(path, record)
        return path, args

    def complete(self, path, response, elapsed):
        record = json.loads(path.read_text(encoding='utf-8'))
        body = response.get('result', {})
        content = body.get('content', [])
        record['result'] = dict(status='error' if response.get('error') or body.get('isError') else 'ok',
                                text='\n'.join(c.get('text', '') for c in content if c.get('type') == 'text'),
                                images=[])
        if response.get('error'):
            record['result']['error'] = response['error']
        if 'structuredContent' in body:
            record['result']['structured_content'] = body['structuredContent']
        for n, item in enumerate(content):
            if item.get('type') != 'image':
                continue
            extension = {'image/png': 'png', 'image/jpeg': 'jpg', 'image/webp': 'webp'}.get(item.get('mimeType'), 'img')
            image = path.with_name(path.stem + f'-{n}.{extension}')
            image.write_bytes(base64.b64decode(item['data'], validate=True))
            record['result']['images'].append({'path': str(image), 'mime_type': item.get('mimeType')})
        record.update(finished_at=time.time(), elapsed_seconds=elapsed,
                      budget_remaining=self.remaining(path.parent))
        write_record(path, record)
        self.report(path.parent)

    def reject(self, tool, arguments, error):
        purpose = arguments.get('_reading') or {}
        try:
            folder = self.folder(purpose.get('task_id'))
        except ValueError:
            return
        if (folder / 'completion.json').exists():
            return
        write_record(folder / ('rejected-' + uuid.uuid4().hex + '.json'),
                     {'tool': tool, 'arguments': arguments, 'error': str(error), 'timestamp': time.time(),
                      'upstream_called': False, 'budget_charged': False})
        self.report(folder)

    def finish(self, task_id, stop_reason, reason, conclusion):
        folder = self.folder(task_id)
        if not all(isinstance(x, str) and x.strip() for x in (stop_reason, reason, conclusion)):
            raise ValueError('reading_completion_required')
        if any(json.loads(p.read_text(encoding='utf-8'))['result']['status'] == 'pending'
               for p in folder.glob('read-*.json')):
            raise ValueError('reading_calls_pending')
        completion = dict(stop_reason=stop_reason, reason=reason, conclusion=conclusion,
                          basis='model_declared', budget_remaining=self.remaining(folder),
                          timestamp=time.time())
        with (folder / 'completion.json').open('x', encoding='utf-8') as out:
            json.dump(completion, out, ensure_ascii=False)
        return self.report(folder)

    def report(self, folder):
        context = json.loads((folder / 'context.json').read_text(encoding='utf-8'))
        reads = [json.loads(p.read_text(encoding='utf-8')) for p in sorted(folder.glob('read-*.json'))]
        completion = json.loads((folder / 'completion.json').read_text(encoding='utf-8')) if (folder / 'completion.json').exists() else None
        report = dict(recorded_at=context['recorded_at'], captured_at=dt.datetime.now(dt.timezone.utc).isoformat(),
                      context=context, user_request=context['goal'], video=context['video'], reads=reads,
                      decisions=[{'read_id': r['read_id'], 'purpose_record': r['purpose_record'],
                                  'budget_remaining': r['budget_before']} for r in reads],
                      completion=completion, stop_reason=completion['stop_reason'] if completion else None,
                      rejected_calls=[json.loads(p.read_text(encoding='utf-8')) for p in sorted(folder.glob('rejected-*.json'))],
                      trace_coverage='instrumented_mcp_calls_only')
        # Separate proxies may finish reads concurrently; each evidence file remains authoritative.
        staging = folder / ('report-' + uuid.uuid4().hex + '.tmp')
        staging.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        staging.replace(folder / 'report.json')
        return report

    def schemas(self, tools):
        result = []
        for tool in tools:
            tool = json.loads(json.dumps(tool))
            schema = tool['inputSchema']
            schema.setdefault('properties', {})['_reading'] = {
                'type': 'object', 'properties': {
                    'task_id': {'type': 'string'}, 'purpose': {'type': 'string', 'enum': ['targeted', 'explore']},
                    'reason': {'type': 'string'}, 'relation': {'type': 'string'},
                    'prior_observation': {'type': 'string'}},
                'required': ['task_id', 'purpose', 'reason', 'relation'], 'additionalProperties': False}
            schema['required'] = list(dict.fromkeys(schema.get('required', []) + ['_reading']))
            result.append(tool)
        for name, description, fields, required in [
            ('begin_reading_task', 'Start one research trace with the original user goal; returns task_id and budget.',
             ['goal', 'video'], ['goal']),
            ('finish_reading_task', 'Record why reading stops and the actual conclusion after all reads finish.',
             ['task_id', 'stop_reason', 'reason', 'conclusion'], ['task_id', 'stop_reason', 'reason', 'conclusion'])]:
            result.append(dict(name=name, description=description, inputSchema={
                'type': 'object', 'properties': {k: {'type': 'string'} for k in fields},
                'required': required, 'additionalProperties': False}))
        return result

    def control(self, name, arguments):
        if name == 'begin_reading_task':
            task_id = self.begin(**arguments)
            return {'task_id': task_id, 'budget_remaining': self.remaining(self.folder(task_id))}
        report = self.finish(**arguments)
        return {'recorded': True, 'stop_reason': report['stop_reason'],
                'reads': len(report['reads']), 'budget_remaining': report['completion']['budget_remaining']}
