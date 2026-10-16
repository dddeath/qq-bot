"""Server adapters: read-only Tulpa collection and subscription-backed daily execution."""

import argparse,json,os,signal,sqlite3,subprocess,time,tomllib

from pathlib import Path

from contextlib import closing

from daily_learning import Learning,RETENTION,write,TZ,dt



def collector(learning,access,now=None):

    now=time.time() if now is None else now;cid=learning.account+':group:'+learning.group;messages=[]

    with closing(sqlite3.connect(Path(access).resolve().as_uri()+'?mode=ro',uri=True)) as d:

        for eid,mid,body,at,sid in d.execute('SELECT i.id,i.message_id,i.payload,i.at,i.session_id FROM chat_inbox i JOIN chat_sessions s ON s.id=i.session_id WHERE s.conversation_id=? AND i.at>=? ORDER BY i.at,i.id',(cid,now-RETENTION)):

            p=json.loads(body)

            if p.get('source')!='onebot_websocket' or p.get('is_self') or p.get('synthetic') or p.get('truncated'):continue

            text=''.join(s.get('text','') for s in p.get('segments',[]) if s.get('type')=='text')

            if not text.strip():continue

            messages.append(dict(id=str(mid),event_id=eid,at=at,text=text,sender=p.get('sender_id',''),session=sid,account=learning.account,group=learning.group))

    learning.collect(messages,[],now)

    return len(messages)



def import_existing(k,legacy,*,refresh=False):

    with k.db() as d:

        if not refresh and d.execute("SELECT 1 FROM settings WHERE key='legacy_import'").fetchone():return

    scope='qq:'+k.account+':group:'+k.group

    with closing(sqlite3.connect(Path(legacy).resolve().as_uri()+'?mode=ro',uri=True)) as src,k.db() as d:

        for id,situation,style,form in src.execute('SELECT e.id,e.situation,e.style,g.surface_form FROM expressions e LEFT JOIN expression_grounding g ON e.id=g.item_id AND e.scope=g.scope WHERE e.scope=? AND e.enabled=1',(scope,)):

            if not form:continue

            x=dict(id=id,situation=situation,surface_form=form,style=style)

            d.execute('INSERT OR IGNORE INTO published VALUES(?,?,?)',('expressions',id,json.dumps(x,ensure_ascii=False)))

        for id,term,meaning in src.execute("SELECT id,term,meaning FROM jargon WHERE scope=? AND enabled=1 AND is_jargon=1 AND meaning!=''",(scope,)):

            x=dict(id=id,term=term,meaning=meaning,usage='结合当前群语境使用',conditions='',kind='group')

            d.execute('INSERT OR IGNORE INTO published VALUES(?,?,?)',('meanings',id,json.dumps(x,ensure_ascii=False)))

        d.execute("INSERT OR REPLACE INTO settings VALUES('legacy_import','done')")



def model(batch,run,*,video_config=None,context_reader=None,frame_reader=None):

    from daily_video import enrich_videos

    images=enrich_videos(batch,run,video_config or {},context_reader=context_reader,frame_reader=frame_reader)

    from reading_review_runtime import daily_review

    review_result=daily_review(run,video_config or {})

    write(run/'review/reading-replay-summary.json',review_result)

    config=tomllib.loads((Path(os.environ['CODEX_HOME'])/'config.toml').read_text())

    prompt=(Path(__file__).resolve().parents[2]/'prompts/daily-learning.md').read_text(encoding='utf-8-sig')

    prompt+='\n本轮材料：\n'+json.dumps(batch,ensure_ascii=False)

    prompt+='\n已有学习：\n'+(run/'input/existing-learning.json').read_text()

    # A fresh thread and normal tier; no QQ or other MCP tools in this worker.

    cmd=['codex','-a','never','-m','gpt-6-astra','-c','model_reasoning_effort="medium"','-c','service_tier="default"','-c','web_search="disabled"','-c','features.image_generation=false']

    for name in config.get('mcp_servers',{}):cmd+=['-c',f'mcp_servers.{name}.enabled=false']

    cmd+=['exec','--skip-git-repo-check','--sandbox','read-only','--json','--output-schema',str((Path(__file__).resolve().parents[2]/'config/daily-learning-schema.json')),'--output-last-message',str(run/'review/answer.json')]

    for image in images:cmd+=['--image',image]

    cmd+=['--','-']

    (run/'review').mkdir(exist_ok=True);started=time.time()

    write(run/'execution.json',dict(command=cmd,started=started,model='gpt-6-astra',effort='medium',service_tier='default'))

    with (run/'execution.jsonl').open('x') as out,(run/'stderr.txt').open('x') as err:

        p=subprocess.Popen(cmd,stdin=subprocess.PIPE,stdout=out,stderr=err,cwd=run,text=True,encoding='utf-8',start_new_session=True)

        try:p.communicate(prompt,timeout=1800)

        except subprocess.TimeoutExpired:

            os.killpg(p.pid,signal.SIGTERM);p.wait(timeout=15);raise RuntimeError('daily_model_timeout')

    write(run/'execution-result.json',dict(exit_status=p.returncode,elapsed_seconds=time.time()-started))

    if p.returncode:raise RuntimeError('daily_model_failed')

    for line in (run/'execution.jsonl').read_text().splitlines():

        e=json.loads(line);i=e.get('item',{})

        if i.get('type') in ('command_execution','mcp_tool_call','web_search'):raise RuntimeError('unexpected_learning_tool_call')

    return json.loads((run/'review/answer.json').read_text())



def instance(config):

    return Learning(config['root'],config['account'],config['group'])



def collect_creators(k,cfg,now):

    from creator_learning import CreatorCollector

    from bilibili_creator_provider import BilibiliProvider

    path=cfg.get('creator_watchlist')

    if not path:return

    settings=json.loads(Path(path).read_text(encoding='utf-8-sig'))

    if not settings.get('enabled'):return

    c=CreatorCollector(k.root/'creator-collection',settings)

    result=c.run(settings['accounts'],BilibiliProvider({**settings,**cfg['bilibili_provider']}),now)

    c.deliver(k,time.time())

    if not result['state'].startswith('already_'):

        print(json.dumps({'creator_collection':result['state'],'run':result['run'],'materials':len(result['materials'])}),flush=True)



def main():

    p=argparse.ArgumentParser();p.add_argument('config');p.add_argument('--once',action='store_true');p.add_argument('--collect-only',action='store_true');a=p.parse_args()

    cfg=json.loads(Path(a.config).read_text());k=instance(cfg);os.umask(0o077)

    import_existing(k,cfg['legacy_db'])

    while True:

        collector(k,cfg['access_db'])

        if a.collect_only:print(json.dumps({'collected':True,'root':str(k.root)}));return

        now=time.time();local=dt.datetime.fromtimestamp(now,TZ)

        if a.once or (cfg.get('enabled') and local.hour>=cfg.get('hour',4)):

            try:

                collect_creators(k,cfg,now)

                video_config={**cfg.get('video_reading',{}),'bilibili_provider':cfg.get('bilibili_provider',{})}

                result=k.run(lambda batch,run:model(batch,run,video_config=video_config),time.time())

                if a.once or not result['state'].startswith('already_'):print(json.dumps(result,ensure_ascii=False),flush=True)

            except Exception as exc:

                print(json.dumps({'error':str(exc)}),flush=True)

                if a.once:raise

        if a.once:return

        time.sleep(60)

if __name__=='__main__':main()
