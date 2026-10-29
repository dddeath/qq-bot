"""Require reviewed semantic tags before either learning publication channel."""
import hashlib
import json
import uuid
from knowledge_tag_import import normalized
from pathlib import Path

VERSION = 'learning-tag-admission-v2'
FIELDS = {'expressions': ('situation', 'surface_form', 'style'),
          'meanings': ('term', 'meaning', 'usage', 'conditions', 'kind')}


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def body(kind, value):
    return '\n'.join(f'{k}: {value[k]}' for k in FIELDS[kind])


def catalog(config):
    policy = json.loads(Path(config['policy']).read_text(encoding='utf-8-sig'))
    target = Path(config['entry_store'])
    base = json.loads(target.read_text(encoding='utf-8-sig')) if target.exists() else {}
    tags = {t['id']: {k: t[k] for k in ('id', 'name', 'category', 'aliases', 'description')}
            for t in policy['tags']}
    tags.update(base.get('tags', {}))
    return tags


def invoke(sessions, role, request, folder):
    folder.mkdir(parents=True, exist_ok=False)
    write(folder/'input.json', request)
    from learning_tag_protocol import generate
    protocol = generate(role, request)
    write(folder/'protocol.json', protocol)
    try:
        result = sessions.call(role, request, folder)
        write(folder/'result.json', result)
        if not result.get('native_session_id'):
            raise ValueError('native_session_id_missing')
        return result
    except Exception as exc:
        write(folder/'error.json', {'type': type(exc).__name__, 'message': str(exc)})
        raise


def validate_content(kind, draft, sources):
    fields = FIELDS[kind]
    required = ('surface_form',) if kind == 'expressions' else ('term', 'meaning')
    if (any(not isinstance(draft.get(k), str) for k in fields)
            or any(not draft[k].strip() for k in required)):
        raise ValueError('invalid_content')
    ids = draft.get('source_ids', [])
    if not ids or any(str(i) not in sources for i in ids):
        raise ValueError('unknown_source')
    if kind == 'expressions':
        quote = draft.get('evidence_quote')
        if not quote or not any(quote in sources[str(i)].get('text', '') for i in ids):
            raise ValueError('quote_missing')
    elif draft['kind'] not in ('group', 'community', 'fact'):
        raise ValueError('invalid_meaning_kind')
    return {k: draft[k] for k in fields}


def approve_tags(decision, proposal, tags, original_ids):
    ids = decision.get('tag_ids', [])
    if not isinstance(ids, list) or any(not isinstance(t,str) or t not in tags for t in ids):
        raise ValueError('unknown_tag')
    requests = proposal.get('new_tags', [])
    if not isinstance(requests,list):raise ValueError('invalid_new_tags')
    by_key = {t['key']:t for t in requests}
    if len(by_key)!=len(requests):raise ValueError('duplicate_tag_request')
    additions = {}
    for key in decision.get('new_tag_keys', []):
        if key not in by_key:raise ValueError('unknown_tag_request')
        new = by_key[key]
        if (new['category'] not in ('领域','主题','对象','需求')
                or any(not isinstance(new.get(k),str) or not new[k].strip() for k in ('name','description','reason'))
                or not isinstance(new.get('aliases'),list)
                or any(not isinstance(a,str) or not a.strip() for a in new['aliases'])):
            raise ValueError('invalid_tag_definition')
        names = {normalized(x) for x in [new['name'],*new['aliases']]}
        tag_id = 'tag-'+hashlib.sha256((new['category']+':'+normalized(new['name'])).encode()).hexdigest()[:16]
        definition = {k:new[k] for k in ('name','category','aliases','description')}
        definition['id']=tag_id
        for existing in [*tags.values(),*additions.values()]:
            if existing['category'] != new['category']:continue
            if names & {normalized(x) for x in [existing['name'],*existing['aliases']]}:
                if existing['id'] in original_ids or existing!=definition:
                    raise ValueError('reuse_existing_tag_required:'+existing['id'])
        if tag_id in tags and tags[tag_id]!=definition:raise ValueError('tag_id_conflict')
        additions[tag_id]=definition;ids=[*ids,tag_id]
    if not ids:raise ValueError('valid_tag_required')
    tags.update(additions)
    return list(dict.fromkeys(ids))


