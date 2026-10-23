"""Read-only links between research reports, sent QQ replies and follow-up messages."""
import copy
import hashlib
from contextlib import closing
import json
import sqlite3
import time
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
                    reports.setdefault(rid, dict(report_id=rid, version=hashlib.sha256(text.encode()).hexdigest(), native_thread_id=agent,
                        turn_id=tid, root_turn_id=data.get('root_turn_id'), text=text,
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


def attach_feedback(original, bundle):
    """Create an audit projection; never rewrite the reading trace or user evaluation."""
    result = copy.deepcopy(original)
    scope = original.get('context', {}).get('audit_scope')
    if scope != 'qq:' + bundle['conversation_id']:
        result['research_feedback'] = {'status': 'scope_mismatch', 'items': []}
        return result
    thread = original.get('native_thread_id')
    turn = original.get('native_turn_id')
    # Native thread IDs are recorded identities; textual similarity is not one.
    items = [copy.deepcopy(item) for item in bundle['items']
             if thread and item['report']['native_thread_id'] == thread
             and (not turn or item['report']['turn_id'] == turn)]
    result['research_feedback'] = dict(status='linked' if items else 'report_identity_unavailable',
        items=items, association_scope='native_turn' if turn else 'native_thread',
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
