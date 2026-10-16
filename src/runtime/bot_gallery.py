"""Resolve a bot-owned gallery without granting access to any chat or send action."""
from contextlib import closing
import json
import sqlite3
from pathlib import Path


def resolve_gallery(config, conversation_id):
    ref = config.get('bot_gallery')
    if ref is None:
        return config if conversation_id in config.get('conversation_ids', []) else None
    # Bot ownership is live configuration; native chat threads keep their own context.
    database = Path(ref['database']).resolve()
    with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as db:
        row = db.execute(
            "SELECT body FROM configurations WHERE kind='bot' AND id=? ORDER BY version DESC LIMIT 1",
            (ref['bot_id'],),
        ).fetchone()
    if row is None:
        return None
    bot = json.loads(row[0])
    account, separator, group = conversation_id.partition(':group:')
    if not separator or not group or str(bot['account_id']) != account:
        return None
    return bot.get('gallery')

