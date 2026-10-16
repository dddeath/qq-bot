import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { root } from '../src/config.mjs';

test('local QQ config persists, reloads without prompting, updates and rejects invalid values', t => {
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'qq-config-test-'));
  t.after(() => fs.rmSync(temp, { recursive: true, force: true }));
  const script = path.join(temp, 'test.ps1');
  fs.writeFileSync(script, `
$ErrorActionPreference = 'Stop'
. '${path.join(root, 'scripts/qq-credentials.ps1')}'
$root = '${temp}'
$secret = [Security.SecureString]::new(); 'fixture-secret-one'.ToCharArray() | ForEach-Object { $secret.AppendChar($_) }
Save-QqCredentials -Root $root -AppId '12345' -Secret $secret
$secret.Dispose()
function Read-Host { throw 'Unexpected credential prompt' }
$a = Get-QqCredentials -Root $root
if ($a.appId -ne '12345' -or $a.appSecret -ne 'fixture-secret-one') { throw 'Round trip mismatch' }
$secret = [Security.SecureString]::new(); 'fixture-secret-two'.ToCharArray() | ForEach-Object { $secret.AppendChar($_) }
Save-QqCredentials -Root $root -AppId '67890' -Secret $secret
$secret.Dispose()
$b = Get-QqCredentials -Root $root
if ($b.appId -ne '67890' -or $b.appSecret -ne 'fixture-secret-two') { throw 'Update mismatch' }
$file = Join-Path $root '.local/qq-auth/config.json'
& icacls $file | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Missing ACL' }
Set-Content -LiteralPath $file -Value '{"appId":"bad","appSecret":"x"}'
$rejected = $false
try { Get-QqCredentials -Root $root | Out-Null } catch { $rejected = $true }
if (!$rejected) { throw 'Invalid config accepted' }
Write-Output 'SAVE_LOAD_UPDATE_VALIDATE_OK; no prompts on reuse'
`);
  const r = spawnSync('powershell', ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', script], { encoding: 'utf8', windowsHide: true });
  assert.equal(r.status, 0, r.stderr);
  assert.match(r.stdout, /SAVE_LOAD_UPDATE_VALIDATE_OK/);
  assert.ok(!r.stdout.includes('fixture-secret'));
});

test('both launchers use shared config; PowerShell sources parse', () => {
  for (const file of ['qq-probe/start.ps1', 'qq-reply-probe/start.ps1', 'scripts/qq-credentials.ps1', 'scripts/configure-qq.ps1']) {
    const source = fs.readFileSync(path.join(root, file), 'utf8');
    if (file.endsWith('start.ps1')) {
      assert.match(source, /Get-QqCredentials -Root/);
      assert.ok(!source.includes('Read-Host'));
    }
    const r = spawnSync('powershell', ['-NoProfile', '-Command', `$t=$null;$e=$null;[System.Management.Automation.Language.Parser]::ParseFile('${path.join(root, file)}',[ref]$t,[ref]$e)|Out-Null;if($e.Count){exit 1}`], { windowsHide: true });
    assert.equal(r.status, 0, file);
  }
});
