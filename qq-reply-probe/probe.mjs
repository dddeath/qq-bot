import fs from 'node:fs';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { runProbe, API } from '../qq-probe/probe.mjs';

export const REPLY_TEXT = 'QQ 私聊固定回复验证成功。';
export async function runFixedReply({ appId, secret, expectedText, dir, signal, timeoutMs = 600000,
  fetchImpl = fetch, socketFactory = url => new WebSocket(url), report = () => {} }) {
  let token, incoming;
  // Observe only the original receiver's authenticated token response and matching C2C event.
  const captureFetch = async (url, options) => {
    const response = await fetchImpl(url, options);
    return { ok: response.ok, status: response.status, json: async () => {
      const data = await response.json();
      if (url === API + '/app/getAppAccessToken') token = data.access_token;
      return data;
    } };
  };
  const captureSocket = url => {
    const socket = socketFactory(url);
    socket.addEventListener('message', event => {
      let p; try { p = JSON.parse(event.data); } catch { return; }
      if (!incoming && p?.op === 0 && p.t === 'C2C_MESSAGE_CREATE' && typeof p.d?.content === 'string' && p.d.content.trim() === expectedText) {
        incoming = { id: p.d.id, openid: p.d.author?.user_openid };
      }
    });
    return socket;
  };
  const receive = await runProbe({ appId, secret, expectedText, signal, timeoutMs, fetchImpl: captureFetch, socketFactory: captureSocket, report });
  const result = { scope: 'qq-private-fixed-reply-only', receive, reply_text: REPLY_TEXT, send_attempts: 0,
    confirmed_messages_sent: 0, dot_calls: 0, success: false, send_state: 'not_attempted', records: [] };
  const emit = (stage, details = {}) => { const entry = { at: new Date().toISOString(), stage, ...details }; result.records.push(entry); report(entry); };
  if (!receive.success) return result;
  if (signal?.aborted) { emit('cancelled_before_send'); return result; }
  if (!token || !incoming || incoming.id !== receive.matched_message.message_id || typeof incoming.openid !== 'string' || !incoming.openid.trim()) {
    emit('missing_or_mismatched_reply_target'); return result;
  }
  fs.mkdirSync(dir, { recursive: true });
  const key = createHash('sha256').update(JSON.stringify([appId, incoming.id])).digest('hex');
  const ledger = path.join(dir, `attempt-${key}.json`);
  const record = { at: new Date().toISOString(), source_message_id: incoming.id,
    recipient_sha256: createHash('sha256').update(incoming.openid).digest('hex'), msg_seq: 1,
    reply_text: REPLY_TEXT, state: 'attempt_reserved', automatic_retry: false };
  // Durable exclusive reservation is retained even after failure/timeout: never resend this message.
  try { fs.writeFileSync(ledger, JSON.stringify(record, null, 2), { flag: 'wx', mode: 0o600 }); }
  catch (error) { emit(error.code === 'EEXIST' ? 'duplicate_send_blocked' : 'send_reservation_failed'); return result; }
  result.ledger_file = ledger;
  result.send_attempts = 1; result.send_state = 'unknown';
  emit('fixed_reply_sending', { source_message_id: incoming.id });
  try {
    const response = await fetchImpl(`${API}/v2/users/${encodeURIComponent(incoming.openid)}/messages`, {
      method: 'POST', redirect: 'error', headers: { Authorization: `QQBot ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ msg_type: 0, content: REPLY_TEXT, msg_id: incoming.id, msg_seq: 1 }),
      signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(15000)]) : AbortSignal.timeout(15000)
    });
    result.http_status = response.status;
    const data = await response.json();
    const hasError = data.code !== undefined && Number(data.code) !== 0;
    if (!response.ok || hasError) {
      result.send_state = response.status >= 500 ? 'unknown' : 'rejected';
      if (Number.isSafeInteger(Number(data.code))) result.api_error_code = Number(data.code);
      emit('reply_not_confirmed', { http_status: response.status, send_state: result.send_state, ...(result.api_error_code === undefined ? {} : { api_error_code: result.api_error_code }) });
    } else if (typeof data.id === 'string' && data.id) {
      result.send_state = 'confirmed'; result.confirmed_messages_sent = 1; result.success = true;
      result.outgoing_message_id = data.id;
      emit('fixed_reply_api_confirmed', { outgoing_message_id: data.id });
    } else emit('reply_response_missing_message_id');
  } catch { emit('reply_result_unknown_no_retry'); }
  const final = { ...record, state: result.send_state, outgoing_message_id: result.outgoing_message_id,
    http_status: result.http_status, api_error_code: result.api_error_code };
  try { fs.writeFileSync(ledger + '.tmp', JSON.stringify(final, null, 2), { mode: 0o600 }); fs.renameSync(ledger + '.tmp', ledger); }
  catch { emit('ledger_update_failed_reservation_retained'); }
  return result;
}
