import {readFile} from 'node:fs/promises';
import {credentialManager, GLOBAL_CONFIG_FILE} from '@xzxzzx/bilibili-mcp/dist/utils/credentials.js';
import {checkLoginStatus} from '@xzxzzx/bilibili-mcp/dist/bilibili/http.js';

// expiresAt is a local cache deadline; the platform decides whether login remains valid.
export async function ensureCredentialReadiness() {
  if (credentialManager.getCredentials()) return {status: 'ready'};
  let raw, stored;
  try {raw = await readFile(GLOBAL_CONFIG_FILE, 'utf8'); stored = JSON.parse(raw);}
  catch {return {status: 'unavailable'};}
  if (!stored.sessdata || !stored.bili_jct || !stored.dedeuserid ||
      !Number.isFinite(stored.expiresAt) || stored.expiresAt > Date.now()) {
    return {status: 'unavailable'};
  }
  const candidate = {...stored, expiresAt: Date.now() + 30 * 24 * 60 * 60 * 1000};
  try {
    const result = await checkLoginStatus(candidate, AbortSignal.timeout(15000));
    if (!result.isLogin) return {status: 'error', code: 'COOKIE_EXPIRED'};
    // A concurrent login owns the newer file; never overwrite it with this candidate.
    if (await readFile(GLOBAL_CONFIG_FILE, 'utf8') !== raw) {
      credentialManager.clearCredentials();
      return {status: 'changed'};
    }
    credentialManager.saveToFile(candidate);
    credentialManager.setCredentials(candidate);
    return {status: 'renewed'};
  } catch {
    return {status: 'error', code: 'CREDENTIAL_VALIDATION_FAILED'};
  }
}