def pending_from_previous(learning, run):
    from daily_learning import RETENTION
    cutoff=json.loads((run/'manifest.json').read_text())['cutoff']
    journals=[]
    for manifest in (learning.root/'runs').glob('*/manifest.json'):
        folder=manifest.parent
        if folder==run or not (folder/'review/tag-admission.json').exists():continue
        at=json.loads(manifest.read_text())['cutoff']
        if cutoff-RETENTION<=at<=cutoff:journals.append((at,folder.name,folder))
    if not journals:return [],{},{},{}
    previous_run=max(journals)[2]
    path=previous_run/'review/tag-admission.json'
    previous=json.loads(path.read_text(encoding='utf-8-sig'))
    if previous.get('account')!=learning.account or previous.get('group')!=learning.group:
        raise ValueError('pending_scope_mismatch')
    materials=previous.get('sources',{})
    eligible={k:v for k,v in materials.items() if v.get('at',0)>=cutoff-RETENTION}
    publication=previous_run/'tag-publication.json'
    committed=publication.exists() and json.loads(publication.read_text()).get('status')=='published'
    rows=[{**r['candidate'], 'previous_review': r['candidate'].get('previous_review',r['reason'])} for r in previous['records'] if (r['status']=='pending' or (r['status']=='approved' and not committed))
          and all(str(i) in eligible for i in r['candidate']['draft']['source_ids'])]
    carried={r['candidate_id'] for r in rows}
    approvals={r['candidate_id']:r for r in previous['records']
               if r['status']=='approved' and r['candidate_id'] in carried}
    used={t for r in approvals.values() for t in r['tags']}
    definitions={t['id']:t for t in previous['tag_definitions'] if t['id'] in used}
    return rows,eligible,approvals,definitions


