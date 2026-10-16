// Independent, bounded receive-only probe. No MCP or QQ message-send API.
export const API = 'https://api.bot.qq.com';
export const INTENTS = 1 << 25;
class ProbeError extends Error {
  constructor(stage, detail) { super(stage); this.stage = stage; this.detail = detail; }
}
export async function connectCredentials(appId, secret, fetchImpl = fetch, signal) {
  async function request(stage, route, options) {
    let response;
    try {
      response = await fetchImpl(API + route, { ...options, redirect: 'error',
        signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(15000)]) : AbortSignal.timeout(15000) });
    } catch (error) {
      const code = error.cause?.code;
      throw new ProbeError(stage, { category: 'network', ...(typeof code === 'string' && /^[A-Z_0-9]+$/.test(code) ? { code } : {}) });
    }
    let data;
    try { data = await response.json(); } catch { throw new ProbeError(stage, { category: 'invalid_json', http_status: response.status }); }
    if (!response.ok || (data.code !== undefined && Number(data.code) !== 0)) {
      throw new ProbeError(stage, { category: 'api_error', http_status: response.status,
        ...(Number.isSafeInteger(Number(data.code)) ? { code: Number(data.code) } : {}) });
    }
    return data;
  }
  const token = await request('access_token', '/app/getAppAccessToken', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ appId, clientSecret: secret })
  });
  if (typeof token.access_token !== 'string' || !token.access_token || !(Number(token.expires_in) > 60)) {
    throw new ProbeError('access_token', { category: 'invalid_token_response' });
  }
  const gateway = await request('gateway', '/gateway', { headers: { Authorization: `QQBot ${token.access_token}` } });
  let url;
  try { url = new URL(gateway.url); } catch { throw new ProbeError('gateway', { category: 'invalid_gateway' }); }
  if (url.protocol !== 'wss:' || !url.hostname.endsWith('.qq.com') || url.username || url.password || (url.port && url.port !== '443')) {
    throw new ProbeError('gateway', { category: 'invalid_gateway' });
  }
  return { token: token.access_token, expiresIn: Number(token.expires_in), url: url.href, host: url.hostname };
}

export async function runProbe({ appId, secret, expectedText, timeoutMs = 600000, signal, report = () => {},
  fetchImpl = fetch, socketFactory = url => new WebSocket(url), acceptMessage = data => data.content.trim() === expectedText,
  continuous = false, onMessage = () => {}, eventType = 'C2C_MESSAGE_CREATE' }) {
  const result = { started_at: new Date().toISOString(), ready: false, heartbeat_ack: false, matched_message: null,
    c2c_events: 0, ignored_events: 0, qq_messages_sent: 0, dot_calls: 0, success: false, records: [] };
  const emit = (stage, detail = {}) => { const entry = { at: new Date().toISOString(), stage, ...detail }; result.records.push(entry); if (continuous && result.records.length > 30) result.records.shift(); report(entry); };
  if (!/^\d+$/.test(appId ?? '') || !secret || !expectedText || timeoutMs <= 0 || timeoutMs > 600000) {
    emit('invalid_configuration'); return result;
  }
  let credentials;
  try {
    credentials = await connectCredentials(appId, secret, fetchImpl, signal);
    emit('credentials_and_gateway_ok', { gateway_host: credentials.host });
  } catch (error) {
    emit(error.stage ?? 'setup_failed', error.detail ?? { category: 'unexpected_error' }); return result;
  }
  // The bridge renews credentials between continuous sessions; standalone probes stay bounded.
  return new Promise(resolve => {
    let ws, heartbeat, deadline, handshake, sequence = null, waitingAck = false, hello = false, done = false;
    const finish = (stage, detail = {}) => {
      if (done) return;
      done = true; clearInterval(heartbeat); clearTimeout(deadline); clearTimeout(handshake);
      signal?.removeEventListener('abort', abort);
      result.success = result.ready && result.heartbeat_ack && Boolean(result.matched_message);
      result.ended_at = new Date().toISOString(); emit(stage, detail);
      try { ws?.close(1000, 'probe finished'); } catch { /* no raw transport errors in output */ }
      resolve(result);
    };
    const abort = () => finish('cancelled');
    const send = packet => {
      try { ws.send(JSON.stringify(packet)); } catch { finish('socket_send_failed'); }
    };
    const beat = () => {
      if (done) return;
      if (waitingAck) return finish('heartbeat_timeout');
      waitingAck = true; send({ op: 1, d: sequence });
    };
    const check = () => { if (!continuous && result.ready && result.heartbeat_ack && result.matched_message) finish('receive_verified'); };
    try { ws = socketFactory(credentials.url); } catch { finish('socket_open_failed'); return; }
    const sessionMs = (credentials.expiresIn - 60) * 1000;
    deadline = setTimeout(() => finish(continuous ? 'token_renewal_due' : 'receive_timeout'), continuous ? sessionMs : Math.min(timeoutMs, sessionMs));
    handshake = setTimeout(() => finish('handshake_timeout'), Math.min(20000, timeoutMs));
    signal?.addEventListener('abort', abort, { once: true });
    if (signal?.aborted) { abort(); return; }
    ws.addEventListener('open', () => { if (!done) emit('websocket_open'); });
    ws.addEventListener('error', () => finish('websocket_error'));
    ws.addEventListener('close', event => finish('websocket_closed', { close_code: event.code }));
    ws.addEventListener('message', event => {
      if (done) return;
      let packet;
      try { packet = JSON.parse(event.data); } catch { finish('invalid_gateway_json'); return; }
      if (!packet || typeof packet !== 'object') { finish('invalid_gateway_packet'); return; }
      if (Number.isSafeInteger(packet.s)) sequence = packet.s;
      if (packet.op === 10) {
        const interval = packet.d?.heartbeat_interval;
        if (hello || !Number.isSafeInteger(interval) || interval < 10 || interval > 300000) { finish('invalid_hello'); return; }
        hello = true; emit('hello', { heartbeat_interval_ms: interval });
        send({ op: 2, d: { token: `QQBot ${credentials.token}`, intents: INTENTS, shard: [0, 1] } });
        heartbeat = setInterval(beat, interval);
      } else if (packet.op === 11) {
        if (!waitingAck) return;
        waitingAck = false;
        if (!result.heartbeat_ack) emit('heartbeat_ack');
        result.heartbeat_ack = true; check();
      } else if (packet.op === 9) finish('invalid_session');
      else if (packet.op === 7) finish('gateway_requested_reconnect');
      else if (packet.op === 0 && packet.t === 'READY') {
        if (!hello || !packet.d?.session_id) { finish('invalid_ready'); return; }
        result.ready = true; clearTimeout(handshake); emit('ready'); beat();
      } else if (packet.op === 0 && packet.t === eventType) {
        if (!result.ready) { finish('message_before_ready'); return; }
        result.c2c_events++;
        const data = packet.d;
        if (typeof data?.id === 'string' && typeof data.content === 'string' && acceptMessage(data)) {
          result.matched_message = { message_id: data.id, content: data.content, received_at: new Date().toISOString() };
          emit(eventType === 'GROUP_MESSAGE_CREATE' ? 'test_group_message_received' : 'test_private_message_received', { message_id: data.id });
          if (continuous) {
            try { onMessage(data); } catch { finish('message_handler_failed'); return; }
          }
          check();
        } else emit(eventType === 'GROUP_MESSAGE_CREATE' ? 'nonmatching_group_message' : 'nonmatching_private_message', { count: result.c2c_events });
      } else if (packet.op === 0) result.ignored_events++;
    });
  });
}
