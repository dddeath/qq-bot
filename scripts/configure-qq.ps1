$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'qq-credentials.ps1')
$root = Split-Path $PSScriptRoot -Parent
Set-QqCredentialsInteractive -Root $root
Write-Output "QQ credentials saved to $(Join-Path $root '.local\qq-auth\config.json'). Future probe launches reuse this configuration."
