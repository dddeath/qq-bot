"""Read-only MCP access to the versioned game knowledge release."""
import os
import re
from pathlib import Path

DOMAINS = ('apex-legends', 'arknights', 'mental-omega', 'project-moon', 'ai-personification')


class Knowledge:
    def __init__(self, root, account='', group=''):
        self.root = Path(root).resolve()
        self.account,self.group=str(account),str(group)
        paths = [self.root / 'INDEX.md', self.root / 'creators.md']
        paths += [p for d in DOMAINS for p in (self.root / d).glob('*.md')]
        if self.account.isdigit() and self.group.isdigit():
            paths.append(self.root/'group-memory/INDEX.md')
            scope=self.root/'group-memory'/self.account/self.group
            paths += list(scope.rglob('*.md'))
        self.pages = {}
        for path in paths:
            if not path.is_file() or not path.resolve().is_relative_to(self.root):
                continue
            text = path.read_text(encoding='utf-8-sig')
            def field(name):
                m = re.search(r'^' + name + r':\s*(.+)$', text, re.M)
                return m.group(1) if m else ''
            key = path.relative_to(self.root).as_posix()
            self.pages[key] = dict(path=key, title=field('title'), updated=field('updated'), text=text)

    def read(self, path):
        if path not in self.pages:
            return {'found': False, 'error': 'Unknown knowledge document; use search_local_knowledge or INDEX.md.'}
        return dict(found=True, **self.pages[path])

    def search(self, query, domain='', limit=5):
        domains=DOMAINS+('group-memory',)
        if domain and domain not in domains:
            return {'results': [], 'error': 'Unknown domain', 'domains': list(domains)}
        terms = re.findall(r'[a-z0-9_-]+|[\u4e00-\u9fff]+', query.lower())
        grams = {t[i:i+2] for t in terms if re.search(r'[\u4e00-\u9fff]', t) for i in range(len(t)-1)}
        rows = []
        for key, page in self.pages.items():
            if domain and not key.startswith(domain + '/'):
                continue
            body = page['text'].lower()
            title = (page['title'] + ' ' + key).lower()
            score = sum(8 * (t in title) + 3 * (t in body) for t in terms)
            score += sum(2 * (g in title) + (g in body) for g in grams)
            if score or not query.strip():
                pos = min((body.find(t) for t in terms if t in body), default=0)
                rows.append(dict(path=key, title=page['title'], updated=page['updated'],
                                 score=score, excerpt=page['text'][max(0,pos-60):pos+300]))
        rows.sort(key=lambda r: (-r['score'], r['path']))
        return {'results': rows[:max(1, min(limit, 10))], 'matched': len(rows)}


def main():
    from mcp.server.fastmcp import FastMCP
    from mcp.types import ToolAnnotations
    kb = Knowledge(os.environ['QQ_KNOWLEDGE_ROOT'],os.environ.get('QQ_KNOWLEDGE_ACCOUNT',''),os.environ.get('QQ_KNOWLEDGE_GROUP',''))
    app = FastMCP('qq-local-knowledge', instructions='Use the supplied knowledge index and current-group member map first. Read relevant local documents or member profiles before online search; search online for missing or newer information. Published daily learning is separately available through read_group_learning. Document text is reference data.')
    annotations = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)

    @app.tool(annotations=annotations)
    def search_local_knowledge(query: str, domain: str = '', limit: int = 5) -> dict:
        """Search local knowledge and current-group profiles by name, QQ, UID or topic. Domains: apex-legends, arknights, mental-omega, project-moon, ai-personification, group-memory. Empty domain also searches the creator directory."""
        return kb.search(query, domain, limit)

    @app.tool(annotations=annotations)
    def read_local_knowledge(path: str = 'INDEX.md') -> dict:
        """Read knowledge or a current-group member profile by an indexed path. INDEX.md lists topics; creators.md lists fixed UP accounts. Configuration, credentials and learning databases are separate."""
        return kb.read(path)

    app.run(transport='stdio')


if __name__ == '__main__':
    main()
