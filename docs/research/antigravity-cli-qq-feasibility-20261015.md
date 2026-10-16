# Antigravity CLI 接入 QQ 机器人可行性

核对日期：2026-10-15（UTC+8）。本轮仅查阅 Google 官方资料并生成报告，未安装、登录、调用模型或修改服务器。文档列出的能力尚未在当前账号与服务器上验证。

## 结论

**技术路线值得先做隔离验证：官方 `agy` 已具备 Linux 安装、SSH 登录、持续多轮进程、会话恢复和 MCP。** Google AI Pro 文档列有 Gemini 3.8 Flash，符合此前接受 Flash 的目标。下一步应先验证官方 CLI 的订阅登录和两轮上下文，再决定 QQ 接入；当前不再把旧 Gemini CLI 的登录成功当成 Antigravity 可用证据。[安装与登录](https://antigravity.google/docs/cli/install/) · [模型与套餐](https://antigravity.google/docs/models/) · [Headless](https://antigravity.google/docs/cli/headless/)

**QQ 桥接的条款适用性仍需核对。** 官方提供程序驱动 CLI 和自定义 MCP，但附加条款第 6 项同时限制第三方软件、工具或服务访问，明确举出 OpenClaw 使用 Antigravity OAuth 的例子，并提到停用账号的后果。本轮资料没有明确解释“个人订阅通过官方 CLI 向 QQ 群持续提供聊天”的适用边界，不能仅凭 headless 接口存在就认定已获许可。[附加条款第 6 项](https://antigravity.google/terms)

## Linux、SSH 与现有凭据

官方安装目标是 `~/.local/bin/agy`，支持 Linux；提供 `--skip-aliases`、`--skip-path` 以避免安装器调整别名和 PATH。SSH 环境有手工授权流程：远端打印 URL，在另一设备浏览器登录，再把授权码交回终端。按该文档，首次登录不要求服务器运行桌面浏览器。[安装与 SSH OAuth](https://antigravity.google/docs/cli/install/)

凭据默认使用系统 keyring，Linux 对应 Secret Service/D-Bus。当前无桌面服务器是否有可用 keyring、后台服务进程能否读取，以及刷新后的持续运行，需要实测；文档没有在该页给出无 keyring 的明确回退保证。[凭据存储](https://antigravity.google/docs/cli/install/)

迁移页说明首次启动可选择迁移旧配置及有效会话令牌到 keyring。此前凭据位于自定义的 `/home/ubuntu/gemini-test/home/.gemini/`，是否被发现、令牌是否适用新服务仍待验证，不复制令牌到自建客户端。规则可使用工作区 `GEMINI.md` / `AGENTS.md`；工作区技能为 `.agents/skills/`。[迁移说明](https://antigravity.google/docs/cli/gcli-migration/)

## 模型、思考强度与订阅额度

| 项目 | 官方资料 | 当前建议 |
| --- | --- | --- |
| Google AI Pro | 列有 Gemini 3.8 Flash；Gemini 4 Argon 列于 Ultra / Enterprise | 先验证 Flash，保留账号实际目录证据 |
| 模型固定 | `agy models` 列出 slug；文档示例有 `gemini-3.8-flash-medium` | 安装后读取实际目录，不猜 `low` slug |
| 思考强度 | `--effort` 可覆盖本次调用，支持级别由当前模型决定 | 用 `agy -p "/effort" --output-format json` 核对，再固定支持的值 |
| 原网页可用模型 | 不构成本 CLI 套餐权限证明 | 以登录账号的实际模型请求核验 |

来源：[模型权限表](https://antigravity.google/docs/models/) · [模型参数](https://antigravity.google/docs/cli/headless/#select-a-model-effort-or-agent) · [effort 命令](https://antigravity.google/docs/cli/commands/effort/)。

Pro 的基础额度按五小时刷新，另有周上限；消耗随工作量变化，不能按固定“群消息条数”换算。额度耗尽时可停等刷新；设置 **AI Credit Overages = Never**，CLI 同时确认 **`useG1Credits: false`**，避免启用积分兜底。实际账号额度和开关尚未读取。[套餐与额度](https://antigravity.google/docs/plans) · [CLI 积分设置](https://antigravity.google/docs/cli/credits/) · [配置默认值](https://antigravity.google/docs/cli/reference/)

## 机器人运行接口

| 能力 | 已有文档依据 |
| --- | --- |
| 单次验证 | `agy -p "..." --output-format json`，返回会话 ID、状态、回答 |
| 持续多轮 | `agy --input-format stream-json --output-format stream-json`；每轮等待 `result` 再提交下一条 |
| 恢复 | `--conversation ID` 指定原会话 |
| 计时 | 持续进程的 `duration_seconds`、`usage` 为累计值；`response` 属于本轮 |
| 轨迹 | `step_update` 提供工具参数、输出和已知耗时，子代理带关联信息 |
| 输入限制 | stdin 只接受文本块；图片块会使会话报错退出 |
| 审批 | headless 需预设权限；工具被拒绝时进程仍可能返回 0，须核对工具回执 |

来源：[Headless 接口](https://antigravity.google/docs/cli/headless/)。

MCP 支持本地 stdio、远程 Streamable HTTP/SSE。工作区配置为 `.agents/mcp_config.json`，远程字段使用 `serverUrl`，全局配置为 `~/.gemini/config/mcp_config.json`。[MCP 配置](https://antigravity.google/docs/mcp)

**图片能力待实测：**当前文档证明了 MCP 连接方式，但没有证明当前模型通过 Tulpa 返回的 MCP 图片内容能完成视觉理解。可先用测试 MCP 返回真实图片，要求描述仅图内可见的随机信息；单纯读到图片 URL 或路径不算通过。

## 最小对接设计与验收顺序

以下为项目方案推断，尚未实施：

1. **隔离 CLI 验证。** 独立工作目录，先核对安装版本、登录、模型目录及积分关闭设置。用固定回答和两轮随机代号测试上下文，不连接 QQ。
2. **离线 MCP 验证。** 连接仅含测试数据的 MCP，验证工具发现、结构化结果、图片与审批规则；保留工具真实返回及异常。
3. **确认桥接适用边界。** 就个人订阅与多人群聊用途核对 Google 官方说明后，再决定持续 QQ 服务。
4. **限定测试群接入。** 沿用原定账号 `1000000009`、群 `2000000003` 和明确 @ 触发范围；复用既有 QQ 收发组件，替换模型运行器。当前白龙娘运行器不变。
5. **常驻而非逐条启动。** 每个群绑定独立会话 ID，同进程按队列串行提交；异常重启恢复指定 ID。适配器持久化 QQ message ID 与发送回执，发送结果未知不自动重发。

建议采用的候选链路：

```text
测试账号 QQ 事件
  → 群/@/消息去重
  → agy 常驻 stream-json 会话
  ↔ 既有 MCP 工具（先测试再逐项开放）
  → 当前轮 result + 工具回执
  → 原群回复与独立时间线
```

验收同时记录入队、提交、首输出、工具起止、最终结果和 QQ 发送回执。CLI 累计计数与桥接层逐轮计时分别保存；缺失耗时留空。图片先走工具读取候选路径，不向 stdin 填入文档未支持的图像块。

## 当前尚未通过的实际验证

- 当前 Google 账号获得 Antigravity 订阅服务和 Flash 调用权限。
- 服务器无桌面会话的 keyring、令牌迁移及后台刷新。
- 本地模型目录、可用 effort、首轮/后续轮延迟与稳定性。
- Tulpa MCP 图片是否真正进入模型视觉输入。
- MCP 读写权限规则和 QQ 发送回执的准确关联。
- 个人订阅用于当前多人 QQ 桥接的条款适用边界。

本报告没有进行安装、登录或模型测试，也未改变现有 QQ 服务。
