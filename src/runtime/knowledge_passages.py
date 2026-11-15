"""Bounded verbatim passage spans; frozen max-child scoring."""
import re
from knowledge_retrieval_policy import PAGE_CHARACTERS, PASSAGES_PER_PARENT

def tok(text):
    text = text.casefold()
    words = re.findall(r'[a-z0-9]+', text)
    pairs = [s[i:i + 2] for s in re.findall(r'[\u3400-\u9fff]+', text)
             for i in range(len(s) - 1)]
    return set(words + pairs)


PAGE = PAGE_CHARACTERS


def cells(line):
    # Test delimiter syntax, leaving escaped pipes in cell contents intact.
    if '|' not in line:
        return []
    value = line.strip().removeprefix('|')
    if value.endswith('|') and not value.endswith(r'\|'):
        value = value[:-1]
    return re.split(r'(?<!\\)\|', value)


def table_at(rows, i):
    if i + 2 >= len(rows):
        return False
    header, rule = cells(rows[i][2]), cells(rows[i + 1][2])
    return (len(header) >= 2 and len(header) == len(rule)
            and all(re.fullmatch(r'\s*:?-{3,}:?\s*', cell) for cell in rule)
            and len(cells(rows[i + 2][2])) == len(header))


def windows(text, start, heading):
    for pos in range(0, len(text), PAGE - 24):
        part = text[pos:pos + PAGE]
        yield (start + pos, len(part), heading, part), (part,)
        if pos + PAGE >= len(text):
            break


def passage_blocks(entry):
    """Yield one readable source span and its searchable child strings."""
    text = entry['content']
    rows, offset = [], 0
    for line in text.splitlines(keepends=True):
        value = line.strip()
        start = offset + (line.index(value) if value else 0)
        rows.append((start, start + len(value), value))
        offset += len(line)
    heading, fence, i = '正文', None, 0
    while i < len(rows):
        start, end, value = rows[i]
        marker = re.match(r'^(\x60{3,}|~{3,})', value)
        if marker:
            run = marker[1]
            if fence is None:
                fence = run
            elif run[0] == fence[0] and len(run) >= len(fence):
                fence = None
        if fence is None and table_at(rows, i):
            header = value
            ncol = len(cells(header))
            j = i + 2
            while j < len(rows) and len(cells(rows[j][2])) == ncol and not table_at(rows, j):
                j += 1
            # Keep a short table whole. For a long table, pack contiguous data
            # rows into bounded pages; never offer a header-only page.
            k = i + 2
            while k < j:
                first = rows[k]
                if len(first[2]) > PAGE:
                    for page, focus in windows(first[2], first[0], heading):
                        yield page, tuple(heading + ' ' + child for child in (header, *focus))
                    k += 1
                    continue
                lo = start if k == i + 2 and first[1] - start <= PAGE else first[0]
                last = k
                while last + 1 < j and rows[last + 1][1] - lo <= PAGE:
                    last += 1
                hi = rows[last][1]
                # A table's subject is often given only by the enclosing heading.
                # Index that context with each child; return only verbatim source.
                children = (header, *(r[2] for r in rows[k:last + 1]))
                yield (lo, hi - lo, heading, text[lo:hi]), tuple(heading + ' ' + child for child in children)
                k = last + 1
            i = j
            continue
        if fence is None and value.startswith('#'):
            heading = value.strip('# ').strip()
        elif value and not re.fullmatch(r'[| :\-]+', value):
            yield from windows(value, start, heading)
        i += 1


def ranked_blocks(entry, query_terms):
    formal = entry['collection'] == 'formal'
    text = entry['content']
    sections = (passage_blocks(entry) if formal else
                [((0, min(PAGE, len(text)), entry['title'], text[:PAGE]), (text[:PAGE],))])
    title = tok(entry['title'])

    def score(block):
        section, children = block
        heading = tok(section[2]) - title
        def child_score(child):
            body = tok(child)
            return sum(weight * (2 * len(terms & heading) + len(terms & body)) / (.8 + len(terms)**.5)
                       for weight, terms in zip((2, 1, 1), query_terms))
        return max(map(child_score, children))
    return [(score(block), block[0]) for block in sorted(sections, key=lambda b: (-score(b), b[0][0]))]


