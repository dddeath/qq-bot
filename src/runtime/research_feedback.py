"""Read-only links between research reports, sent QQ replies and follow-up messages."""
import copy
import hashlib
from contextlib import closing
import json
import os
import sqlite3
import time
import uuid
from pathlib import Path


def link_feedback(reports, replies, messages, *, conversation_id, cutoff,
                  feedback_window_seconds=3600):
    """Keep structural links separate from interpretation of the user's words."""
    if feedback_window_seconds <= 0:
        raise ValueError('invalid_feedback_window')
    reports = [copy.deepcopy(r) for r in reports
               if r['conversation_id'] == conversation_id and r['at'] <= cutoff]
    messages = [copy.deepcopy(m) for m in messages
                if m['conversation_id'] == conversation_id and m['at'] <= cutoff
                and not m.get('is_self') and not m.get('synthetic')]
    by_event = {str(m['event_id']): m for m in messages}
    items = {r['report_id']: dict(report=r, requests=[], replies=[], followups=[],
                                 pending_followups=[]) for r in reports}
    unresolved = []
    sent = {}
    for reply in replies:
        if (reply['conversation_id'] != conversation_id or reply['at'] > cutoff
                or reply['state'] != 'SUCCEEDED' or not reply.get('message_id')):
            continue
        mid = str(reply['message_id'])
        if mid in sent:
            continue
        sent[mid] = copy.deepcopy(reply)
        explicit = 'report_refs' in reply
        if explicit:
            refs = reply['report_refs']
            candidates = list(dict.fromkeys(ref.get('report_id') for ref in refs
                if ref.get('report_id') in items
                and items[ref['report_id']]['report'].get('version') == ref.get('version')
                and items[ref['report_id']]['report']['at'] <= reply['at']))
            valid = bool(refs) and all(ref.get('report_id') in items
                and items[ref['report_id']]['report'].get('version') == ref.get('version')
                and items[ref['report_id']]['report']['at'] <= reply['at'] for ref in refs)
            basis = {'kind': 'explicit_report_reference',
                     'meaning': 'Model selected these report versions for the reply plan.'}
        else:
            candidates = [rid for rid in reply['report_candidates'] if rid in items
                          and items[rid]['report']['at'] <= reply['at']]
            valid = len(candidates) == 1
            basis = {'kind': 'single_report_delivered_in_response_turn',
                     'meaning': 'Report was available in the sending turn; use of its contents remains for review.'}
        if not valid:
            unresolved.append(dict(reply=copy.deepcopy(reply), candidates=candidates,
                reason='explicit_reference_unresolved' if explicit else
                       'report_link_ambiguous' if candidates else 'report_link_missing'))
            continue
        for rid in candidates:
            item = items[rid]
            item['replies'].append({**copy.deepcopy(reply), 'link_basis': basis})
            request = by_event.get(str(reply.get('target_event_id')))
            if request and request['at'] <= reply['at'] and request not in item['requests']:
                item['requests'].append(copy.deepcopy(request))
    for item in items.values():
        ids = {str(r['message_id']): r for r in item['replies']}
        for message in messages:
            eligible = {mid: r for mid, r in ids.items()
                        if 0 < message['at'] - r['at'] <= feedback_window_seconds}
            if not eligible:
                continue
            quoted = [str(mid) for mid in message.get('reply_message_ids', [])
                      if str(mid) in eligible]
            # Exact text quotation is evidence of an explicit reference, not sentiment.
            textual = [mid for mid, r in eligible.items()
                       if len(r.get('text', '').strip()) >= 12
                       and r['text'].strip() in message['text']]
            linked = quoted or textual
            if linked:
                item['followups'].append(dict(message=copy.deepcopy(message),
                    basis={'kind': 'qq_quote' if quoted else 'exact_reply_text',
                           'reply_message_ids': linked},
                    classification='pending_review'))
            elif not message.get('reply_message_ids'):
                # Plain nearby messages are candidates, never asserted evaluations.
                item['pending_followups'].append(dict(message=copy.deepcopy(message),
                    basis={'kind': 'time_window_only', 'reply_message_ids': list(eligible)},
                    classification='association_unresolved'))
        item['status'] = 'linked' if item['replies'] else 'no_linked_sent_reply'
    return dict(schema_version=1, conversation_id=conversation_id, captured_at=cutoff,
                feedback_window_seconds=feedback_window_seconds,
                items=list(items.values()), unresolved_replies=unresolved,
                interpretation='Follow-ups are original messages; relevance and evaluation are not inferred.')


