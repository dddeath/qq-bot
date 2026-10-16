# QQ 桥接的延迟机制参考

## 结论

可直接借鉴的是减少首次读取往返、准确计算人为等待、连接断开后的恢复和分段观测。已检查的项目没有提供可证明本项目 dot 回调能降至某个秒数的对照实验。它们采用本地 Agent 会话 API 或模型 API，未使用本项目的 OpenAI dot 事件订阅链路，因此其架构不能直接证明 dot 云端唤醒可以绕过或加速。

核验日期：2026-10-11。下列链接固定到实际读取的提交；未运行第三方项目，也未改本项目业务代码、配置或订阅。

## 当前项目的回调与工具链路

两条网络路径分别承担事件通知和工具调用：

```text
QQ 群消息 → QQ Gateway WebSocket → 本机 QQBridge 接收并保存
  → Probe.deliver → postWebhook → OpenAI 订阅 callback URL
  → 云端事件处理与 dot 任务执行

dot 调用 MCP 工具 → OpenAI Tunnel 服务
  → 本机 tunnel-client 长轮询取得请求 → localhost:8787/mcp
  → list_pending_messages → get_message → reply_message
  → QQ REST API → 原测试群
```

第二行中的三个工具是三次顺序调用，分别经过隧道往返。事件 callback 的 HTTPS 请求由本机 Node 服务直接发出，不经过 tunnel-client。隧道连接正常不代表 callback 请求正常。