def passages(entry, query_terms):
    return [section for _, section in ranked_blocks(entry, query_terms)[:PASSAGES_PER_PARENT]]


def diversify_sections(entry, selected, query_terms):
    """Offer one better-matched section without replacing primary or body-supported evidence."""
    if entry['collection'] != 'formal' or not selected:
        return selected
    result = list(selected)
    headings = {section[2] for section, _ in selected}
    terms = set().union(*query_terms)
    ranked = ranked_blocks(entry, query_terms)
    alternative = next(((score, section) for score, section in ranked
                        if score > 0 and section[2] not in headings), None)
    if alternative is None:
        return result
    score, section = alternative
    if len(result) < PASSAGES_PER_PARENT:
        return result + [(section, 'section_match')]
    scores = {(s[0], s[1]): value for value, s in ranked}
    # Replace at most one span: the other original spans may carry useful
    # semantic evidence despite having no literal query overlap.
    replaceable = [(scores.get((s[0], s[1]), 0), -i, i)
                   for i, (s, _) in enumerate(selected) if i > 0 and not terms & tok(s[3])]
    if replaceable:
        old_score, _, index = min(replaceable)
        if score > old_score:
            result[index] = (section, 'section_match')
    return result


def retain_literal_passage(entry, selected, evidence):
    """Keep the defining source span, rather than another mention of its name."""
    locations = [r for r in evidence if r.get('offset') is not None]
    if not locations:
        return selected
    if any(section[0] <= r['offset'] and r['end'] <= section[0] + section[1]
           for section, _ in selected for r in locations):
        return selected
    matches = []
    blocks = list(passage_blocks(entry))
    # Preserve adjacent name/gloss fields as one bounded source span when
    # the ordinary paragraph parser split them into separate lines.
    for record in locations:
        lo, hi = record['offset'], record['end']
        if (record['kind'] == 'alias' and 0 < hi-lo <= PAGE
                and not any(s[0] <= lo and hi <= s[0]+s[1] for s, _ in blocks)):
            matches.append((-1, lo, (lo, hi-lo, entry['title'], entry['content'][lo:hi])))
    for section, _ in blocks:
        lo, size, heading, _ = section
        for record in locations:
            overlap = (lo <= record.get('anchor', record['offset'])
                       and record.get('anchor_end', record['end']) <= lo+size)
            is_heading = (record['kind'] == 'heading' and heading.casefold().startswith(record['name'].casefold())
                          and lo >= record['end'])
            if overlap or is_heading:
                matches.append((0 if overlap else 1, lo, section))
    if not matches:
        return selected
    _, _, extra = min(matches, key=lambda item: (item[0], item[1]))
    return ([(extra, 'literal_coverage')] + [
        (section, method) for section, method in selected
        if not (extra[0] <= section[0] and section[0]+section[1] <= extra[0]+extra[1])
    ])[:PASSAGES_PER_PARENT]


def selected_passages(entry, query_terms, vector_match=None, *, literal_evidence=()):
    """Keep the primary source hit and offer distinct matched sections for optional reading."""
    lexical = passages(entry, query_terms)
    if vector_match is None:
        selected = diversify_sections(entry, [(section, 'lexical') for section in lexical], query_terms)
        return retain_literal_passage(entry, selected, literal_evidence)
    start = vector_match['offset']
    end = start + vector_match['limit']
    text = entry['content']
    if not 0 <= start < end <= len(text):
        raise ValueError('vector_match_out_of_bounds')
    raw = [section for section, _ in windows(text[start:end], start, entry['title'])]
    if len(raw) > PASSAGES_PER_PARENT:
        raise ValueError('vector_match_exceeds_passage_budget')
    anchored = []
    if entry['collection'] == 'formal':
        # Embedding windows can start in URLs or end inside a table row. Map
        # them back to bounded source blocks instead of slicing the window again.
        overlapping = []
        for section, _ in passage_blocks(entry):
            lo, size = section[:2]
            overlap = min(end, lo + size) - max(start, lo)
            if overlap > 0:
                overlapping.append((overlap, section))
        anchored = [section for _, section in sorted(
            overlapping, key=lambda item: (-item[0], item[1][0]))[:PASSAGES_PER_PARENT]]
        anchored.sort(key=lambda section: section[0])
    if not anchored:
        anchored = raw
    selected = [(section, 'vector_match') for section in anchored]
    for section in lexical:
        if len(selected) >= PASSAGES_PER_PARENT:
            break
        lo, size = section[:2]
        if any(p[0] <= lo and lo + size <= p[0] + p[1] for p, _ in selected):
            continue
        selected.append((section, 'lexical'))
    return retain_literal_passage(entry, diversify_sections(entry, selected, query_terms), literal_evidence)


