import { connectCredentials, INTENTS } from './probe.mjs';

// Prerequisite probe only: authentication, gateway and heartbeat; no message-send or dot API.
export async function receiveGroup({ appId, secret, expectedText, groupOpenid, timeoutMs = 600000,
  signal, report = () => {}, fetchImpl = fetch, socketFactory = url => new WebSocket(url) }) {
  const result = { success: false, ready: false, heartbeat_ack: false, matched_event: null,
    qq_messages_sent: 0, dot_calls: 0, records: [] };
  const emit = (stage, detail = {}) => {
    const record = { at: new Date().toISOString(), stage, ...detail };
    result.records.push(record); report(record);
  };
  if (!expectedText || timeoutMs <= 0 || timeoutMs > 600000) throw new Error('Invalid probe configuration');
  let credentials;
  try { credentials = await connectCredentials(appId, secret, fetchImpl, signal); }
  catch (error) { emit(error.stage ?? 'connection_failed', error.detail ?? {}); return result; }
  return new Promise(resolve => {
    let ws, timer, handshake, heartbeat, sequence = null, waitingAck = false, hello = false, done = false;
    const finish = stage => {
      if (done) return;
      done = true; clearTimeout(timer); clearTimeout(handshake); clearInterval(heartbeat);
      signal?.removeEventListener('abort', abort);
      result.success = stage === 'group_receive_verified';
      emit(stage);
      try { ws?.close(1000, 'receive probe finished'); } catch {}
      resolve(result);
    };
    const abort = () => finish('cancelled');
    const send = packet => { try { ws.send(JSON.stringify(packet)); } catch { finish('socket_send_failed'); } };
    const check = () => {
      if (result.ready && result.heartbeat_ack && result.matched_event) finish('group_receive_verified');
    };
    const beat = () => {
      if (done) return;
      if (waitingAck) return finish('heartbeat_timeout');
      waitingAck = true; send({ op: 1, d: sequence });
    };
    try { ws = socketFactory(credentials.url); } catch { finish('socket_open_failed'); return; }
    timer = setTimeout(() => finish('receive_timeout'), Math.min(timeoutMs, (credentials.expiresIn - 60) * 1000));
    handshake = setTimeout(() => finish('handshake_timeout'), Math.min(20000, timeoutMs));
    signal?.addEventListener('abort', abort, { once: true });
    if (signal?.aborted) { abort(); return; }
    ws.addEventListener('error', () => finish('websocket_error'));
    ws.addEventListener('close', () => finish('websocket_closed'));
    ws.addEventListener('message', event => {
      if (done) return;
      let packet;
      try { packet = JSON.parse(event.data); } catch { finish('invalid_packet'); return; }
      if (!packet || typeof packet !== 'object') { finish('invalid_packet'); return; }
      if (Number.isSafeInteger(packet.s)) sequence = packet.s;
      if (packet.op === 10) {
        const interval = packet.d?.heartbeat_interval;
        if (hello || !Number.isSafeInteger(interval) || interval < 10 || interval > 300000) return finish('invalid_hello');
        hello = true;
        send({ op: 2, d: { token: `QQBot ${credentials.token}`, intents: INTENTS, shard: [0, 1] } });
        heartbeat = setInterval(beat, interval);
      } else if (packet.op === 11 && waitingAck) {
        waitingAck = false; result.heartbeat_ack = true; check();
      } else if (packet.op === 9) finish('invalid_session');
      else if (packet.op === 7) finish('gateway_requested_reconnect');
      else if (packet.op === 0 && packet.t === 'READY') {
        if (!hello || !packet.d?.session_id) return finish('invalid_ready');
        clearTimeout(handshake); result.ready = true; emit('ready'); beat();
      } else if (packet.op === 0 && packet.t === 'GROUP_MESSAGE_CREATE') {
        const d = packet.d;
        if (groupOpenid !== undefined && d?.group_openid !== groupOpenid) return;
        if (!result.ready || typeof d?.content !== 'string' || d.content.trim() !== expectedText) return;
        if (!d.id || !d.group_openid || !d.author?.member_openid || !d.timestamp) return finish('incomplete_group_event');
        if (Array.isArray(d.mentions) && d.mentions.length) return finish('mentioned_message_not_accepted');
        result.matched_event = packet;
        emit('matching_ordinary_group_message', { group_openid: d.group_openid, message_id: d.id });
        check();
      }
    });
  });
}
