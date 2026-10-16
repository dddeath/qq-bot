# Gemini CLI 接入 QQ 机器人可行性

核对日期：2026-10-14。证据来自 Google 官方文档与 `google-gemini/gemini-cli` 官方仓库；代码核对固定在稳定版 `v0.64.0`。本报告未安装 CLI、登录账号、连接机器人服务器或调用模型。

## 结论

**优先验证“Google AI Pro 账号登录官方 Gemini CLI → headless 子进程 → 现有 QQ MCP 工具”这一条路线。** 官方登录文档确认订阅账号可使用 Google 登录，已有登录缓存可由 headless 模式复用；因此技术验证不必先切换到 API 按量计费。[官方认证说明](https://geminicli.com/docs/get-started/authentication/)

当前最明确的目标模型是 **`gemini-3.8-flash`**：稳定版源码已包含该 ID，但最新 Flash 的别名映射受账号/服务端实验开关控制，实际订阅账号是否获得权限仍待验证。Gemini 4 Argon 已有官方模型卡；本轮核对的 CLI 内建模型表未列出 Argon，尚无证据确认该订阅账号能经 CLI 使用它。[v0.64.0 模型定义](https://github.com/google-gemini/gemini-cli/blob/v0.64.0/packages/core/src/config/models.ts#L54-L149) · [Argon 官方模型卡](https://deepmind.google/models/model-cards/gemini-4-argon/)

**技术链路值得做小规模验证，长期多人 QQ 服务的订阅适用性仍待 Google 明确答复。** 官方明确禁止第三方软件直接复用 CLI OAuth 访问 Code Assist 后端；本路线只调用官方 CLI，不提取 OAuth 令牌自建后端客户端。官方 headless 功能说明也没有直接给出“单个人订阅可向 QQ 群成员持续转供服务”的许可。[CLI 条款](https://geminicli.com/docs/resources/tos-privacy/) · [headless 接口](https://geminicli.com/docs/cli/headless/)

## 版本与模型证据

| 项目 | 本轮确认 | 对接影响 |
| --- | --- | --- |
| 最新稳定版 | GitHub `releases/latest` 实际跳转到 `v0.64.0`，发布页显示 10 月 13 日，提交短号 `4a0749a` | 首轮实验固定版本，记录 `gemini --version`；不以搜索摘要中的旧版本作为当前版本 |
| Flash 3.8 | `LATEST_GEMINI_FLASH_MODEL = 'gemini-3.8-flash'`；`hasLatestFlashGAAccess` 参与选择和后端映射 | 用精确 ID 验证，记录实际模型统计和降级提示 |
| 默认/别名 | `flash` 及旧 Flash ID 存在按开关映射；模型 ID 出现在源码不代表账号获准调用 | 不能仅凭 UI 标签或 CLI 接受参数宣告模型接入成功 |
| Gemini 4 Argon | 官方模型卡存在；上述版本的内建模型集合未见 Argon | 保留“待账号模型目录/实际请求验证”，不猜测 CLI 模型 ID |
| 文档时效差异 | `/model` 文档仍显示 Gemini 3 / 2.5，页面更新日期为 2026-03-19 | 模型清单以固定版本源码与真实账号结果交叉验证 |

来源：[稳定版发布页](https://github.com/google-gemini/gemini-cli/releases/tag/v0.64.0)、[模型解析与开关](https://github.com/google-gemini/gemini-cli/blob/v0.64.0/packages/core/src/config/models.ts#L195-L336)、[模型选择文档](https://geminicli.com/docs/cli/model/)、[Argon 模型卡](https://deepmind.google/models/model-cards/gemini-4-argon/)。

## 订阅登录与运行方式

- 使用订阅对应的个人 Google 账号完成官方交互登录；凭据由 CLI 本地缓存。个人 Google AI Pro / Ultra 在官方支持列表内，多数个人账号不要求 Cloud project。
- headless 可以复用已有认证缓存；尚未登录时，文档提供的纯环境变量认证方式是 API key 或 Vertex AI。首次交互登录与后续无人值守运行应分别验证。
- 同一机器、同一操作系统用户下的缓存复用有直接文档支持；跨机器搬迁凭据、服务账户与桌面账户共享缓存、无限期无人干预运行均没有在本次资料中获得保证。服务器首次登录与刷新应另外核验，不默认复制本机凭据。

来源：[认证方式及 headless 缓存复用](https://geminicli.com/docs/get-started/authentication/)。

官方配额页列出 Google AI Pro 每用户每天最多 **1,500 次模型请求**，同时存在每分钟限制及高需求时的服务可用性约束。工具循环可能产生多次模型请求，因此不能把该数字直接换算成 1,500 条 QQ 回复。该页将订阅与 API 按量计费分开，实际账号配额以 `/stats model` 显示为核验入口；本轮未读取账号配额。[配额与订阅说明](https://geminicli.com/docs/resources/quota-and-pricing/)

## QQ 接入所需能力

| 能力 | 官方证据 | 实际接入待验 |
| --- | --- | --- |
| headless 程序调用 | `-p` 或非 TTY 触发；`--output-format stream-json` 输出 JSONL，包括 `init`、消息、工具调用/结果、错误及最终结果 | 子进程退出、stderr、最终结果与重启后的行为 |
| MCP HTTP | 支持 Streamable HTTP，配置键为 `httpUrl`；SSE 使用 `url`；可配请求头及工具包含列表 | 现有 QQ MCP 的握手、工具 schema 与鉴权兼容性 |
| 长等待 | `timeout` 单位为毫秒，默认 600000；固定版源码将值传给 SDK `callTool` | 等待工具跨超时、代理断连、进程取消时的结果；不把进度通知视为自动无限续期 |
| 图片输入 | MCP `image` 数据块具有 `data`、`mimeType`；源码转换为 `inlineData` | 用实际图片内容测试识别，不能仅核对 URL 或文件名 |
| 会话恢复 | 自动记录对话及工具输入输出；按项目目录划分历史；`--resume <UUID>` 可恢复 | 为各 QQ 会话保存明确 UUID；跨群不使用“最新会话”恢复 |

来源：[headless 输出及退出码](https://geminicli.com/docs/cli/headless/)、[MCP 配置](https://geminicli.com/docs/tools/mcp-server/)、[v0.64.0 超时传递](https://github.com/google-gemini/gemini-cli/blob/v0.64.0/packages/core/src/tools/mcp-client.ts#L1324-L1396)、[图片转换源码](https://github.com/google-gemini/gemini-cli/blob/v0.64.0/packages/core/src/tools/mcp-tool.ts#L553-L569)、[会话管理](https://geminicli.com/docs/cli/session-management/)。

图片能力的证据覆盖“读取图片作为模型上下文”；发送 QQ 图片仍由现有 QQ 工具完成。图片生成不在这些证据确认的能力之内。

长等待方面，源码设置请求超时并注册进度 token，但该调用没有显式传入 `resetTimeoutOnProgress`。因此建议测量实际等待窗口，再决定等待工具的超时参数；不据此承诺持续数小时挂起稳定运行。[MCP 调用实现](https://github.com/google-gemini/gemini-cli/blob/v0.64.0/packages/core/src/tools/mcp-client.ts#L1343-L1367)

## 订阅用于自有 QQ 机器人的明确限制与未知

1. **明确限制：第三方软件直接访问 CLI 后端。** 官方条款点名第三方工具使用 CLI OAuth 直接访问 Code Assist 属于违反适用条款/政策，可能导致账号暂停或终止。将令牌提取到 QQ provider、自建兼容 API 或第三方代理不属于本报告推荐路线。[CLI 条款](https://geminicli.com/docs/resources/tos-privacy/)
2. **明确限制：订阅请求配额及服务容量。** 固定订阅有配额，长期循环、工具多轮与机器人并发都会影响可用性；额度耗尽时应返回可识别状态，不自动引入新的付费认证方式。[官方配额页](https://geminicli.com/docs/resources/quota-and-pricing/)
3. **明确义务：内容权利与服务使用行为。** Google 通用条款禁止垃圾信息、绕过保护措施、侵犯隐私权等行为；上传群聊内容应具有相应权利，并遵守适用服务条款。[Google 服务条款](https://policies.google.com/terms/embedded?hl=en-US)
4. **仍待确认：多人群聊长期转供。** 官方提供程序化 headless 功能，说明自动化接口本身成立；现有来源没有明确确认“个人订阅经官方 CLI 为第三方群成员持续提供通用聊天服务”的适用范围。应向 Google 提供准确架构和用途确认，而非从开源许可证或登录成功推导服务授权。
5. **仍待确认：账号对应的数据条款。** CLI 条款按认证后端指向不同服务条款；Code Assist 当前隐私入口又重点列出 Standard/Enterprise。不能把企业数据保障直接套给个人 AI Pro。上线真实群聊前需核对实际账号登录时接受的条款及 `/privacy` 展示内容。[CLI 条款入口](https://geminicli.com/docs/resources/tos-privacy/) · [Code Assist 隐私入口](https://developers.google.com/gemini-code-assist/resources/privacy-notices)

## 推荐验证顺序

以下为后续验证计划，尚未执行；由主控确认执行范围后开展。

1. **账号及模型。** 固定 `v0.64.0`，在独立测试目录使用订阅账号完成官方登录，保存版本、`/model` 与 `/stats model` 的去敏结果。先验证 `gemini-3.8-flash` 最短文本请求，检查实际模型及错误/降级信息；Argon 仅在账号显示可用的精确 ID 后另测。
2. **缓存与 headless。** 退出交互会话后，在同一用户下执行 `gemini -m gemini-3.8-flash -p "仅回复 READY" --output-format stream-json`；保存字面输出、退出码、认证方式及 session ID。随后重启进程再测，不切到 API key。
3. **MCP 与图片。** 仅连接本地测试 MCP，先暴露文本回显和图片读取工具；验证 HTTP 握手、单次调用、PNG 内容识别。QQ 发送工具保持未接入。
4. **长等待。** 本地等待工具分别测试短等待、超过 60 秒、接近配置超时，以及主动取消；记录真实耗时、工具返回和进程结果。大于 10 分钟的需求另设 timeout 后单独测，不以文档默认值代替实测。
5. **恢复隔离。** 建立两条带不同识别短语的测试会话，用各自完整 UUID 恢复，验证上下文正确且互不串入；记录新进程使用的 cwd。
6. **再决定真实 QQ 验收。** 前述技术测试通过并确认订阅用途后，只在指定测试群核对收消息、读图片、生成与发送。实际吞吐、延迟、限额和长期刷新问题以这一步结果判断。

每轮验证使用独立时间戳目录保存命令、输入、字面输出、退出状态和去敏版本/账号状态。连续两次执行检查目录独立、前次产物哈希不变。成功标准是所需行为被核验，而非只启动 CLI 或取得零退出码。

## 当前交付状态

已完成官方资料与固定版本源码核对。技术推荐为官方 CLI 订阅登录路线；Flash 3.8 实际账号权限、HTTP MCP 集成、图片识别、长等待、会话恢复及长期 QQ 使用适用性均仍待上述验证。本轮唯一交付物为本报告，未更改机器人代码或运行配置。
