"""Run chronological topic decisions without touching any live chat."""
import argparse,json,os,shutil
from pathlib import Path
from topic_state import TopicState,Limits
from topic_replay import replay,new_run
from topic_codex import CodexProvider
from topic_dialogue import load_member_profiles

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--input',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--config',type=Path,default=Path(__file__).with_name('topic-replay-config.json'))
    p.add_argument('--seed',type=int,default=7)
    p.add_argument('--member-root',type=Path,help='Read identity fields from group-memory/account/group/members/*.md')
    a=p.parse_args();os.umask(0o077)
    config=json.loads(a.config.read_text(encoding='utf-8'))
    for key in ('group_limits','topic_limits'):config[key]=Limits(**config[key])
    run=new_run(a.output)
    (run/'source').mkdir()
    for name in ('topic_state.py','topic_replay.py','topic_codex.py','topic_dialogue.py','replay_topics.py'):
        shutil.copy2(Path(__file__).with_name(name),run/'source'/name)
    result=replay(json.loads(a.input.read_text(encoding='utf-8')),CodexProvider('maintainer',run/'calls'),
                  CodexProvider('main',run/'calls'),run/'reports',state=TopicState(**config),seed=a.seed,
                  member_profiles=load_member_profiles(a.member_root) if a.member_root else None)
    (run/'report-path.txt').write_text(str(result))
    print(json.dumps(dict(run=str(run),report=str(result))))
