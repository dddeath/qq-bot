"""Small local synonym vocabulary for emotion and scene sticker lookup."""
import re

SYNONYMS = (
    ('黑历史', '糗照', '自嘲'),
    ('开心', '高兴', '快乐', '欢乐'),
    ('得意', '嘚瑟', '骄傲'),
    ('疑惑', '疑问', '问号', '不解'),
    ('困', '困倦', '困了', '睡觉', '晚安'),
    ('等待', '等候', '稍等'),
    ('尴尬', '尬住', '尬笑'),
    ('招呼', '打招呼', '问好', '挥手'),
)


def search_score(query, text):
    query, text = query.strip().casefold(), text.casefold()
    if not query:
        return 1
    if query in text:
        return 100
    # Space-separated concepts must all match; within a concept allow synonyms.
    words = re.split(r'\s+', query)
    for word in words:
        variants = {word}
        for group in SYNONYMS:
            if word in group:
                variants.update(group)
        if not any(value in text for value in variants):
            return 0
    return 10
