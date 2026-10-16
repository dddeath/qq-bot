# QQ WebSocket private-message probe

Run in an interactive PowerShell terminal:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File E:\qq-bot\qq-probe\start.ps1
```

Both QQ probes share E:\qq-bot\.local\qq-auth\config.json. On first use, enter the bot AppID and hidden AppSecret once; later launches load the saved values without prompting. The file stores the secret in plaintext, is excluded from Git, and its directory is restricted to the current Windows user and SYSTEM. To replace credentials without connecting to QQ, run E:\qq-bot\scripts\configure-qq.ps1. The launcher passes values to Node through temporary environment variables and restores its previous environment on exit.

After `ready`, send the printed `qq-probe-...` text to the bot in **QQ private chat**. A matched `C2C_MESSAGE_CREATE`, authenticated READY and heartbeat ACK are all required for success. The probe then closes its own connection. Timeout is ten minutes; Ctrl+C cancels. Do not run another gateway client for this bot during the test.

Results are stored under `E:\qq-bot\.local\qq-ws-probe\run-<uuid>.json`. Records exclude credentials, session IDs, sender IDs and unrelated message text. Only the matching synthetic test text and message ID are retained. The terminal prints protocol stages and numerical API/close errors, not raw remote error bodies.

This probe only calls the QQ token endpoint and GET /gateway. Its outbound WebSocket packets are Identify and heartbeat. It has no message-send endpoint, no MCP calls, no listener port, no reconnect loop and no background installation. It does not import or start the Phase 1 service. Tokens near expiry end the bounded session rather than refreshing indefinitely.

QQ uses the shared `GROUP_AND_C2C_EVENT` intent (`1 << 25`) for private messages. Group and other dispatch events are ignored. Your bot must have the corresponding platform permission and your QQ account must be eligible to test it. If the platform requires an IP allowlist, use this PC's actual public egress IP.

The first phase remains in its original directories. This probe does not deploy to a public server. To stop/roll back its operation, press Ctrl+C in its terminal; there is no persistent process or configuration to undo. Keep the run JSON as evidence.

Local protocol tests (simulated QQ, not a live acceptance):

```powershell
node --test E:\qq-bot\qq-probe\probe.test.mjs
```

Official protocol: https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/interface-framework/event-emit.html

Official credentials: https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/access-token.html
