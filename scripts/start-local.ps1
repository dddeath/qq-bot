$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$node = (Get-Command node -ErrorAction Stop).Source
& $node (Join-Path $PSScriptRoot 'probe.mjs') setup
if ($LASTEXITCODE -ne 0) { throw 'Local configuration failed' }
$local = Join-Path $root '.local'
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
& icacls $local /inheritance:r /grant:r "${identity}:(OI)(CI)F" 'SYSTEM:(OI)(CI)F' | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Setting local credential directory ACL failed' }
$config = Get-Content (Join-Path $local 'config.json') -Raw | ConvertFrom-Json
foreach ($port in @($config.mcpPort, $config.adminPort)) {
  if (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue) { throw "Port $port is already in use; inspect before restarting." }
}
$process = Start-Process -FilePath $node -ArgumentList @('"' + (Join-Path $root 'src\server.mjs') + '"') -WorkingDirectory $root -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $local 'server.stdout.log') -RedirectStandardError (Join-Path $local 'server.stderr.log')
@{ pid = $process.Id; startTime = $process.StartTime.ToUniversalTime().ToString('o') } | ConvertTo-Json | Set-Content (Join-Path $local 'server-process.json') -Encoding UTF8
for ($i=0; $i -lt 30; $i++) {
  Start-Sleep -Milliseconds 200
  try { $health = Invoke-RestMethod "http://127.0.0.1:$($config.mcpPort)/healthz"; if ($health.service -eq 'dot-event-probe') { Write-Output "Local probe ready. PID=$($process.Id). MCP=http://127.0.0.1:$($config.mcpPort)/mcp"; exit 0 } } catch {}
}
throw 'Server did not become healthy; inspect .local/server.stderr.log'
