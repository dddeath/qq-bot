"""Shared execution receipts; native evidence remains owned by each harness."""
from contextlib import contextmanager
import json
import hashlib
import os
from pathlib import Path
import time
import uuid


def state(value):
    return {'success': 'succeeded', 'completed': 'succeeded',
            'execution_succeeded': 'succeeded', 'execution_failed': 'failed',
            'stopped': 'unknown', 'idle': 'unknown'}.get(value, value) if value in (
                'success', 'completed', 'execution_succeeded', 'execution_failed',
                'stopped', 'idle', 'running', 'succeeded', 'failed', 'cancelled', 'unknown') else 'unknown'


def receipt(session, run_id, *, status='running', started_at=None, finished_at=None,
            native_session_id=None, result=None, error=None, evidence=None):
    return dict(schema_version=1, run_id=run_id, session_id=session.get('session_id'),
                purpose=session.get('purpose'), harness=session.get('harness'),
                native_session_id=native_session_id or session.get('native_session_id'),
                status=state(status), started_at=started_at, finished_at=finished_at,
                elapsed_seconds=finished_at-started_at if finished_at is not None and started_at is not None else None,
                result=result, error=error, evidence=evidence,
                configuration={k:session[k] for k in ('model','effort') if k in session})


def from_turn(session, turn):
    return receipt(session, turn['request_id'], status=turn.get('status'),
                   started_at=turn.get('started_at'), finished_at=turn.get('finished_at'),
                   native_session_id=turn.get('native_session_id'),
                   result={k: turn[k] for k in ('response', 'exit_code', 'continuation') if k in turn},
                   error=turn.get('error'), evidence=turn.get('evidence'))


def save(path, value):
    temp = path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)


@contextmanager
def recorded(directory, *, purpose, harness, native_session_id=None, session_id=None, configuration=None):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory/'run-receipt.json'
    value = receipt(dict(session_id=session_id, purpose=purpose, harness=harness),
                    str(directory.resolve()), started_at=time.time(),
                    native_session_id=native_session_id, evidence=str(directory.resolve()))
    value['configuration'] = configuration or {}
    value['owner_pid'] = os.getpid()
    with path.open('x', encoding='utf-8') as out:
        json.dump(value, out, ensure_ascii=False)
    try:
        yield value
    except BaseException as exc:
        value.update(status='cancelled' if isinstance(exc, (KeyboardInterrupt, SystemExit)) else 'failed',
                     error=type(exc).__name__+': '+str(exc))
        raise
    else:
        if value['status'] == 'running':
            value['status'] = 'succeeded'
    finally:
        value['finished_at'] = time.time()
        value['elapsed_seconds'] = value['finished_at']-value['started_at']
        # Only native evidence establishes a newly created thread identity.
        log = directory/'execution.jsonl'
        if value['native_session_id'] is None and log.exists():
            for line in log.read_text(encoding='utf-8').splitlines():
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if event.get('type') == 'thread.started':
                    value['native_session_id'] = event.get('thread_id')
                    break
        save(path, value)


def loaded_configuration(*, model, effort, release, snapshot=None, **settings):
    value=dict(model=model, effort=effort, release=str(release), **settings)
    if snapshot:
        path=Path(snapshot)
        raw=path.read_bytes()
        body=json.loads(raw)
        value.update(tool_snapshot=str(path), tool_snapshot_sha256=hashlib.sha256(raw).hexdigest(),
                     bot_ref=body.get('bot_ref'), tool_profile_ref=body.get('tool_profile_ref'))
    return value
