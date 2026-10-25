"""Publish clean learning through the same EntryStore CRUD used by knowledge MCP."""
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from knowledge_catalog import KnowledgeCatalog
from knowledge_tag_publish import prepare_update, publish_candidate, write_json


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
    snapshot = KnowledgeCatalog(Path(run)/"no-formal-source", learning.account,
        learning.group, learning.root.parents[2]).export_snapshot()
    entries = [e for e in snapshot["entries"] if e["source"] == "published_learning"]
    if snapshot["sources"].get("published_learning") != "available":
        raise ValueError("learning_publication_source_unavailable")
    folder = Path(run)/"tag-publication"/(datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")+"-"+uuid.uuid4().hex[:8])
    prepared = prepare_update(target, mappings, entries, policy, annotations, folder)
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