源码入口：`src/qq-bridge.mjs`、`src/probe.mjs:144`、`src/webhook.mjs:55`。官方机制：[MCP Events](https://developers.openai.com/plugins/build/mcp-events)、[Secure MCP Tunnels](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)。

当前 tunnel-client 健康接口报告版本 `0.0.16+5f99daabd4aa4a77049e6d81d54a0d8c18335397`，poll 等待参数 30 秒。该参数是长轮询保持时间，不是每 30 秒才检查一次请求。[已安装版本协议](https://github.com/openai/tunnel-client/blob/5f99daabd4aa4a77049e6d81d54a0d8c18335397/docs/protocol.md)。

### 已有样本拆分

证据根目录：`E:\qq-bot\evidence\issue05-live-2026-10-11T09-28-37-427Z`。以下间隔使用本机记录，不混减 QQ 客户端时间。

| 区间 | D01 | D03 |
|---|---:|---:|
| callback 获接受 → 首次 pending 查询 | 14.357 秒 | 15.486 秒 |
| pending 查询 → get_message | 8.964 秒 | 6.498 秒 |
| get_message → reply_message 调用 | 12.301 秒 | 35.111 秒 |
| 本机记录端到端 | 39.360 秒 | 64.478 秒 |

这些区间包含平台编排、模型决策与网络往返，不等于纯模型生成或纯隧道耗时。固定回复三个有效样本的本机端到端为 1.306–1.548 秒。D02 三次 callback 均未取得 HTTP 状态，单次约 0.09–0.12 秒，缺少错误类型；不能归因为 10 秒请求超时。

### 已定位的调查入口

- `src/probe.mjs` 的 delivery catch 丢弃错误详情，只保存 status=0；下一步可保存脱敏错误码、失败阶段和分段耗时，避免把 DNS、连接、TLS、响应失败混为一类。
- `src/webhook.mjs` 使用 `agent:false`，没有复用的连接池；逐次解析 IPv4，Fake-IP 场景另走 DoH。10 秒请求计时开始于解析之后。连接复用、解析缓存与代理路径属于可核验候选，尚未证明是主要耗时来源。
- pending 工具仅返回编号与时间，dot 随后需要 get_message 才得到内容。参考项目内联当前消息的思路，可以评估一次只读查询返回当前待处理消息正文与发言者，减少一个串行工具调用，不增加对话历史。

## Derpyu520/qq-bridge

源码提交：`9df6a7e7fc5abcb36793337f778483bd442a3d2d`。

### 实际链路

QQ → SnowLuma OneBot v11 WebSocket → 桥接 → 本地 DSH `session/prompt` → DSH 模型/工具执行 → 本地事件流 → QQ。

`deliverPromptNow` 最终调用 `api.sessions.prompt({ sessionId, mode: 'queue', content })`。回复事件通过 `/api/remote.mux` WebSocket 中的 `session/follow` 接收。这里的推送是 DSH 本地会话能力，并非 OpenAI dot 的事件回调。

来源：[投递会话消息](https://github.com/Derpyu520/qq-bridge/blob/9df6a7e7fc5abcb36793337f778483bd442a3d2d/src/bridge.js#L8396-L8469)、[事件流连接与会话订阅](https://github.com/Derpyu520/qq-bridge/blob/9df6a7e7fc5abcb36793337f778483bd442a3d2d/src/dsh-client.js#L667-L744)。

### 能借鉴的机制

1. **将当前消息随唤醒一起提交，减少重复读取。** `buildWakeSnapshotV2` 的结果直接附加到会话消息；只有快照不完整时才继续取未读。这一机制能够减少协议上的读取往返，但该仓库未给出节省毫秒数。本项目先前存在事件载荷在 dot 上下文不可见的问题，所以要先验证载荷实际可见，或者另行评估合并“列出待处理与读取内容”接口；不直接假定内联已经可用。

   来源：[唤醒消息快照与提交](https://github.com/Derpyu520/qq-bridge/blob/9df6a7e7fc5abcb36793337f778483bd442a3d2d/src/bridge.js#L8430-L8452)。

2. **短静默从最后来信计时，不在处理完后重新完整等待。** 提示构造明确将合批和读取提示的时间计入静默期；剩余静默为零时直接回复。长时间观察放在准备休眠阶段，不要求首回复先等待数分钟。这是避免重复人为等待的设计，不能消除模型生成或平台排队。

   来源：[首回复节奏与休眠观察](https://github.com/Derpyu520/qq-bridge/blob/9df6a7e7fc5abcb36793337f778483bd442a3d2d/src/bridge.js#L9453-L9475)。

3. **断流后恢复订阅，避免永久不回应。** `session/follow` 正常结束后，若仍在期望订阅集合中，2 秒后重开；发送订阅失败会清除状态并结束流，交给上层重连。这主要改善可用性，不是已量化的延迟优化。

   来源：[订阅失败清理](https://github.com/Derpyu520/qq-bridge/blob/9df6a7e7fc5abcb36793337f778483bd442a3d2d/src/dsh-client.js#L735-L743)、[流结束后重订阅](https://github.com/Derpyu520/qq-bridge/blob/9df6a7e7fc5abcb36793337f778483bd442a3d2d/src/dsh-client.js#L846-L867)。

4. **批处理本身会增加等待。** 二代群聊唤醒默认合批 8 秒，最短 1 秒；繁忙会话先积压唤醒原因，之后再执行。减少唤醒次数和降低单条消息等待之间有取舍，不能照搬为低延迟方案。

   来源：[合批及繁忙等待](https://github.com/Derpyu520/qq-bridge/blob/9df6a7e7fc5abcb36793337f778483bd442a3d2d/src/bridge.js#L9675-L9718)。

### 未知

已检查源码未给出 SnowLuma 与 QQ 官方机器人在相同网络、同一模型、同一消息上的延迟对照；未核验 SnowLuma 专有内部实现。因此没有依据断言更换 QQ 接入会解决当前 dot 等待。

## AstrBot

源码提交：`595f990b6447236d6b48c6b62836d67ef74749c9`。

### 实际链路

所检查的 OneBot 路线由平台适配器接收群或私聊事件并提交本地队列；事件总线从队列取得消息，创建异步调度任务。OpenAI 兼容 provider 直接调用 `chat.completions.create`，支持流式响应。它并不经过 dot 自动化事件订阅。

来源：[群私聊事件入口](https://github.com/AstrBotDevs/AstrBot/blob/595f990b6447236d6b48c6b62836d67ef74749c9/astrbot/core/platform/sources/aiocqhttp/aiocqhttp_platform_adapter.py#L85-L105)、[入队](https://github.com/AstrBotDevs/AstrBot/blob/595f990b6447236d6b48c6b62836d67ef74749c9/astrbot/core/platform/sources/aiocqhttp/aiocqhttp_platform_adapter.py#L500-L510)、[异步调度](https://github.com/AstrBotDevs/AstrBot/blob/595f990b6447236d6b48c6b62836d67ef74749c9/astrbot/core/event_bus.py#L35-L55)、[模型流式请求](https://github.com/AstrBotDevs/AstrBot/blob/595f990b6447236d6b48c6b62836d67ef74749c9/astrbot/core/provider/sources/openai_source.py#L621-L650)。

### 能借鉴的机制与限制

- **接收与执行分离**：异步调度使入口不用等待上一条模型回答才取下一条事件。不过队列、同一会话约束和模型服务仍可能产生等待；源码形态不是低延迟基准。
- **流式分段减少首段等待**：OneBot 消息事件实现可按标点将累积文本发送；非实时分段模式则收完流再发送。分段发送还包含限速等待。它主要改善第一段出现时间，不保证整段回答更快，而且会改变本项目“一条消息只回复一次”的结果，不能默认为当前优化。

来源：[流式发送、缓冲和限速](https://github.com/AstrBotDevs/AstrBot/blob/595f990b6447236d6b48c6b62836d67ef74749c9/astrbot/core/platform/sources/aiocqhttp/aiocqhttp_message_event.py#L200-L234)。

## 对本项目的影响

| 方向 | 可借鉴内容 | 仍须验证 |
|---|---|---|
| 回调可靠性 | 清晰区分连接失败、订阅失效与任务等待，失败后保持可恢复状态 | 现有失败究竟发生在 DNS、连接、TLS、代理还是响应阶段 |
| dot 首次拿到消息 | 消息随事件携带或减少读取次数 | dot 实际上下文能否取得载荷；每次工具往返真实耗时 |
| 人为等待 | 从消息到达起计算合批/静默，避免叠加等待 | 本项目当前是否真的存在这类等待，不预先加入参数 |
| 模型直接调用 | 对照架构省去 dot 任务触发环节 | 会更换既有运行及上下文方式，属于需讨论的架构选择 |
| 流式分段 | 首段更早显示 | 改变单次回复规则；不是当前默认实施项 |

当前研究支持先拆清现有回调路径与工具往返，再选择最小修改；不支持承诺通过更换 SnowLuma、添加 WebSocket 或启用流式即可达到十秒目标。
