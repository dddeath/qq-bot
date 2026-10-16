$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$node = (Get-Command node -ErrorAction Stop).Source
$dir = Join-Path $root '.local\qq-ws-probe'
New-Item -ItemType Directory -Path $dir -Force | Out-Null
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
& icacls $dir /inheritance:r /grant:r "${identity}:(OI)(CI)F" 'SYSTEM:(OI)(CI)F' | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Private output directory ACL setup failed' }
. (Join-Path $root 'scripts\qq-credentials.ps1')
$credentials = Get-QqCredentials -Root $root
$oldId = $env:QQ_PROBE_APP_ID
$oldSecret = $env:QQ_PROBE_APP_SECRET
try {
  $env:QQ_PROBE_APP_ID = $credentials.appId
  $env:QQ_PROBE_APP_SECRET = $credentials.appSecret
  & $node (Join-Path $PSScriptRoot 'run.mjs')
  $code = $LASTEXITCODE
} finally {
  $env:QQ_PROBE_APP_ID = $oldId
  $env:QQ_PROBE_APP_SECRET = $oldSecret
  $credentials = $null
}
exit $code
