# QQ private-chat fixed reply test

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File E:\qq-bot\qq-reply-probe\start.ps1
```

Credentials are loaded from E:\qq-bot\.local\qq-auth\config.json; the first launch prompts once and saves them. After READY, send the printed `qq-reply-<uuid>` text to this bot in QQ private chat. The fixed reply is **QQ 私聊固定回复验证成功。** The destination comes only from the matching C2C event's `author.user_openid`; `msg_id` is the same event's `d.id` and `msg_seq` is fixed to 1.

The receiver is the unchanged `E:\qq-bot\qq-probe\probe.mjs`. The wrapper observes its token and matching event in memory, waits for successful receive verification, then makes at most one sending request. It does not call dot, MCP, a group-message API or an arbitrary recipient. Other messages are ignored. The receive session lasts at most ten minutes; the sending request times out after fifteen seconds.

The API result `FIXED_REPLY_API_CONFIRMED` requires a success response with an outgoing message ID. It does not prove the message appeared in your QQ client; confirm that separately. HTTP errors, timeouts and malformed results never trigger automatic retries. A durable exclusive reservation under `.local/qq-fixed-reply/attempt-<hash>.json` prevents a later run from resending the same source message. Preserve reservations even if the result is unknown. A new run creates a new test text.

AppID and AppSecret are saved in a Git-ignored plaintext local configuration restricted to the current Windows user and SYSTEM. Both QQ probes reuse it. Run E:\qq-bot\scripts\configure-qq.ps1 to update it without connecting. Credentials enter Node through temporary environment variables, not command arguments. Run evidence and reservations are restricted to the local user and SYSTEM by the launcher. Evidence excludes the raw sender OpenID and credentials; only a recipient hash, synthetic test text and message IDs are recorded.

Ctrl+C stops this test without stopping Phase 1. An already accepted QQ message is not undone by stopping or removing the probe. No automatic message recall is performed.

Tests: `node --test E:\qq-bot\qq-reply-probe\probe.test.mjs`

Official send schema: https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_users_user_openid_messages.post.html

Official receive schema: https://bot.q.qq.com/wiki/develop/api-v2/autogen/event/c2c_message_create.html
