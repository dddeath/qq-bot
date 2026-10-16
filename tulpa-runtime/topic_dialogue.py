"""Dialogue evidence and interpretation for the offline decision boundary."""
from pathlib import Path


def load_member_profiles(root):
    profiles={}
    for path in sorted(Path(root).glob('*/*/members/*.md')):
        text=path.read_text(encoding='utf-8-sig')
        if not text.startswith('---\n'):continue
        fields={}
        for line in text.split('---',2)[1].splitlines():
            key,sep,value=line.partition(':')
            if sep:fields[key.strip()]=value.strip().strip('"\'')
        kind=fields.get('participant_type')
        if kind not in ('ai','human'):continue
        qq=fields.get('qq_number',path.stem)
        if qq!=path.stem:raise ValueError('member QQ number differs from filename')
        account,group=path.relative_to(root).parts[:2]
        profiles.setdefault(f'{account}:group:{group}',{})[qq]=dict(participant_type=kind,source=fields.get('source','unspecified'))
    return profiles


def quote_ids(message):
    return [str(s['onebot_message_id']) for s in message.get('segments',[])
            if s.get('type')=='reply' and s.get('onebot_message_id') is not None]


def dialogue_context(message, view):
    past=[m for m in view['messages'] if m['id']!=message['id'] and m['at']<=message['at']
          and m.get('group')==message.get('group')]
    by_id={m['id']:m for m in past}
    quotes=quote_ids(message)
    exchanges=[]
    for reply in past:
        if not reply.get('is_self'):continue
        for target in quote_ids(reply):
            request=by_id.get(target)
            if request and request['at']<=reply['at'] and request['sender']==message['sender']:
                exchanges.append(dict(request=request,reply=reply))
    return dict(explicit_mentions=[str(s['qq']) for s in message.get('segments',[]) if s.get('type')=='at' and 'qq' in s],
                quoted_messages=[by_id[i] for i in quotes if i in by_id],
                missing_quote_ids=[i for i in quotes if i not in by_id],
                recent_sender_messages=[m for m in past if m['sender']==message['sender']][-3:],
                recent_bot_messages=[m for m in past if m.get('is_self')][-3:],
                sender_bot_exchanges=exchanges[-2:],
                recent_bot_by_topic={t['id']:[m for m in t['messages'] if m['id'] in by_id and m.get('is_self')][-2:]
                                     for t in view['topics']})


def interpret(decision, message, visible):
    if not isinstance(decision,dict):raise ValueError('invalid maintainer decision')
    if decision.get('addressee') not in ('bot','other','group','unknown'):
        raise ValueError('invalid addressee')
    if decision.get('intent') not in ('question','request','followup','correction','answer','comment','chat'):
        raise ValueError('invalid intent')
    if type(decision.get('should_interject')) is not bool:raise ValueError('invalid interjection decision')
    reference=decision.get('reply_to_message_id')
    past={m['id'] for m in visible if m['id']!=message['id'] and m['at']<=message['at'] and m.get('group')==message.get('group')}
    if reference is not None and reference not in past:
        unavailable_quote=reference in quote_ids(message) and reference!=message['id'] and not any(
            m['id']==reference for m in visible)
        if not unavailable_quote:raise ValueError('reply reference is not visible past context')
    direct=decision['addressee']=='bot' and decision['intent'] in ('question','request','followup','correction')
    return direct,decision['should_interject']
