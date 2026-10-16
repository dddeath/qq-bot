"""Apply/restore narrow Tulpa hooks; retain original files in a new evidence directory."""
import argparse,difflib,json,shutil
from pathlib import Path

def apply(source,evidence):
    source=Path(source);evidence=Path(evidence);evidence.mkdir(parents=True,exist_ok=False)
    edits={}
    file=source/'chatlocal/mcp_chat_turns.py';before=file.read_text()
    needle="        if fresh:raise TurnRejected('stale',"
    if before.count(needle)!=1:raise ValueError('stale hook anchor differs')
    after=before.replace(needle,"        if fresh and not __import__('topic_tulpa').allow_fresh(self.chat,p,rows,now):raise TurnRejected('stale',")
    edits['chatlocal/mcp_chat_turns.py']=(before,after)
    file=source/'chatlocal/mcp_chat.py';before=file.read_text()
    needle="                if (now>=earliest and ((pending and"
    if before.count(needle)!=1:raise ValueError('wait hook anchor differs')
    after=before.replace(needle,"                if __import__('topic_tulpa').topic_ready(self,sid) or (now>=earliest and ((pending and")
    needle="kind='messages' if items else 'reactions'"
    if after.count(needle)!=1:raise ValueError('wait event anchor differs')
    after=after.replace(needle,"kind='messages' if items else 'topic_ready' if __import__('topic_tulpa').topic_ready(self,sid) and ready else 'reactions'")
    # Executed after all classes are defined, before the app constructs MCPChat.
    after+="\n# Optional topic routing for the configured live group.\nif __import__('os').environ.get('QQ_TOPIC_SETTINGS'):\n    __import__('topic_tulpa').install()\n"
    edits['chatlocal/mcp_chat.py']=(before,after)
    for name,(_,after) in edits.items():compile(after,name,'exec')
    for name in edits:
        dest=evidence/'original'/name;dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(source/name,dest)
    (evidence/'manifest.json').write_text(json.dumps(dict(source=str(source.resolve()),files=list(edits))))
    for name,(_,after) in edits.items():
        (source/name).write_text(after)
    (evidence/'hooks.patch').write_text(''.join(''.join(difflib.unified_diff(a.splitlines(True),b.splitlines(True),fromfile=n,tofile=n)) for n,(a,b) in edits.items()))

def rollback(evidence):
    evidence=Path(evidence);manifest=json.loads((evidence/'manifest.json').read_text())
    for name in manifest['files']:shutil.copy2(evidence/'original'/name,Path(manifest['source'])/name)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['apply','rollback']);p.add_argument('--source');p.add_argument('--evidence',required=True)
    a=p.parse_args()
    if a.action=='apply':apply(a.source,a.evidence)
    else:rollback(a.evidence)
