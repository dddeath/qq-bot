$ErrorActionPreference = 'Stop'
& ssh -n -i E:\qq-bot\key\key_gpt.pem -o BatchMode=yes ubuntu@192.0.2.11 'python3 /home/ubuntu/tulpa-test/runtime/control_current.py report'
if ($LASTEXITCODE -ne 0) { throw 'report command failed' }
