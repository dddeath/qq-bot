"""Publish only video MCP config and the background-work skill; no service restart."""
import argparse,datetime,hashlib,json,os,pathlib,shutil,tempfile,tomllib,uuid

def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def atomic(path,data):
    temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    temp.write_bytes(data);temp.chmod(0o600);os.replace(temp,path)

def rollback(evidence,apply=False):
    manifest=json.loads((evidence/'deployment.json').read_text())
    for item in manifest['files']:
        target=pathlib.Path(item['target'])
        if digest(target)!=item['after']:raise RuntimeError('Target changed after deployment: '+str(target))
        if digest(evidence/item['backup'])!=item['before']:raise RuntimeError('Backup changed')
    if apply:
        for item in manifest['files']:atomic(pathlib.Path(item['target']),(evidence/item['backup']).read_bytes())
    return {'validated':True,'applied':apply}

def deploy(base,home,release):
    evidence=base/'evidence'/('video-deploy-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'-'+uuid.uuid4().hex[:8])
    evidence.mkdir(mode=0o700)
    config=home/'config.toml';skill=home/'skills/qq-background-work/SKILL.md'
    old=config.read_text();parsed=tomllib.loads(old)
    if 'video_frames' in parsed.get('mcp_servers',{}):raise RuntimeError('video_frames already configured; inspect before publishing again')
    env={'QQ_VIDEO_PYTHON':str(release/'venv/bin/python'),'QQ_VIDEO_EVIDENCE':str(base/'evidence/video-frames'),'YUEYING_OUT_DIR':str(base/'video-cache'),'YUEYING_MAX_JOBS':'1','YUEYING_JOB_TIMEOUT':'600','QQ_VIDEO_BILIBILI':str(base/'runtime/bilibili-fix-20261013T233821842/bilibili')}
    block='\n[mcp_servers.video_frames]\ncommand = '+json.dumps('/home/ubuntu/.local/qq-bot-runtime/node-v24.21.0-linux-x64/bin/node')+'\nargs = ['+json.dumps(str(release/'server.mjs'))+']\nenabled_tools = ["watch_video", "sample_video_frames", "get_frames", "get_frame_at"]\ntool_timeout_sec = 120\n[mcp_servers.video_frames.env]\n'+''.join(k+' = '+json.dumps(v)+'\n' for k,v in env.items())
    updated=old+block
    checked=tomllib.loads(updated);checked['mcp_servers'].pop('video_frames');assert checked==parsed
    items=[]
    for target,data in [(config,updated.encode()),(skill,(release/'SKILL.md').read_bytes())]:
        backup=f'{len(items)}.before';shutil.copy2(target,evidence/backup)
        items.append({'target':str(target),'backup':backup,'before':digest(target),'after':hashlib.sha256(data).hexdigest()})
    (evidence/'deployment.json').write_text(json.dumps({'files':items,'release':str(release)},indent=2))
    for item,data in zip(items,[updated.encode(),(release/'SKILL.md').read_bytes()]):
        target=pathlib.Path(item['target']);assert digest(target)==item['before'];atomic(target,data)
    # Execute rollback against isolated copies and compare exact bytes.
    with tempfile.TemporaryDirectory() as temp:
        sandbox=pathlib.Path(temp);test={'files':[]}
        for item in items:
            copy=dict(item);copy['target']=str(sandbox/(item['backup']+'.target'))
            shutil.copy2(item['target'],copy['target']);shutil.copy2(evidence/item['backup'],sandbox/item['backup']);test['files'].append(copy)
        (sandbox/'deployment.json').write_text(json.dumps(test));result=rollback(sandbox,True)
        assert all(digest(pathlib.Path(i['target']))==i['before'] for i in test['files'])
    (evidence/'rollback-verification.json').write_text(json.dumps(result|{'isolated_copy':True,'exact_restoration':True}))
    (evidence/'video-config.patch').write_text(block)
    shutil.copy2(__file__,evidence/'deploy.py')
    print(evidence)

if __name__=='__main__':
    os.umask(0o077)
    p=argparse.ArgumentParser();p.add_argument('--rollback',type=pathlib.Path);p.add_argument('--apply',action='store_true');a=p.parse_args()
    if a.rollback:print(json.dumps(rollback(a.rollback,a.apply)))
    else:deploy(pathlib.Path('/home/ubuntu/tulpa-test'),pathlib.Path('/home/ubuntu/.local/qq-bot-runtime/codex-home'),pathlib.Path(__file__).resolve().parent)
