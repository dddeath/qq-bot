import { receiveGroup } from './group-receive.mjs';
import { API } from './probe.mjs';
import fs from 'node:fs';
import path from 'node:path';
import { createHash } from 'node:crypto';

export const GROUP_REPLY_TEXT = 'QQ 群固定回复验证成功。';

export async function runGroupReply({ fetchImpl = fetch, ...options }) {
  if (typeof options.groupOpenid !== 'string' || !options.groupOpenid.trim()) throw new Error('groupOpenid is required');
  let token;
  const captureFetch = async (url, init) => {
    const response = await fetchImpl(url, init);
    return { ok: response.ok, status: response.status, json: async () => {
      const data = await response.json();
      if (url === API + '/app/getAppAccessToken') token = data.access_token;
      return data;
    } };
  };
  const receive = await receiveGroup({ ...options, fetchImpl: captureFetch });
  const timing = { receive_finished_at: new Date().toISOString() };
  if (!receive.success) return { success: false, timing, receive };
  if (options.signal?.aborted) return { success: false, timing, receive, stage: 'cancelled_before_send' };
  const incoming = receive.matched_event.d;
  fs.mkdirSync(options.dir, { recursive: true });
  const key = createHash('sha256').update(JSON.stringify([options.appId, incoming.group_openid, incoming.id])).digest('hex');
  const ledger = path.join(options.dir, `attempt-${key}.json`);
  try {
    fs.writeFileSync(ledger, JSON.stringify({ state: 'attempt_reserved', source_message_id: incoming.id,
      group_openid: incoming.group_openid, automatic_retry: false }), { flag: 'wx', mode: 0o600 });
  } catch (error) {
    if (error.code !== 'EEXIST') throw error;
    return { success: false, timing, receive, stage: 'duplicate_send_blocked' };
  }
  timing.send_started_at = new Date().toISOString();
  try {
    const response = await fetchImpl(`${API}/v2/groups/${encodeURIComponent(incoming.group_openid)}/messages`, {
      method: 'POST', redirect: 'error',
      headers: { Authorization: `QQBot ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ msg_type: 0, content: GROUP_REPLY_TEXT, msg_id: incoming.id, msg_seq: 1 }),
      signal: options.signal ? AbortSignal.any([options.signal, AbortSignal.timeout(15000)]) : AbortSignal.timeout(15000)
    });
    let data;
    try { data = await response.json(); }
    catch {
      return { receive, timing, success: false, send_state: 'unknown', stage: 'reply_response_invalid_json', http_status: response.status };
    }
    if (!response.ok || (data.code !== undefined && Number(data.code) !== 0)) {
      return { receive, timing, success: false, send_state: response.status >= 500 ? 'unknown' : 'rejected', stage: 'reply_not_confirmed',
        http_status: response.status, ...(Number.isSafeInteger(Number(data.code)) ? { api_error_code: Number(data.code) } : {}) };
    }
    if (typeof data.id !== 'string' || !data.id.trim()) {
      return { receive, timing, success: false, send_state: 'unknown', stage: 'reply_response_missing_message_id', http_status: response.status };
    }
    return { receive, timing, success: true, send_state: 'confirmed', stage: 'fixed_reply_api_confirmed',
      outgoing_message_id: data.id, reply_text: GROUP_REPLY_TEXT, http_status: response.status };
  } catch (error) {
    const code = error.cause?.code ?? error.code;
    return { receive, timing, success: false, send_state: 'unknown', stage: 'reply_result_unknown_no_retry',
      ...(typeof code === 'string' && /^[A-Z_0-9]+$/.test(code) ? { network_error_code: code } : {}) };
  } finally { timing.send_finished_at = new Date().toISOString(); }
}
