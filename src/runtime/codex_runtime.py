"""Versioned Codex launch contract for stage-scoped knowledge tools."""
import json
from pathlib import Path


def contract():
    return json.loads((Path(__file__).resolve().parents[2] / 'config/codex-runtime.json').read_text(encoding='utf-8'))


def app_server_command(overrides):
    selected = contract()
    executable = 'codex'
    if overrides.get('features.' + selected['stage_catalog_feature']) is True:
        # Use the tested installation, not whichever CLI happens to be on PATH.
        executable = '"$HOME/.local/qq-bot-runtime/codex/' + selected['version'] + '/node_modules/.bin/codex"'
    command = ['bash', '-lc', 'source "$HOME/.local/qq-bot-runtime/env.sh"; exec ' + executable + ' app-server "$@"', 'context-runner']
    for key, value in overrides.items():
        command += ['-c', key + '=' + json.dumps(value)]
    return command