def jsonl(path):
    with Path(path).open(encoding='utf-8') as stream:
        for number, line in enumerate(stream, 1):
            try:
                yield number, json.loads(line)
            except ValueError:
                continue


def body_of(item):
    result = item.get('result') or {}
    for key in ('structuredContent', 'structured_content'):
        if isinstance(result.get(key), dict):
            return result[key]
    for block in result.get('content', []):
        if block.get('type') == 'text':
            try:
                value = json.loads(block['text'])
                if isinstance(value, dict):
                    return value
            except ValueError:
                pass
    return {}


def full_report(result, database, conversation_id):
    """Recover the exact registered version when the delivered report was paged."""
    data = result.get('result') or {}
    text = data.get('last_agent_message')
    ref = result.get('report_ref') or {}
    version = ref.get('version') or hashlib.sha256(text.encode()).hexdigest()
    source = None
    if hashlib.sha256(text.encode()).hexdigest() != version and database.is_file():
        with closing(sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True)) as db:
            db.execute('PRAGMA query_only=ON')
            row = db.execute('SELECT body FROM reports WHERE conversation=? AND id=? AND version=?',
                             (conversation_id, ref.get('report_id'), version)).fetchone()
        if row:
            restored = json.loads(row[0])['result']['last_agent_message']
            if hashlib.sha256(restored.encode()).hexdigest() == version:
                text = restored
                source = {'file': str(database.resolve()), 'report_id': ref['report_id'], 'version': version}
    return text, version, ('complete' if hashlib.sha256(text.encode()).hexdigest() == version
                           else 'registered_body_unavailable'), source


def runtime_materials(run_directories, conversation_id):
    """Read actual tool receipts and reports delivered in the same response turn."""
    reports, replies = {}, []
    for directory in run_directories:
        path = Path(directory) / 'timed.jsonl'
        active = []
        for number, row in jsonl(path):
            event = row.get('event', {})
            if event.get('type') != 'item.completed':
                continue
            item = event.get('item', {})
            if item.get('type') != 'mcp_tool_call':
                continue
            body = body_of(item)
            if item.get('tool') == 'wait_chat_messages':
                active = []
                if body.get('event') != 'background_results':
                    continue
                for result in body.get('results', []):
                    data = result.get('result') or {}
                    text = data.get('last_agent_message')
                    tid = data.get('turn_id')
                    agent = result.get('agent_id')
                    if not text or not tid or not agent:
                        continue
                    rid = agent + ':' + tid
                    if result.get('report_ref', {}).get('report_id', rid) != rid:
                        continue
                    text, version, content_status, registry_source = full_report(
                        result, Path(directory)/'research-links.sqlite3', conversation_id)
                    reports.setdefault(rid, dict(report_id=rid, version=version, native_thread_id=agent,
                        turn_id=tid, root_turn_id=data.get('root_turn_id'), text=text,
                        content_status=content_status, registry_source=registry_source,
                        at=row['observed_at'], conversation_id=conversation_id,
                        source={'file': str(path.resolve()), 'line': number}))
                    active.append(rid)
            elif item.get('tool') == 'send_chat_reply':
                for bubble in body.get('bubbles', []):
                    receipt = bubble.get('receipt') or {}
                    result = receipt.get('result') or {}
                    if result.get('conversation_id') != conversation_id:
                        continue
                    replies.append(dict(message_id=str(result['message_id']) if result.get('message_id') is not None else None,
                        target_event_id=result.get('reply_to_event_id', body.get('decision', {}).get('target_event_id')),
                        text=result.get('content', ''), at=result.get('timestamp', row['observed_at']),
                        state=receipt.get('state'), conversation_id=conversation_id,
                        plan_id=body.get('plan_id'), bubble_index=bubble.get('index'),
                        report_candidates=list(dict.fromkeys(active)),
                        source={'file': str(path.resolve()), 'line': number}))
                    association = body.get('research_association')
                    if association is not None:
                        # Presence of an explicit receipt suppresses legacy same-turn guessing.
                        replies[-1]['report_refs'] = (association.get('reports', [])
                            if association.get('conversation_id') == conversation_id
                            and association.get('plan_id') == body.get('plan_id') else [])
    return list(reports.values()), replies


