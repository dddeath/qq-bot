"""Lossless, content-addressed review evidence with bounded, progressive reads."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def pointer_key(value):
    return str(value).replace('~', '~0').replace('/', '~1')


class ReviewMaterials:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.database = self.root / 'materials.sqlite3'

    @classmethod
    def create(cls, root, reports):
        self = cls(root)
        self.root.mkdir(parents=True, exist_ok=False)
        duplicates = 0
        images = []
        with closing(sqlite3.connect(self.database)) as db, db:
            db.executescript('''
                create table blocks (id text primary key, body text not null);
                create table roots (name text primary key, ref text not null);
                create table materials (id text primary key, section text, ref text, summary text);
            ''')

            def pack(value):
                nonlocal duplicates
                if isinstance(value, dict):
                    node = ['object', [[key, pack(item)] for key, item in value.items()]]
                elif isinstance(value, list):
                    node = ['array', [pack(item) for item in value]]
                else:
                    node = ['value', value]
                    # Some MCPs return identical data both as JSON text and as structuredContent.
                    # Share their object only when the exact original text can be reconstructed.
                    if isinstance(value, str) and len(value) >= 256:
                        try: parsed = json.loads(value)
                        except ValueError: parsed = None
                        if isinstance(parsed, (dict, list)):
                            for indent in (None, 2, 4):
                                for ascii_only in (False, True):
                                    for separators in (None, (',', ':')):
                                        fmt = dict(ensure_ascii=ascii_only, indent=indent, separators=separators)
                                        if json.dumps(parsed, **fmt) == value:
                                            node = ['json_text', pack(parsed), fmt]
                                            break
                                    if node[0] == 'json_text': break
                                if node[0] == 'json_text': break
                body = encoded(node)
                if len(body) < 160:
                    return ['inline', node]
                digest = hashlib.sha256(body.encode('utf-8')).hexdigest()
                inserted = db.execute('insert or ignore into blocks values (?,?)', (digest, body)).rowcount
                duplicates += int(not inserted)
                return ['ref', digest]

            def material(name, section, value, summary=None):
                ref = pack(value)
                db.execute('insert into materials values (?,?,?,?)',
                           (name, section, encoded(ref), encoded(summary or {})))

            for label, report in reports.items():
                db.execute('insert into roots values (?,?)', (label, encoded(pack(report))))
                for key, value in report.items():
                    if key != 'reads':
                        material(label + '/' + key, label, value)
                for i, read in enumerate(report.get('reads', []), 1):
                    name = f'{label}/reads/{i:03d}'
                    material(name, label + '/reads', read, dict(read_id=read.get('read_id', i),
                        tool=read.get('tool') or read.get('action', {}).get('kind'),
                        purpose=read.get('action', {}).get('purpose'), status=read.get('result', {}).get('status')))
                    for n, image in enumerate(read.get('result', {}).get('images', []), 1):
                        source = Path(image.get('path', ''))
                        entry = dict(id=f'{name}/image/{n}', material_id=name, source=image,
                                     status='missing', artifact=None)
                        if source.is_file():
                            data = source.read_bytes()
                            digest = hashlib.sha256(data).hexdigest()
                            dest = self.root / 'images' / digest
                            dest.parent.mkdir(exist_ok=True)
                            if not dest.exists(): dest.write_bytes(data)
                            entry.update(status='available', artifact=str(dest.relative_to(self.root)),
                                         sha256=digest, bytes=len(data))
                        images.append(entry)
            sections = {s: count for s, count in db.execute('select section,count(*) from materials group by section')}
            size, count = db.execute('select coalesce(sum(length(cast(body as blob))),0),count(*) from blocks').fetchone()
        # Image metadata is a separate directory; pixels are read only on request.
        (self.root / 'images.json').write_text(json.dumps(images, ensure_ascii=False, indent=2), encoding='utf-8')
        index = dict(version='review-materials-v1', directory=str(self.root), sections=sections,
                     images={'available':sum(i['status']=='available' for i in images),
                             'missing':sum(i['status']=='missing' for i in images)},
                     storage={'unique_blocks':count, 'block_bytes':size, 'duplicate_blocks':duplicates},
                     reading='list_review_materials -> read_review_material (JSON pointer or bounded JSON pages); read_review_image for pixels')
        (self.root / 'index.json').write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding='utf-8')
        return self

    def index(self):
        return json.loads((self.root / 'index.json').read_text(encoding='utf-8'))

    def _db(self):
        return sqlite3.connect(self.database.as_uri() + '?mode=ro', uri=True)

    def _decode(self, ref, db):
        node = json.loads(db.execute('select body from blocks where id=?', (ref[1],)).fetchone()[0]) if ref[0] == 'ref' else ref[1]
        kind, value = node[:2]
        if kind == 'object': return {key:self._decode(item, db) for key, item in value}
        if kind == 'array': return [self._decode(item, db) for item in value]
        if kind == 'json_text': return json.dumps(self._decode(value, db), **node[2])
        return value

    def reconstruct(self, name):
        with closing(self._db()) as db:
            row = db.execute('select ref from roots where name=?', (name,)).fetchone()
            if not row: raise ValueError('unknown_report')
            return self._decode(json.loads(row[0]), db)

    def list(self, section=None, offset=0, limit=8):
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 20:
            raise ValueError('invalid_material_page')
        if section is None: return self.index()
        with closing(self._db()) as db:
            rows = db.execute('select id,summary from materials where section=? order by id', (section,)).fetchall()
        return dict(section=section, total=len(rows), items=[dict(id=name, **json.loads(summary)) for name,summary in rows[offset:offset+limit]],
                    next_offset=offset+limit if offset+limit < len(rows) else None)

    def read(self, material_id, pointer='', offset=0, limit=6000, format='outline'):
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 6000 or format not in ('outline','json'):
            raise ValueError('invalid_material_page')
        with closing(self._db()) as db:
            row = db.execute('select ref from materials where id=?', (material_id,)).fetchone()
            if not row: raise ValueError('unknown_material')
            value = self._decode(json.loads(row[0]), db)
        if pointer:
            if not pointer.startswith('/'): raise ValueError('invalid_json_pointer')
            for key in pointer[1:].split('/'):
                key = key.replace('~1','/').replace('~0','~')
                try: value = value[int(key)] if isinstance(value,list) else value[key]
                except (KeyError,IndexError,TypeError,ValueError): raise ValueError('unknown_material_pointer') from None
        if format == 'outline' and isinstance(value,(dict,list)):
            entries = list(value.items()) if isinstance(value,dict) else list(enumerate(value))
            items = [{'key':key,'pointer':pointer+'/'+pointer_key(key),'type':type(item).__name__}
                     for key,item in entries[offset:offset+min(limit,20)]]
            return dict(material_id=material_id,pointer=pointer,items=items,total=len(entries),
                        next_offset=offset+len(items) if offset+len(items)<len(entries) else None,
                        offset_unit='entries',images=self.images(material_id))
        text = value if isinstance(value,str) and format=='outline' else json.dumps(value,ensure_ascii=False,indent=2)
        return dict(material_id=material_id,pointer=pointer,text=text[offset:offset+limit],total_chars=len(text),
                    next_offset=offset+limit if offset+limit<len(text) else None,offset_unit='characters')

    def images(self, material_id):
        return [i for i in json.loads((self.root/'images.json').read_text(encoding='utf-8')) if i['material_id']==material_id]

    def image(self, image_id):
        entries=json.loads((self.root/'images.json').read_text(encoding='utf-8'))
        entry=next((i for i in entries if i['id']==image_id),None)
        if entry is None:raise ValueError('unknown_review_image')
        if entry['status']!='available':raise ValueError('review_image_missing')
        path=(self.root/entry['artifact']).resolve()
        if not path.is_relative_to(self.root):raise ValueError('invalid_review_image_path')
        data=path.read_bytes()
        if hashlib.sha256(data).hexdigest()!=entry['sha256']:raise ValueError('review_image_changed')
        return entry,data
