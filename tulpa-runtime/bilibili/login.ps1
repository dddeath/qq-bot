$ErrorActionPreference = 'Stop'
$root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$key = Join-Path $root 'key\key_gpt.pem'
Write-Host 'Use the Bilibili app to scan and confirm login in this terminal. Credentials stay on the server.'
& ssh -t -i $key ubuntu@192.0.2.11 'source ~/.local/qq-bot-runtime/env.sh; cd /home/ubuntu/tulpa-test/runtime/bilibili-20261013/bilibili; node node_modules/@xzxzzx/bilibili-mcp/dist/cli.js setup'
exit $LASTEXITCODE