def read_messages(database, session_id, conversation_id, *, after, before):
    """Scope the SQLite read to the configured chat, without opening a writer."""
    with closing(sqlite3.connect(Path(database).resolve().as_uri() + '?mode=ro', uri=True)) as db:
        db.execute('PRAGMA query_only=ON')
        rows = db.execute('SELECT id,message_id,payload,at FROM chat_inbox '
                          'WHERE session_id=? AND at>=? AND at<=? ORDER BY id',
                          (session_id, after, before)).fetchall()
    messages = []
    for eid, mid, payload, at in rows:
        p = json.loads(payload)
        if p.get('conversation_id') != conversation_id or p.get('source') != 'onebot_websocket':
            continue
        messages.append(dict(event_id=eid, message_id=str(mid), text=p.get('content', ''),
            at=at, conversation_id=conversation_id, sender_id=p.get('sender_id'),
            sender=p.get('sender'), is_self=p.get('is_self', False),
            synthetic=p.get('synthetic', False), truncated=p.get('truncated', False),
            reply_message_ids=[str(s.get('onebot_message_id', s.get('id')))
                               for s in p.get('segments', []) if s.get('type') == 'reply'],
            mentions=[str(s.get('qq')) for s in p.get('segments', []) if s.get('type') == 'at'],
            source={'file': str(Path(database).resolve()), 'table': 'chat_inbox', 'row': eid}))
    return messages


def collect_feedback(run_directories, database, session_id, conversation_id, *,
                     cutoff=None, feedback_window_seconds=3600):
    cutoff = time.time() if cutoff is None else cutoff
    reports, replies = runtime_materials(run_directories, conversation_id)
    start = min((r['at'] for r in reports), default=cutoff)
    # Original request can precede completion; the one-hour window also bounds this lookup.
    messages = read_messages(database, session_id, conversation_id,
                             after=start-feedback_window_seconds, before=cutoff)
    return link_feedback(reports, replies, messages, conversation_id=conversation_id,
                         cutoff=cutoff, feedback_window_seconds=feedback_window_seconds)


def decoded_objects(value):
    """Read nested JSON MCP blocks, never code or free-form quoted chat text."""
    stack = [value]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            if current.get('isError') is True:
                continue
            yield current
            stack.extend(current.values())
        elif isinstance(current, list):
            stack.extend(current)
        elif isinstance(current, str) and current.lstrip().startswith(('{', '[')):
            try: stack.append(json.loads(current))
            except ValueError: pass


def native_task_links(task_id, reports, sessions):
    """Bind an executor task to actual tool receipts in a delivered report's turn."""
    links = {}
    if not task_id or not sessions:
        return links
    by_thread = {}
    for report in reports:
        by_thread.setdefault(report['native_thread_id'], {})[report['turn_id']] = report['report_id']
    for thread, turns in by_thread.items():
        for path in sorted(Path(sessions).rglob(f'*{thread}.jsonl')):
            owner = None
            turn = None
            calls = {}
            for number, row in jsonl(path):
                payload = row.get('payload', {})
                if row.get('type') == 'session_meta' and owner is None:
                    owner = payload.get('id')
                    if owner != thread: break
                elif row.get('type') == 'turn_context':
                    turn = payload.get('turn_id')
                elif row.get('type') == 'response_item' and owner == thread:
                    kind, cid = payload.get('type'), payload.get('call_id')
                    if kind in ('function_call', 'custom_tool_call') and turn in turns:
                        name = payload.get('name', '')
                        code = payload.get('input', '') if name == 'exec' else name
                        if 'begin_reading_task' in code or 'declare_native_read' in code:
                            calls[cid] = (turn, number)
                    elif kind in ('function_call_output', 'custom_tool_call_output') and cid in calls:
                        for value in decoded_objects(payload.get('output')):
                            if (value.get('task_id') == task_id and
                                    ((value.get('protocol_version') and value.get('execution_prompt')) or
                                     (value.get('read_id') and value.get('native_input')))):
                                call_turn, line = calls[cid]
                                links.setdefault(turns[call_turn], []).append({
                                    'kind': 'native_task_receipt', 'task_id': task_id,
                                    'native_thread_id': thread, 'native_turn_id': call_turn,
                                    'call_id': cid, 'file': str(path.resolve()),
                                    'call_line': line, 'result_line': number})
                                break
    return links