TABLE_PREVIEW_CHARACTERS = 80
TABLE_PREVIEW_ROWS = 2
_CONDITION = re.compile(r'每|如果|若|当|仅|除非|否则|至少|至多|不超过|\b(?:if|when|unless|per|every|only)\b', re.I)


def _table_context(source, offset, length):
    """Find the original header and complete data rows within the selected span."""
    rows, pos = [], 0
    for line in source.splitlines(keepends=True):
        value = line.strip()
        lo = pos + (line.index(value) if value else 0)
        rows.append((lo, lo + len(value), value))
        pos += len(line)
    fence, i = None, 0
    end = offset + length
    while i < len(rows) and rows[i][0] < end:
        marker = re.match(r'^(\x60{3,}|~{3,})', rows[i][2])
        if marker:
            run = marker[1]
            if fence is None:
                fence = run
            elif run[0] == fence[0] and len(run) >= len(fence):
                fence = None
        if fence is None and table_at(rows, i):
            header = [v.strip() for v in cells(rows[i][2])]
            j = i + 2
            while j < len(rows) and len(cells(rows[j][2])) == len(header) and not table_at(rows, j):
                j += 1
            if rows[i][0] <= offset < rows[j - 1][1]:
                complete = [r[2] for r in rows[i + 2:j] if offset <= r[0] and r[1] <= end]
                partial = any(r[0] < end and r[1] > offset and not (offset <= r[0] and r[1] <= end)
                              for r in rows[i + 2:j])
                return header, complete, partial
            i = j
        else:
            i += 1
    return None


def table_preview(part, query_terms=(), *, source=None, offset=0):
    context = _table_context(source if source is not None else part, offset, len(part))
    if context is None:
        return None
    header, rows, partial = context
    if not rows:
        return '表：当前页为行片段，机制与条件需展开'

    def priority(row):
        terms = tok(row)
        score = sum(weight * len(query & terms) / (.8 + len(query)**.5)
                    for weight, query in zip((2, 1, 1), query_terms))
        # A query may match only the enclosing section. In that case, prefer
        # explicit conditional rules over a list of names or isolated values.
        conditional = bool(_CONDITION.search(' '.join(cells(row)[1:])))
        return -score, -conditional

    ordered = sorted(rows, key=priority)
    chosen = []
    for row in ordered[:TABLE_PREVIEW_ROWS]:
        values = [v.strip() for v in cells(row)]
        text = '｜'.join(f'{name}：{value}' if name else value for name, value in zip(header, values))
        trial = '表：' + '；'.join([*chosen, text])
        omitted = partial or len(chosen) + 1 < len(rows)
        if len(trial) + int(omitted) > TABLE_PREVIEW_CHARACTERS:
            if not chosen:
                # Never publish a number while cutting off its condition.
                subject = values[0][:24]
                return f'表：{subject}…（该行较长，机制与条件需展开）'
            break
        chosen.append(text)
    return '表：' + '；'.join(chosen) + ('…' if partial or len(chosen) < len(rows) else '')


def preview(part, query_terms=(), *, source=None, offset=0):
    table = table_preview(part, query_terms, source=source, offset=offset)
    return table if table is not None else part[:35]


