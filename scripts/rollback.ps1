param([switch]$DryRun)
$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath((Split-Path $PSScriptRoot -Parent))
$server = Join-Path $root 'src\server.mjs'
$tunnel = Join-Path $root '.tools\tunnel-client\tunnel-client.exe'
$candidates = @(Get-CimInstance Win32_Process | Where-Object {
  ($_.Name -eq 'node.exe' -and $_.CommandLine -and $_.CommandLine.Contains($server)) -or
  ($_.ExecutablePath -eq $tunnel -and $_.CommandLine -and $_.CommandLine.Contains('tunnel_REPLACE_WITH_YOUR_ID'))
})
foreach ($process in $candidates) {
  if ($DryRun) { Write-Output "Would stop owned process PID=$($process.ProcessId) name=$($process.Name)" }
  else { Stop-Process -Id $process.ProcessId -ErrorAction Stop; Write-Output "Stopped owned process PID=$($process.ProcessId) name=$($process.Name)" }
}
if ($candidates.Count -eq 0) { Write-Output 'No owned probe/tunnel process is running.' }
Write-Output 'Source, evidence and local subscription state retained. Before a permanent stop, ask your dot to unsubscribe; remove the plugin if no longer needed.'
