"""Subscription review session with progressively disclosed, immutable evidence."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import tomllib
from review_materials import ReviewMaterials
from review_materials_mcp import cli_arguments


def review(reports, root, seconds, settings, prompt, schema, *, response_instructions=None):
    root=Path(root);root.mkdir(parents=True,exist_ok=False)
    started=time.monotonic();deadline=time.time()+seconds
    materials=ReviewMaterials.create(root/'materials',reports)
    cfg=tomllib.loads((Path(os.environ['CODEX_HOME'])/'config.toml').read_text(encoding='utf-8'))
    options=settings.get('reading_review',{})
    command=['codex','-a','never','-m',options.get('model','gpt-6-astra'),
             '-c','model_reasoning_effort='+json.dumps(options.get('reasoning_effort','medium')),
             '-c','service_tier="default"','-c','web_search="disabled"',
             '-c','features.shell_tool=false','-c','features.image_generation=false']
    for name in cfg.get('mcp_servers',{}):command+=['-c',f'mcp_servers.{name}.enabled=false']
    command+=cli_arguments(materials.root,options.get('python',sys.executable),deadline)
    schema_path=root/'schema.json';schema_path.write_text(json.dumps(schema),encoding='utf-8')
    command+=['exec','--skip-git-repo-check','--sandbox','read-only','--json','--output-schema',str(schema_path),
              '--output-last-message',str(root/'answer.json'),'--','-']
    response_instructions=response_instructions or '留出整理评审的时间，来不及阅读的证据写入 limitations，相关分数填 null。逐项给出三类评审结论，明确实际依据。仅输出符合 schema 的评审 JSON。'
    model_prompt=prompt+f'''\n材料目录：{materials.root}
先用 list_review_materials 读取目录，再按当前任务需要展开材料。
read_review_material 默认返回字段目录，用 pointer 选择内容；正文按 next_offset 续读，图片用 read_review_image 获取像素。目录计数与图片路径本身不证明已经读过。
预算剩余 {max(0,seconds-(time.monotonic()-started)):.1f} 秒。材料读取回执包含剩余时间。
{response_instructions}
'''
    (root/'prompt.txt').write_text(model_prompt,encoding='utf-8')
    (root/'input.json').write_text(json.dumps({'materials_directory':str(materials.root),'deadline':deadline},ensure_ascii=False,indent=2),encoding='utf-8')
    code=None;error=None
    try:
        remaining=seconds-(time.monotonic()-started)
        if remaining<=0:raise TimeoutError('review_budget_exhausted')
        with (root/'execution.jsonl').open('x',encoding='utf-8') as out,(root/'stderr.txt').open('x',encoding='utf-8') as err:
            process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=out,stderr=err,cwd=root,text=True,encoding='utf-8',start_new_session=True)
            try:process.communicate(model_prompt,timeout=remaining)
            except subprocess.TimeoutExpired:
                if os.name=='posix':os.killpg(process.pid,signal.SIGKILL)
                else:process.kill()
                process.wait();code=process.returncode
                raise TimeoutError('review_budget_exhausted') from None
            code=process.returncode
        if code:raise RuntimeError('review_model_failed')
        return json.loads((root/'answer.json').read_text(encoding='utf-8'))
    except Exception as exc:
        error=str(exc);raise
    finally:
        (root/'execution-result.json').write_text(json.dumps({'command':command,'exit_status':code,
            'elapsed_seconds':time.monotonic()-started,'error':error,'materials_directory':str(materials.root)},ensure_ascii=False,indent=2),encoding='utf-8')
