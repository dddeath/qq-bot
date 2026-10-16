import fs from 'node:fs';
import path from 'node:path';
import { loadConfig, root } from '../src/config.mjs';

const config = loadConfig();
const report = { captured_at: new Date().toISOString(), hosted_tunnel: 'NOT_OBSERVED', personal_dot_e2e: 'NOT_VERIFIED' };
try {
  const response = await fetch('http://127.0.0.1:8789/health?details=true', { signal: AbortSignal.timeout(5000) });
  const h = await response.json();
  report.tunnel = { live: h.live, ready: h.ready, version: h.runtime?.version,
    control_plane: h.components?.['control-plane']?.state,
    last_poll_success: h.components?.['control-plane']?.details?.last_success,
    dispatched_calls: h.components?.dispatcher?.details?.completed,
    accepted_responses: h.components?.['response-delivery']?.details?.accepted };
  if (h.ready && report.tunnel.control_plane === 'polling') report.hosted_tunnel = 'READY_AND_POLLING';
} catch { report.tunnel = { error: 'Tunnel health endpoint not reachable' }; }
try {
  const response = await fetch(`http://127.0.0.1:${config.adminPort}/status`, { headers: { Authorization: 'Bearer ' + config.adminToken }, signal: AbortSignal.timeout(5000) });
  report.probe = await response.json();
} catch { report.probe = { error: 'Local probe not reachable' }; }
const file = path.join(root, 'evidence', 'live-status.json');
fs.mkdirSync(path.dirname(file), { recursive: true }); fs.writeFileSync(file, JSON.stringify(report, null, 2));
console.log(JSON.stringify(report, null, 2));
