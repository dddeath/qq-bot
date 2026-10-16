import http from 'node:http';
import { timingSafeEqual } from 'node:crypto';
import { pathToFileURL } from 'node:url';
import { loadConfig } from './config.mjs';
import { Probe, RpcError, VERSION } from './probe.mjs';
import { BridgeRouter } from './qq-bridge.mjs';

function authenticated(req, token) {
  const got = Buffer.from(req.headers.authorization ?? ''), expected = Buffer.from('Bearer ' + token);
  return got.length === expected.length && timingSafeEqual(got, expected);
}
async function readJSON(req) {
  let size = 0; const chunks = [];
  for await (const chunk of req) {
    size += chunk.length;
    if (size > 262144) throw new RpcError(-32600, 'Request exceeds 256 KiB');
    chunks.push(chunk);
  }
  try { return JSON.parse(Buffer.concat(chunks).toString('utf8')); }
  catch { throw new RpcError(-32700, 'Parse error'); }
}
function json(res, status, value) {
  res.writeHead(status, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' });
  res.end(JSON.stringify(value));
}
export async function startServers(config, probe = new Probe(config.dir)) {
  const mcp = http.createServer(async (req, res) => {
    if (req.url === '/healthz' && req.method === 'GET') return json(res, 200, { ok: true, service: 'dot-event-probe' });
    if (req.url !== '/mcp') return json(res, 404, { error: 'Not found' });
    if (req.headers.origin) return json(res, 403, { error: 'Browser-origin requests are not used by this private probe' });
    if (!authenticated(req, config.mcpToken)) return json(res, 401, { error: 'Unauthorized' });
    if (req.method !== 'POST') return json(res, 405, { error: 'Only stateless POST is supported' });
    let request;
    try {
      request = await readJSON(req);
      if (!request || request.jsonrpc !== '2.0' || typeof request.method !== 'string' || Array.isArray(request)) throw new RpcError(-32600, 'Invalid Request');
      if (request.id === undefined) {
        if (!request.method.startsWith('notifications/')) throw new RpcError(-32600, 'Request id required');
        res.writeHead(202); res.end(); return;
      }
      const header = req.headers['mcp-protocol-version'];
      const meta = request.params?._meta?.['io.modelcontextprotocol/protocolVersion'];
      const modern = header === VERSION || meta === VERSION;
      if (modern && (header !== VERSION || meta !== VERSION)) throw new RpcError(-32020, 'Protocol header and metadata must match');
      if (header && ![VERSION, '2025-06-18', '2025-03-26', '2024-11-05'].includes(header)) throw new RpcError(-32022, 'Unsupported protocol version', { supported: [VERSION], requested: header });
      if (request.method.startsWith('events/') && !modern) throw new RpcError(-32022, 'Events require MCP 2026-07-28', { supported: [VERSION] });
      const result = await probe.rpc(request.method, request.params ?? {}, { source: 'mcp-http' });
      json(res, 200, { jsonrpc: '2.0', id: request.id, result });
    } catch (error) {
      probe.state.protocolErrors ??= [];
      probe.state.protocolErrors.push({ at: probe.iso(), method: typeof request?.method === 'string' ? request.method.slice(0, 100) : null,
        code: error instanceof RpcError ? error.code : -32603,
        message: error instanceof RpcError ? error.message : 'Internal error',
        protocol_header: req.headers['mcp-protocol-version'] ?? null,
        protocol_meta: request?.params?._meta?.['io.modelcontextprotocol/protocolVersion'] ?? null });
      probe.state.protocolErrors = probe.state.protocolErrors.slice(-30); probe.save();
      const protocolError = [-32020, -32022].includes(error.code);
      json(res, protocolError ? 400 : 200, { jsonrpc: '2.0', id: request?.id ?? null, error: {
        code: error instanceof RpcError ? error.code : -32603,
        message: error instanceof RpcError ? error.message : 'Internal error',
        ...(error.data ? { data: error.data } : {})
      } });
    }
  });
  const admin = http.createServer(async (req, res) => {
    if (req.headers.origin || !authenticated(req, config.adminToken)) return json(res, 401, { error: 'Unauthorized' });
    try {
      if (req.method === 'POST' && ((req.url === '/qq/start' && probe.group?.receiving) ||
        (req.url === '/qq/group/start' && probe.qq?.receiving))) throw new Error('Another QQ receiver is already running');
      if (probe.group && req.method === 'GET' && req.url === '/qq/group/status') return json(res, 200, probe.group.status());
      if (probe.group && req.method === 'POST' && req.url === '/qq/group/start') {
        const args = await readJSON(req);
        if (probe.qq?.receiving) throw new Error('Another QQ receiver is already running');
        return json(res, 202, probe.group.start(args));
      }
      if (probe.group && req.method === 'POST' && req.url === '/qq/group/stop') return json(res, 200, probe.group.stop());
      if (probe.qq && req.method === 'GET' && req.url === '/qq/status') return json(res, 200, probe.qq.status());
      if (probe.qq && req.method === 'POST' && req.url === '/qq/start') return json(res, 202, probe.qq.start());
      if (probe.qq && req.method === 'POST' && req.url === '/qq/stop') return json(res, 200, probe.qq.stop());
      if (req.method === 'GET' && req.url === '/status') return json(res, 200, probe.status());
      if (req.method === 'POST' && req.url === '/inject') {
        const message = probe.inject(await readJSON(req));
        json(res, 202, message);
        probe.deliver(message.message_id).catch(() => {});
        return;
      }
      if (req.method === 'POST' && req.url === '/redeliver') {
        const args = await readJSON(req);
        const results = await probe.deliver(args.message_id);
        return json(res, 200, { results });
      }
      json(res, 404, { error: 'Not found' });
    } catch (error) { json(res, 400, { error: error.message }); }
  });
  const listen = server => port => new Promise((resolve, reject) => { server.once('error', reject); server.listen(port, '127.0.0.1', resolve); });
  await listen(mcp)(config.mcpPort);
  try { await listen(admin)(config.adminPort); } catch (error) { await new Promise(r => mcp.close(r)); throw error; }
  return { mcp, admin, probe, close: async () => { await Promise.all([mcp, admin].map(server => new Promise(r => { server.close(r); server.closeIdleConnections(); }))); } };
}
if (import.meta.url === pathToFileURL(process.argv[1] ?? '').href) {
  const config = loadConfig();
  const bridge = new BridgeRouter(config.dir);
  const servers = await startServers(config, bridge);
  console.log(JSON.stringify({ service: 'dot-event-probe', mcp: `http://127.0.0.1:${config.mcpPort}/mcp`, admin: `http://127.0.0.1:${config.adminPort}`, state: config.dir, live_e2e: 'NOT_VERIFIED' }));
  for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, async () => { bridge.qq.stop(); bridge.group.stop(); await servers.close(); process.exit(0); });
}
