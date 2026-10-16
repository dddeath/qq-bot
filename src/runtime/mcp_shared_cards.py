"""Extract display text and web links from QQ share cards without opening them."""
import json
from urllib.parse import urlsplit


def shared_card(kind, data):
    if kind == 'json':
        raw = data.get('data')
        if not isinstance(raw, str) or len(raw) > 65536:
            return None
        try:
            card = json.loads(raw)
        except (ValueError, RecursionError):
            return None
        if not isinstance(card, dict) or not isinstance(card.get('meta'), dict):
            return None
        meta = card['meta']
        detail = next((meta[key] for key in ('detail_1', 'news', 'detail') if isinstance(meta.get(key), dict)), None)
        if detail is None:
            return None
    elif kind == 'share':
        detail = data
    else:
        return None
    url = ''
    for key in ('qqdocurl', 'jumpUrl', 'url'):
        candidate = detail.get(key)
        if not isinstance(candidate, str) or len(candidate) > 2048:
            continue
        candidate = candidate.strip()
        try:
            parsed = urlsplit(candidate)
            if parsed.scheme in ('http', 'https') and parsed.hostname and not parsed.username and not parsed.password:
                url = candidate
                break
        except ValueError:
            continue
    if not url:
        return None
    title = detail.get('title', '')
    description = detail.get('desc', detail.get('content', ''))
    title = title[:500] if isinstance(title, str) else ''
    description = description[:1500] if isinstance(description, str) else ''
    return dict(type='share', title=title, description=description, url=url)
