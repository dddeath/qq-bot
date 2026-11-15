"""Exact nominations grounded in named source fields, not arbitrary body tokens."""
import re

from knowledge_passages import PAGE, cells, table_at
from knowledge_ranking import STOP


# These labels describe document structure, never particular games or entities.
ALIAS_LABELS = {'别名', '简称', '代号', '叫法', '称呼', '术语',
                'alias', 'aliases', 'code', 'term'}
KEYWORD_LABELS = {'关键词与别名', '关键词', 'keywords'}
IDENTITY_LABELS = {'名称', '名字', '姓名', '角色', '对象', '作品', '文档',
                   'name', 'character', 'entity', 'title'}
URL = re.compile(r'https?://[^\s<>\]\)）]+', re.I)
LINK = re.compile(r'\[([^\]\n]+)\]\([^\)\n]*\)')


def visible_text(text):
    """Keep link labels; URL contents never supply identity evidence."""
    return URL.sub(' ', LINK.sub(r'\1', text)).replace('**', '').replace('`', '').strip()


def names(text):
    for part in re.split(r'[、／/,，;；\n]+', visible_text(text)):
        value = part.strip(' \t\"\'“”「」《》')
        if len(value) >= 2 and len(value) <= 80:
            yield value


def occurs(name, text):
    name, text = name.casefold(), visible_text(text).casefold()
    # Numeric identities still work next to Chinese words. A directly attached
    # quantity unit is value syntax, even if the same number names an object.
    boundary = r'a-z0-9_'
    left = rf'(?<![{boundary}])' if name[0].isascii() and name[0].isalnum() else ''
    right = rf'(?![{boundary}])' if name[-1].isascii() and name[-1].isalnum() else ''
    for match in re.finditer(left + re.escape(name) + right, text):
        if name.isdecimal() and re.match(
                r'\s*(?:[.%％]|[个件次枚张秒分时天年月元块人米克斤吨升度岁万亿]|小时|分钟|毫秒)', text[match.end():]):
            continue
        return True
    return False


def identity_records(entry):
    """Read current title, named headings, definition fields and typed table cells.

    All offsets refer to unmodified source. A typed entity row is weaker than
    an explicit alias mapping and needs local query support at nomination time.
    """
    records = []
    text = entry['content']

    def add(value, kind, start, end, context):
        for name in names(value):
            source = URL.sub(lambda m: ' '*len(m[0]), text[start:end])
            anchor = re.search(re.escape(name), source, re.I)
            records.append(dict(name=name, kind=kind, offset=start,
                                end=end, anchor=start+anchor.start() if anchor else start,
                                anchor_end=start+anchor.end() if anchor else end,
                                context=visible_text(context)))

    # A title is one name, not a bag of its constituent words.
    title = visible_text(entry['title'])
    if len(title) >= 2:
        records.append(dict(name=title, kind='title', offset=None, end=None, context=title))
    rows, offset = [], 0
    for raw in text.splitlines(keepends=True):
        value = raw.strip()
        start = offset + (raw.index(value) if value else 0)
        rows.append((start, start + len(value), value))
        offset += len(raw)
    heading, fence, i = '', None, 0
    while i < len(rows):
        start, end, value = rows[i]
        marker = re.match(r'^(\x60{3,}|~{3,})', value)
        if marker:
            run = marker[1]
            if fence is None:
                fence = run
            elif run[0] == fence[0] and len(run) >= len(fence):
                fence = None
            i += 1
            continue
        if fence is not None:
            i += 1
            continue
        if table_at(rows, i):
            header = [visible_text(c).strip().casefold() for c in cells(value)]
            identity = [(col, 'alias' if label in ALIAS_LABELS else 'entity')
                        for col, label in enumerate(header)
                        if label in ALIAS_LABELS | IDENTITY_LABELS | KEYWORD_LABELS]
            j = i + 2
            while j < len(rows) and len(cells(rows[j][2])) == len(header):
                lo, hi, row = rows[j]
                for col, kind in identity:
                    add(cells(row)[col], kind, lo, hi, heading+' '+value+' '+row)
                j += 1
            i = j
            continue
        h = re.match(r'^#{1,6}\s+(.+)', value)
        if h:
            heading = visible_text(h[1])
            # Preserve full heading names; do not turn each heading word into
            # an entity. A colon can separate a named subject from its gloss.
            name = re.split(r'[:：]', heading, maxsplit=1)[0]
            if len(name) >= 2:
                following = []
                for _, _, next_line in rows[i+1:]:
                    if next_line.startswith('#') or (not next_line and following):
                        break
                    if next_line:
                        following.append(next_line)
                records.append(dict(name=name, kind='heading', offset=start, end=end,
                                    context=heading+' '+' '.join(following)[:280]))
        else:
            clean = visible_text(value)
            field = re.match(r'^[-*]?\s*([^:：]{1,20})[:：]\s*(.+)$', clean)
            if field and field[1].strip().casefold() in ALIAS_LABELS:
                # A name field followed immediately by its gloss is one
                # readable definition, even when they occupy separate lines.
                if i+1 < len(rows) and re.match(r'^(?:含义|释义|定义|对应名称|meaning|definition)\s*[:：]', visible_text(rows[i+1][2]), re.I):
                    end = min(rows[i+1][1], start+PAGE)
                add(field[2], 'alias', start, end, clean)
            elif field and re.search(r'别名|简称|代号|称呼', field[2]):
                add(field[1], 'alias', start, end, clean)
        i += 1
    return records


def locally_supported(query, record):
    if record['kind'] not in ('entity', 'heading'):
        return True
    name = record['name']
    residual = visible_text(query).casefold().replace(name.casefold(), '')
    lookup = re.sub(r'是谁|是什么|什么意思|含义|解释|介绍|简介|[\s?？:：,，。!！]+', '', residual)
    if not lookup:
        return True
    # For a named table row, only the same row, its column headings and its
    # enclosing heading can support the relation requested by the query.
    import jieba
    required = {word for word in jieba.cut(residual, HMM=False)
                if len(word) >= 2 and re.fullmatch(r'\w+', word) and word not in STOP}
    supported = {word for word in required if word in record['context'].casefold()}
    # Exact priority needs a majority of the non-name query clues locally
    # supported. A generic shared word alone is not sufficient for a long ask.
    return bool(required) and len(supported) * 2 >= len(required)


def nominate(query, entries, eligible, limit, cache):
    matches, evidence = {}, {}
    for key in sorted(eligible):
        item = entries[key]
        signature = (item['title'], item['content'])
        if key not in cache or cache[key][0] != signature:
            cache[key] = (signature, identity_records(item))
        for record in cache[key][1]:
            if not occurs(record['name'], query) or not locally_supported(query, record):
                continue
            term = record['name'].casefold()
            matches.setdefault(term, set()).add(key)
            evidence.setdefault(key, []).append(record)
    matches = {term: sorted(keys) for term, keys in matches.items() if len(keys) <= limit}
    nominated = {key for keys in matches.values() for key in keys}
    if len(nominated) > limit:
        nominated = set()
    evidence = {key: [r for r in evidence[key] if key in matches.get(r['name'].casefold(), ())]
                for key in sorted(nominated)}
    return nominated, matches, evidence
