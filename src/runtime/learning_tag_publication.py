"""Publish clean learning through the same EntryStore CRUD used by knowledge MCP."""
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from learning_tag_admission import body
from knowledge_tag_publish import prepare_update, publish_candidate, write_json, digest


def publish_learning(learning, config, run):
    if not config:
        return {"status": "not_configured"}
    target = Path(config["entry_store"])
    base = json.loads(target.read_text(encoding="utf-8-sig"))
    mappings = base.get("import_mappings")
    if mappings is None:
        mapping_path = config.get("mappings")
        if mapping_path:
            mappings = json.loads(Path(mapping_path).read_text(encoding="utf-8-sig"))
        elif not base["entries"]:
            mappings = []
        else:
            raise ValueError("import_mappings_required")
    policy = json.loads(Path(config["policy"]).read_text(encoding="utf-8-sig"))
    annotations = json.loads(Path(config["annotations"]).read_text(encoding="utf-8-sig")) if config.get("annotations") else {}
    admission_path = Path(run)/"review/tag-admission.json"
    if not admission_path.exists():
        return {"status": "pending_review", "reason": "tag_admission_missing"}
    admission = json.loads(admission_path.read_text(encoding="utf-8-sig"))
    if admission.get('account') != learning.account or admission.get('group') != learning.group:
        raise ValueError('admission_scope_mismatch')
    accepted = {r['source_id']: r for r in admission['records'] if r['status']=='approved'}
    entries=[]
    for key,reviewed in accepted.items():
        kind=reviewed['candidate']['kind'];value=reviewed['value']
        expected=f"learning:{learning.account}:{learning.group}:{kind}:{value['id']}"
        if key!=expected:raise ValueError('admission_entry_scope_mismatch')
        text=body(kind,value)
        entries.append(dict(entry_id=key,title=value.get('term',value.get('surface_form')),
            text=text,source='published_learning',domain='group-learning',version=digest(text.encode()),
            scope={'account':learning.account,'group':learning.group}))
    if not entries:
        return {"status": "no_approved_entries"}
    definitions = {t['id']:t for t in admission['tag_definitions']}
    definitions.update(base.get('tags', {}))
    used={tag for reviewed in accepted.values() for tag in reviewed.get('tags',[])}
    if not used<=definitions.keys():raise ValueError('unknown_approved_tag')
    definitions={tag:definitions[tag] for tag in used}
    for entry in entries:
        reviewed = accepted[entry['entry_id']]
        if not reviewed.get('tags') or digest(entry['text'].encode()) != reviewed['content_sha256']:
            raise ValueError('admission_content_changed')
        annotations[entry['entry_id']] = dict(tags=reviewed['tags'], reason=reviewed['reason'],
            content_sha256=reviewed['content_sha256'])
    if set(accepted) != {e['entry_id'] for e in entries}:
        raise ValueError('approved_entry_missing')
    folder = Path(run)/"tag-publication"/(datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")+"-"+uuid.uuid4().hex[:8])
    prepared = prepare_update(target, mappings, entries, policy, annotations, folder,
                              reviewed_tags=definitions)
    if prepared["counts"].get("conflict"):
        result = dict(status="conflict", directory=str(folder), counts=prepared["counts"])
    else:
        result = publish_candidate(folder, target, prepared["candidate_sha256"])
        result = {**result, "directory": str(folder), "counts": prepared["counts"]}
    write_json(Path(run)/"tag-publication.json", result)
    return result


def publish_pending(learning, config, run):
    """Publication failure never changes the completed learning batch."""
    if not config:
        return {"status": "not_configured"}
    receipt = Path(run)/"tag-publication.json"
    if receipt.exists():
        previous = json.loads(receipt.read_text(encoding="utf-8"))
        if previous.get("status") == "published":
            return previous
    try:
        return publish_learning(learning, config, run)
    except Exception as exc:
        result = {"status": "failed", "error": str(exc)}
        Path(run).mkdir(parents=True, exist_ok=True)
        write_json(receipt, result)
        return result