def prepare_review_feedback(settings, output):
    """One read-only collection path for daily and explicitly requested reviews."""
    cfg = settings.get('reading_review', {})
    feedback = cfg.get('feedback', {})
    conversation = str(settings.get('account', '')) + ':group:' + str(settings.get('group', ''))
    bundle = {'status': 'not_configured', 'conversation_id': conversation, 'items': []}
    try:
        if cfg.get('feedback_bundle'):
            bundle = json.loads(Path(cfg['feedback_bundle']).read_text(encoding='utf-8'))
        elif feedback.get('enabled'):
            for key in ('account', 'group', 'access_db'):
                if not settings.get(key): raise ValueError('feedback_binding_missing: ' + key)
            directories = list(feedback.get('run_directories', []))
            if feedback.get('current_run_path_file'):
                directories.append(Path(feedback['current_run_path_file']).read_text(encoding='utf-8').strip())
            if not directories: raise ValueError('feedback_binding_missing: run_directories')
            bundle = collect_feedback(list(dict.fromkeys(directories)), settings['access_db'],
                feedback['session_id'], conversation, cutoff=feedback.get('cutoff'),
                feedback_window_seconds=feedback.get('window_seconds', 3600))
            bundle['status'] = 'collected'
    except (OSError, ValueError, KeyError, sqlite3.Error) as exc:
        bundle = {'status': 'collection_failed', 'conversation_id': conversation,
                  'items': [], 'error': str(exc)}
    root = Path(output)
    root.mkdir(parents=True, exist_ok=True)
    path = root / ('feedback-' + uuid.uuid4().hex + '.json')
    path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding='utf-8')
    return {**bundle, 'collection_file': str(path.resolve()),
            'native_sessions_directory': feedback.get('native_sessions_directory') or
                (str(Path(os.environ['CODEX_HOME'])/'sessions') if os.environ.get('CODEX_HOME') else None)}


def attach_feedback(original, bundle, *, native_sessions_directory=None):
    """Create an audit projection; never rewrite the reading trace or user evaluation."""
    result = copy.deepcopy(original)
    if bundle.get('status') in ('not_configured', 'collection_failed'):
        result['research_feedback'] = {key: bundle[key] for key in
            ('status', 'error', 'collection_file') if key in bundle}
        result['research_feedback']['items'] = []
        return result
    scope = original.get('context', {}).get('audit_scope')
    if scope != 'qq:' + bundle['conversation_id']:
        result['research_feedback'] = {'status': 'scope_mismatch', 'items': []}
        return result
    thread = original.get('native_thread_id')
    turn = original.get('native_turn_id')
    # Native thread IDs are recorded identities; textual similarity is not one.
    candidates = [copy.deepcopy(item) for item in bundle['items']
             if thread and item['report']['native_thread_id'] == thread
             and (not turn or item['report']['turn_id'] == turn)]
    evidence = []
    if not candidates:
        links = native_task_links(original.get('task_id'), [i['report'] for i in bundle['items']],
                                  native_sessions_directory or bundle.get('native_sessions_directory'))
        candidates = [copy.deepcopy(item) for item in bundle['items'] if item['report']['report_id'] in links]
        evidence = [link for item in candidates for link in links[item['report']['report_id']]]
    items = candidates if len(candidates) == 1 else []
    result['research_feedback'] = dict(status='linked' if items else
        'report_identity_ambiguous' if candidates else 'report_identity_unavailable',
        items=items, association_scope='native_turn', identity_evidence=evidence,
        candidate_report_ids=[i['report']['report_id'] for i in candidates],
        collection_file=bundle.get('collection_file'),
        captured_at=bundle['captured_at'],
        feedback_window_seconds=bundle['feedback_window_seconds'],
        interpretation=bundle['interpretation'])
    return result


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', action='append', required=True)
    parser.add_argument('--database', required=True)
    parser.add_argument('--session', required=True)
    parser.add_argument('--conversation', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    result = collect_feedback(args.run, args.database, args.session, args.conversation)
    with Path(args.output).open('x', encoding='utf-8') as out:
        json.dump(result, out, ensure_ascii=False, indent=2)
