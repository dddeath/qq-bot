param([switch]$DoctorOnly)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$config = Get-Content (Join-Path $root '.local\config.json') -Raw | ConvertFrom-Json
$binary = Join-Path $root '.tools\tunnel-client\tunnel-client.exe'
if (!(Test-Path -LiteralPath $binary)) { throw 'Official tunnel-client executable is missing' }
$ownedKey = $false
if (!$env:CONTROL_PLANE_API_KEY) {
  $secret = Read-Host 'Enter the tunnel runtime API Key (hidden; not saved)' -AsSecureString
  $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secret)
  try { $env:CONTROL_PLANE_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
  finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
  $ownedKey = $true
}
try {
  $env:DOT_PROBE_MCP_AUTH = 'Bearer ' + $config.mcpToken
  $argsList = @('--control-plane.tunnel-id', $config.tunnelId, '--control-plane.api-key', 'env:CONTROL_PLANE_API_KEY', '--mcp.server-url', "http://127.0.0.1:$($config.mcpPort)/mcp", '--mcp.extra-headers', 'Authorization: env:DOT_PROBE_MCP_AUTH', '--mcp.discovery-extra-headers', 'Authorization: env:DOT_PROBE_MCP_AUTH', '--health.listen-addr', '127.0.0.1:8789', '--profile-dir', (Join-Path $root '.local\profiles'))
  if ($DoctorOnly) { & $binary doctor @argsList --explain; exit $LASTEXITCODE }
  Write-Output 'Tunnel running in this terminal. Keep it open; Ctrl+C stops the tunnel. Health UI: http://127.0.0.1:8789/ui'
  & $binary run @argsList
  if ($LASTEXITCODE -ne 0) { throw "tunnel-client exited with code $LASTEXITCODE" }
} finally {
  Remove-Item Env:DOT_PROBE_MCP_AUTH -ErrorAction SilentlyContinue
  if ($ownedKey) { Remove-Item Env:CONTROL_PLANE_API_KEY -ErrorAction SilentlyContinue }
}
