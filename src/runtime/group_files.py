"""Owner-gated group files; independent of Tulpa's chat process."""
from contextlib import closing
import json
import sqlite3
import time
from pathlib import Path

LIMIT = 16 * 1024 * 1024

class GroupFiles:
    def __init__(self, chat_db, storage, conversation, owner, api, stream):
        self.chat_db, self.root = Path(chat_db), Path(storage)
        self.conversation, self.owner = conversation, owner
        self.api, self.stream = api, stream
        self.root.mkdir(parents=True, exist_ok=True)

    def authorize(self, session_id, event_id, action=''):
        with closing(sqlite3.connect(f'{self.chat_db.resolve().as_uri()}?mode=ro', uri=True)) as db:
            row = db.execute('SELECT conversation_id,active FROM chat_sessions WHERE id=?', (session_id,)).fetchone()
            event = db.execute('SELECT payload FROM chat_inbox WHERE id=? AND session_id=? AND delivered=1', (event_id, session_id)).fetchone()
        if not row or row != (self.conversation, 1) or not event:
            raise PermissionError('Active group and delivered request required')
        p = json.loads(event[0])
        if (p.get('sender_id') != self.owner or p.get('is_self') or p.get('source') != 'onebot_websocket'
                or p.get('conversation_id') != self.conversation or not 0 <= time.time()-p.get('received_at', 0) <= 1800):
            raise PermissionError('Only the owner can request group files')
        text = ''.join(s.get('text', '') for s in p.get('segments', []) if s.get('type') == 'text')
        words = {'upload': ('上传',), 'download': ('下载',), '': ('文件', '上传', '下载')}
        if not any(w in text for w in words[action]):
            raise PermissionError('Explicit file request required in owner message')
        return int(self.conversation.split(':')[-1])

    def list_files(self, session_id, event_id, folder_id=''):
        group = self.authorize(session_id, event_id)
        action = 'get_group_files_by_folder' if folder_id else 'get_group_root_files'
        args = dict(group_id=group)
        if folder_id: args['folder_id'] = folder_id
        return self.api(action, args)

    def download(self, session_id, event_id, file_id, folder_id=''):
        import uuid
        group = self.authorize(session_id, event_id, 'download')
        files = self.list_files(session_id, event_id, folder_id).get('files', [])
        item = next((f for f in files if f.get('file_id') == file_id), None)
        if not item or type(item.get('file_size')) is not int or not 0 <= item['file_size'] <= LIMIT:
            raise ValueError('File missing or larger than 16 MiB')
        url = self.api('get_group_file_url', dict(group_id=group, file_id=file_id, busid=item.get('busid', 0)))['url']
        aid = uuid.uuid4().hex
        part, target = self.root / (aid+'.part'), self.root / (aid+'.bin')
        size = 0
        chunks = self.stream(url)
        try:
            with part.open('xb') as f:
                for chunk in chunks:
                    size += len(chunk)
                    if size > LIMIT: raise ValueError('Download exceeds 16 MiB')
                    f.write(chunk)
            self.authorize(session_id, event_id, 'download')
            part.replace(target)
        finally:
            if hasattr(chunks, 'close'): chunks.close()
            part.unlink(missing_ok=True)
        record = dict(artifact_id=aid, name=item['file_name'], size=size, group=self.conversation)
        (self.root/(aid+'.json')).write_text(json.dumps(record), encoding='utf-8')
        return record

    def artifacts(self, session_id, event_id):
        self.authorize(session_id, event_id)
        return [json.loads(p.read_text(encoding='utf-8')) for p in self.root.glob('*.json')]

    def upload(self, session_id, event_id, artifact_id):
        import re, hashlib
        group = self.authorize(session_id, event_id, 'upload')
        if not re.fullmatch('[a-f0-9]{32}', artifact_id): raise ValueError('Invalid artifact ID')
        meta = json.loads((self.root/(artifact_id+'.json')).read_text(encoding='utf-8'))
        path = self.root/(artifact_id+'.bin')
        if meta['group'] != self.conversation or path.is_symlink(): raise ValueError('Wrong artifact scope')
        with path.open('rb') as f: raw = f.read(LIMIT+1)
        if len(raw) > LIMIT: raise ValueError('Upload exceeds 16 MiB')
        name = meta['name'].replace('\\', '/').split('/')[-1]
        if not name or name in ('.', '..') or any(ord(c)<32 for c in name): raise ValueError('Invalid filename')
        key = hashlib.sha256((session_id+':'+str(event_id)+':'+artifact_id).encode()).hexdigest()
        ops = self.root/'operations';ops.mkdir(exist_ok=True)
        receipt = ops/(key+'.json')
        try:
            with receipt.open('x', encoding='utf-8') as f: json.dump(dict(state='UNKNOWN', artifact_id=artifact_id), f)
        except FileExistsError:
            return json.loads(receipt.read_text(encoding='utf-8'))
        # Freeze the size-checked bytes handed to QQ.
        outgoing = ops/(key+'.upload');outgoing.write_bytes(raw)
        try:
            self.authorize(session_id, event_id, 'upload')
            result = self.api('upload_group_file', dict(group_id=group, file=str(outgoing.resolve()), name=name))
            record = dict(state='SUCCEEDED', artifact_id=artifact_id, receipt=result)
        except Exception:
            record = dict(state='UNKNOWN', artifact_id=artifact_id, note='No reliable upload receipt; no automatic retry')
        receipt.write_text(json.dumps(record), encoding='utf-8')
        return record

    def import_exports(self, session_id, event_id, roots):
        import hashlib
        self.authorize(session_id, event_id)
        items = []
        for root in roots:
            root = Path(root).resolve()
            for path in sorted(root.glob('*')):
                if path.is_symlink() or not path.is_file() or path.stat().st_size > LIMIT: continue
                with path.open('rb') as f: raw = f.read(LIMIT+1)
                if len(raw) > LIMIT: continue
                aid = hashlib.sha256((self.conversation+'\0'+path.name+'\0').encode()+raw).hexdigest()[:32]
                target = self.root/(aid+'.bin')
                if not target.exists(): target.write_bytes(raw)
                record = dict(artifact_id=aid, name=path.name, size=len(raw), group=self.conversation)
                (self.root/(aid+'.json')).write_text(json.dumps(record), encoding='utf-8')
                items.append(record)
        return items