def admit(learning, clean, drafts, sources, run, *, sessions=None):
    config = learning.knowledge_publication or {}
    rows = []
    for kind in FIELDS:
        for value, draft in zip(clean[kind], drafts[kind]):
            rows.append(dict(candidate_id=value['id'], kind=kind, draft=draft,
                source_domains=sorted({sources[str(i)].get('creator', {}).get('category', '')
                                       for i in draft['source_ids']} - {''})))
    previous,old_sources,approvals,definitions=pending_from_previous(learning,run)
    sources={**old_sources,**sources}
    merged={r['candidate_id']:r for r in previous}
    for row in rows:
        old=merged.get(row['candidate_id'])
        if old and body(old['kind'],old['draft'])==body(row['kind'],row['draft']):
            row.update(return_count=old.get('return_count',0),previous_review=old.get('previous_review',''))
        else:approvals.pop(row['candidate_id'],None)
        merged[row['candidate_id']]=row
    rows=list(merged.values())
    tags = catalog(config) if config.get('policy') and config.get('entry_store') else {}
    tags={**definitions,**tags}
    results = {r['candidate_id']: dict(candidate_id=r['candidate_id'], status='pending',
                reason='review_not_configured', return_count=r.get('return_count',0), candidate=r) for r in rows}
    approved = {'expressions': [], 'meanings': []}
    for row in rows:
        saved=approvals.get(row['candidate_id'])
        if saved:
            results[row['candidate_id']]={**saved,'candidate':row}
            approved[row['kind']].append(saved['value'])
    active=[r for r in rows if r['candidate_id'] not in approvals]
    if active and sessions is None and config.get('tag_review', {}).get('enabled'):
        from learning_tag_model import CodexTagSessions
        sessions = CodexTagSessions(config['tag_review'], run, learning.session_id)
    original_ids=set(tags)
    author_id = None
    review_ids = set()
    rounds = int(config.get('tag_review', {}).get('max_revision_rounds', 1))
    if rounds not in (0, 1):raise ValueError('invalid_revision_limit')
    if active and sessions is not None and config.get('policy') and config.get('entry_store'):
        feedback = [dict(candidate_id=r['candidate_id'], action='revise', reason=r['previous_review'])
                    for r in active if r.get('return_count',0)>0 and r.get('previous_review')]
        for attempt in range(rounds+1):
            if not active:break
            request = dict(protocol_version=VERSION, candidates=active, tags=list(tags.values()),
                           feedback=feedback, max_revision_rounds=rounds,
                           timeout_seconds=config.get('tag_review', {}).get('timeout_seconds', 180))
            folder = run/f'review/tag-admission/round-{attempt}'
            retry=[];next_feedback=[]
            try:
                author = invoke(sessions, 'author', request, folder/'author')
                if author_id and author['native_session_id'] != author_id:
                    raise ValueError('author_session_changed')
                author_id=author['native_session_id']
                proposals = author['result']['entries']
                by_id = {r['candidate_id']: r for r in active}
                proposed_ids=[r['candidate_id'] for r in proposals]
                if len(set(proposed_ids))!=len(proposed_ids) or set(proposed_ids)-set(by_id):
                    raise ValueError('invalid_candidate_identity')
                review_rows = []
                for proposed in proposals:
                    key=proposed['candidate_id'];row=by_id[key]
                    if set(proposed)-{'candidate_id','action','tag_ids','new_tags','reason'}:
                        results[key]['reason']='invalid_author_fields';continue
                    if not proposed.get('reason'):raise ValueError('decision_reason_required')
                    if proposed['action'] == 'discard':
                        results[key].update(status='discarded', reason=proposed['reason']);continue
                    if proposed['action'] != 'assign':raise ValueError('invalid_author_action')
                    try:
                        validate_content(row['kind'], row['draft'], sources)
                    except (ValueError, KeyError, TypeError) as exc:
                        results[key].update(status='discarded', reason=str(exc),
                                            terminal_reason='invalid_original_content')
                        continue
                    review_rows.append({**row, 'proposal': proposed})
                if review_rows:
                    review = invoke(sessions, 'reviewer', {**request, 'candidates': review_rows}, folder/'reviewer')
                    native=review['native_session_id']
                    if native==author_id or native in review_ids:
                        raise ValueError('review_session_not_independent')
                    review_ids.add(native)
                    candidates={r['candidate_id']:r for r in review_rows}
                    decisions=review['result']['decisions'];keys=[d['candidate_id'] for d in decisions]
                    if len(set(keys))!=len(keys) or set(keys)-set(candidates):raise ValueError('invalid_decision_identity')
                    for decision in decisions:
                        key=decision['candidate_id'];row=candidates[key]
                        if set(decision)-{'candidate_id','action','reason'}:
                            results[key]['reason']='invalid_reviewer_fields';continue
                        if not decision.get('reason'):raise ValueError('decision_reason_required')
                        if decision['action']=='discard':
                            results[key].update(status='discarded',reason=decision['reason']);continue
                        if decision['action']=='revise':
                            count=results[key]['return_count']+1
                            revised={**by_id[key], 'return_count':count, 'previous_review':decision['reason']}
                            results[key].update(reason=decision['reason'],candidate=revised,return_count=count)
                            if count>rounds:
                                results[key].update(status='discarded',terminal_reason='review_return_limit')
                                continue
                            retry.append(revised);next_feedback.append(decision);continue
                        if decision['action']!='approve':raise ValueError('invalid_review_action')
                        try:
                            selection={'tag_ids':row['proposal']['tag_ids'],
                                       'new_tag_keys':[t['key'] for t in row['proposal']['new_tags']]}
                            ids=approve_tags(selection,row['proposal'],tags,original_ids)
                            value=validate_content(row['kind'],row['draft'],sources)
                        except (ValueError,KeyError,TypeError) as exc:
                            results[key]['reason']=str(exc);continue
                        name=value.get('term',value.get('surface_form',''))
                        value['id']=uuid.uuid5(uuid.NAMESPACE_URL,learning.account+'/'+learning.group+'/'+row['kind']+'/'+name).hex
                        source_id=f"learning:{learning.account}:{learning.group}:{row['kind']}:{value['id']}"
                        if any(r.get('source_id')==source_id for r in results.values()):
                            results[key]['reason']='duplicate_final_entry';continue
                        approved[row['kind']].append(value)
                        results[key].update(status='approved',reason=decision['reason'],tags=ids,source_id=source_id,
                            candidate=by_id[key],
                            content_sha256=hashlib.sha256(body(row['kind'],value).encode()).hexdigest(),
                            reviewer_native_session_id=native,value=value)
            except Exception as exc:
                for row in active:
                    result=results[row['candidate_id']]
                    if result['status']=='pending':
                        result['last_error']=type(exc).__name__+': '+str(exc)
                        if not result['candidate'].get('previous_review'):result['reason']=result['last_error']
                break
            active=retry;feedback=next_feedback
    record = dict(protocol_version=VERSION, account=learning.account, group=learning.group,
                  records=list(results.values()), tag_definitions=list(tags.values()),
                  sources={str(i):sources[str(i)] for r in results.values() if r['status'] in ('pending','approved')
                           for i in r['candidate']['draft']['source_ids']})
    write(run/'review/tag-admission.json', record)
    summary = {name:sum(r['status']==state for r in results.values()) for name,state in
               [('approved','approved'),('pending','pending'),('discarded','discarded')]}
    return approved, {**summary, 'evidence':str(run/'review/tag-admission.json')}
