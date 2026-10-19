"""Compile repository guide sources into a versionable ToolProfile body."""
import argparse
import copy
import json
from pathlib import Path


def build(profile, root):
    root = Path(root)
    result = copy.deepcopy(profile)
    catalog = json.loads((root/'config/qq-capabilities.json').read_text(encoding='utf-8'))
    capabilities = {}
    for name, definition in catalog.items():
        tools = {server: [tool for tool in config.get('tools', []) if tool in definition['tools']]
                 for server, config in profile['servers'].items()}
        tools = {server: names for server, names in tools.items() if names}
        if not tools:
            continue
        capabilities[name] = dict(summary=definition['summary'], tools=tools, enabled=True,
            parameters={}, guide=(root/'prompts/qq-tools'/definition['guide']).read_text(encoding='utf-8'),
            sections={section:(root/'prompts/qq-tools'/path).read_text(encoding='utf-8')
                      for section,path in definition.get('sections',{}).items()})
        # Retain configured switches/parameters when recompiling guide text.
        previous=profile.get('qq_tools',{}).get('capabilities',{}).get(name,{})
        for key in ('enabled','parameters'):
            if key in previous:capabilities[name][key]=copy.deepcopy(previous[key])
    result['qq_tools'] = dict(core=(root/'prompts/qq-tools.md').read_text(encoding='utf-8'), capabilities=capabilities)
    return result


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--profile',type=Path,required=True,help='Existing ToolProfile body JSON')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[2])
    args=parser.parse_args()
    body=build(json.loads(args.profile.read_text(encoding='utf-8')),args.root)
    with args.output.open('x',encoding='utf-8') as target:
        json.dump(body,target,ensure_ascii=False,indent=2)


if __name__=='__main__':main()
