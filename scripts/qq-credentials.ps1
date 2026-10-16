function Save-QqCredentials {
  param([string]$Root, [string]$AppId, [Security.SecureString]$Secret)
  if ($AppId -notmatch '^\d+$') { throw 'AppID must contain digits only' }
  $dir = Join-Path $Root '.local\qq-auth'
  New-Item -ItemType Directory -Path $dir -Force | Out-Null
  $identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
  & icacls $dir /inheritance:r /grant:r "${identity}:(OI)(CI)F" 'SYSTEM:(OI)(CI)F' | Out-Null
  if ($LASTEXITCODE -ne 0) { throw 'Credential directory ACL setup failed' }
  $pointer = [IntPtr]::Zero
  try {
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secret)
    $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    if ([string]::IsNullOrWhiteSpace($plain)) { throw 'AppSecret is empty' }
    $file = Join-Path $dir 'config.json'
    @{ appId = $AppId; appSecret = $plain } | ConvertTo-Json | Set-Content -LiteralPath ($file + '.tmp') -Encoding UTF8
    Move-Item -LiteralPath ($file + '.tmp') -Destination $file -Force
  } finally {
    if ($pointer -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
    $plain = $null
  }
}

function Set-QqCredentialsInteractive {
  param([string]$Root)
  $appId = Read-Host 'QQ bot AppID (saved locally)'
  $secret = Read-Host 'QQ bot AppSecret (hidden; saved in local config)' -AsSecureString
  try { Save-QqCredentials -Root $Root -AppId $appId -Secret $secret }
  finally { $secret.Dispose() }
}

function Get-QqCredentials {
  param([string]$Root)
  $file = Join-Path $Root '.local\qq-auth\config.json'
  if (!(Test-Path -LiteralPath $file)) { Set-QqCredentialsInteractive -Root $Root }
  try { $config = Get-Content -LiteralPath $file -Raw | ConvertFrom-Json }
  catch { throw 'QQ config is invalid JSON; run scripts/configure-qq.ps1 to replace it.' }
  if ($config.appId -notmatch '^\d+$' -or $config.appSecret -isnot [string] -or [string]::IsNullOrWhiteSpace($config.appSecret)) {
    throw 'QQ config requires appId and appSecret; run scripts/configure-qq.ps1.'
  }
  return $config
}
