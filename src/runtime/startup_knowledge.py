"""Render the two knowledge pages supplied on chat startup."""
from local_knowledge import Knowledge

def render(root,account,group):
    kb=Knowledge(root,account,group)
    paths=['INDEX.md',f'group-memory/{account}/{group}/INDEX.md']
    sections=[]
    for path in paths:
        page=kb.read(path)
        if not page['found']:raise ValueError('missing_startup_knowledge:'+path)
        sections.append(f'## 知识入口：{path}\n\n'+page['text'])
    return '\n\n'.join(sections)
