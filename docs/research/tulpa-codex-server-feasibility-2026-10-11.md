# 服务器 Codex CLI OAuth 与 Tulpa 可行性

## 结论

服务器运行 Codex CLI，以 ChatGPT OAuth 登录后接入 MCP，在技术上可行。Tulpa 能作为 MCP 服务供 Codex 读取并回复 QQ 群消息，但当前成品使用 OneBot 与本机 QQ 客户端，尚未提供本项目 QQ 开放平台官方机器人的即插即用适配。若保留官方机器人，更小的改动是继续使用现有 QQ 桥接，将 dot 云端事件唤醒替换为服务器上的 Codex 会话驱动；Tulpa 的等待与批次接口可按需借鉴。

核验日期：2026-10-11。Tulpa 源码固定提交：[`d91c980677197ca4322e083d83937c2883cc943a`](https://github.com/fumingyang2004/Tulpa/tree/d91c980677197ca4322e083d83937c2883cc943a)。本结论来自源码和官方文档，未安装、启动或登录第三方项目，未实测目标服务器。

## Codex 登录与会话驱动

官方支持无浏览器服务器使用 `codex login --device-auth`；设备码登录需要账户安全设置或工作区策略允许。登录凭据应保留在服务器持久目录，活跃使用期间会刷新令牌。OAuth 路径仍受账户额度和工作区权限约束；官方对自动化默认推荐 API Key。登录成功不等于无限持续执行或不限额。[Codex 鉴权文档](https://learn.chatgpt.com/docs/auth)

Codex `app-server` 通过默认 stdio 提供 `thread/start`、`thread/resume`、`turn/start` 和执行通知，可由桥接服务持有群与线程的映射。采用此路径时，同一群的原生上下文属于对应的 Codex 线程；不会自动继承此前 dot 聊天。桥接端仍需负责进程生命周期、线程映射、单群串行及异常恢复。[Codex app-server 文档](https://learn.chatgpt.com/docs/app-server)

## Tulpa 当前实际执行链路

```text
本机 QQ / OneBot v11 HTTP + 正向 WebSocket
  → Tulpa EventReceiver
  → SQLite chat_inbox
  → Codex 已发出的 wait_chat_messages 阻塞调用返回消息
  → 同一 Codex Agent 调用 plan_chat_reply
  → 按条件调用 select_chat_expressions
  → send_chat_reply 经 OneBot 发送
  → Codex 再次调用 wait_chat_messages
```

Tulpa 群聊模块自身不调用 LLM。Codex 接入教程只配置 HTTP MCP、Bearer Token 和工具超时，没有启动 `codex exec`、SDK 或 `app-server` 的群聊守护流程。官方仓库明确要求外部 Agent 持续执行；Agent 回合结束、额度耗尽、退出或休眠后，Tulpa 不会自动重新启动它。[群聊模块](https://github.com/fumingyang2004/Tulpa/blob/d91c980677197ca4322e083d83937c2883cc943a/chatlocal/mcp_chat.py#L1-L3)、[Codex 配置](https://github.com/fumingyang2004/Tulpa/blob/d91c980677197ca4322e083d83937c2883cc943a/doc/AGENT_SETUP.md#L39-L59)、[持续运行条件](https://github.com/fumingyang2004/Tulpa/blob/d91c980677197ca4322e083d83937c2883cc943a/doc/AGENT_SETUP.md#L260-L268)

### 等待与持久化

- `wait_chat_messages` 默认最长等待 45 秒，上限 180 秒。收到新消息后结合短静默条件返回，内部事件可唤醒等待，检查间隔最多约 0.4 秒；不是固定等满 45 秒。[参数](https://github.com/fumingyang2004/Tulpa/blob/d91c980677197ca4322e083d83937c2883cc943a/chatlocal/mcp_chat.py#L48-L56)、[等待实现](https://github.com/fumingyang2004/Tulpa/blob/d91c980677197ca4322e083d83937c2883cc943a/chatlocal/mcp_chat.py#L483-L567)
- 等待结果直接含 `messages` 正文、消息水位与批次信息，无需先列 ID 再逐条读取。它还会返回下一次调用建议，但由外部 Agent 执行；返回 `continue_waiting` 本身不是进程守护。[返回结构](https://github.com/fumingyang2004/Tulpa/blob/d91c980677197ca4322e083d83937c2883cc943a/chatlocal/mcp_chat.py#L530-L563)
- SQLite 保存群聊 session、人格快照、消息游标、收信与发送状态。重启时将旧心跳置零并增加接收中断计数；这些状态不等同于 Codex 原生会话或自动恢复推理。[持久化表和重启处理](https://github.com/fumingyang2004/Tulpa/blob/d91c980677197ca4322e083d83937c2883cc943a/chatlocal/mcp_chat.py#L74-L120)

## 与现有官方 QQ 机器人的兼容缺口

Tulpa 使用 OneBot 的 `self_id`、数值 `group_id`、数值 `sender_id`，并调用 `get_group_list`、`get_group_member_info` 等接口。群成员身份与引用目标校验依赖这些标识和 OneBot 查询；现有项目使用开放平台 `group_openid` / 成员 OpenID，两套标识及功能接口需映射，单填现有 AppID/AppSecret 不足以接通。[OneBot 读取接口](https://github.com/fumingyang2004/Tulpa/blob/d91c980677197ca4322e083d83937c2883cc943a/chatlocal/onebot.py#L24-L28)、[群目录](https://github.com/fumingyang2004/Tulpa/blob/d91c980677197ca4322e083d83937c2883cc943a/chatlocal/mcp_chat.py#L634-L642)、[身份校验](https://github.com/fumingyang2004/Tulpa/blob/d91c980677197ca4322e083d83937c2883cc943a/chatlocal/mcp_chat.py#L569-L589)

可复用的是消息批次、游标、同群单 Agent 等待、幂等发送、人格文件与细粒度权限；保留官方机器人时，接收器、消息标识、发送器和相关校验必须适配。不必为了使用 Codex OAuth 一并更换 QQ 接入。

## 服务器与权限条件

Tulpa 发布和源码启动文档面向 Windows x64、Python 3.13；桌面壳依赖 .NET Framework 4.8 / WebView2。不过 `app_mcp.py` 确有独立 Python/FastAPI 入口，可启动本机网页及 MCP 服务，因此后端并非只能由 EXE 启动。已检查的核心收信、SQLite 和 MCP 模块主要是 Python；Linux 服务器能否直接安装当前固定依赖、启动全部导入模块，仍需独立验证，当前不按已支持 Linux 成品交付判断。[运行说明](https://github.com/fumingyang2004/Tulpa/blob/d91c980677197ca4322e083d83937c2883cc943a/README.md)、[Python 入口](https://github.com/fumingyang2004/Tulpa/blob/d91c980677197ca4322e083d83937c2883cc943a/app_mcp.py#L8-L52)、[轻量版依赖](https://github.com/fumingyang2004/Tulpa/blob/d91c980677197ca4322e083d83937c2883cc943a/requirements/mcp.txt)

MCP 默认绑定回环地址并校验 Host、Origin 和来源地址；OneBot HTTP/WS 配置也只接受回环地址。服务器 Codex 与 Tulpa 同机部署符合这种结构，跨机器直连则不是现成配置路径。[MCP 服务限制](https://github.com/fumingyang2004/Tulpa/blob/d91c980677197ca4322e083d83937c2883cc943a/chatlocal/mcp_server.py#L90-L102)、[OneBot 配置限制](https://github.com/fumingyang2004/Tulpa/blob/d91c980677197ca4322e083d83937c2883cc943a/chatlocal/onebot.py#L46-L56)、[WS 限制](https://github.com/fumingyang2004/Tulpa/blob/d91c980677197ca4322e083d83937c2883cc943a/chatlocal/onebot_events.py#L32-L40)

Tulpa 按连接限制账号、群、日期和媒体/发送权限，发送获授权后直接执行；Codex 的工具权限、文件访问及审批仍是另一层配置。运行服务器机器人时需要保留现有测试群边界并明确工具许可，不应默认沿用个人开发会话的全部工具。[授权实现](https://github.com/fumingyang2004/Tulpa/blob/d91c980677197ca4322e083d83937c2883cc943a/chatlocal/mcp_access.py)、[客户端权限说明](https://github.com/fumingyang2004/Tulpa/blob/d91c980677197ca4322e083d83937c2883cc943a/doc/AGENT_SETUP.md#L260-L268)

## 对延迟的意义

相较当前 dot 方案，服务器同机 Codex + MCP 可以移除事件 callback、云端自动任务调度和工具隧道三项中间环节，并在等待返回时一次拿到正文。模型生成、工具规划轮次和 QQ 发信仍存在，因此目前只成立架构上的减项，尚无可承诺的端到端秒数。

Tulpa 本身还引入自然聊天节奏：默认短静默 2 秒、最大收集 8 秒、回复冷却 3 秒；多气泡之间有 1.2–4 秒间隔。Planner / Replyer 是同一外部 Agent 的阶段，有表达候选时还需一次选择工具调用。因此全量搬用 Tulpa 不保证比简洁 Codex 桥接更快。[节奏默认值](https://github.com/fumingyang2004/Tulpa/blob/d91c980677197ca4322e083d83937c2883cc943a/chatlocal/mcp_chat_turns.py#L16-L21)、[执行顺序](https://github.com/fumingyang2004/Tulpa/blob/d91c980677197ca4322e083d83937c2883cc943a/doc/MCP_CHAT_TURNS.md#L3-L13)

## 推荐的验证边界

先验证服务器 Codex OAuth 登录、同一线程连续两轮上下文、一次本机 MCP 调用；再在保留现有官方 QQ 桥接的情况下，用一个测试群驱动 Codex 同一线程，比较 QQ 收信到生成开始、生成到发信的时间。Tulpa 先作为接口与群聊行为参考；如明确改走 OneBot，再评估完整产品部署。目标服务器系统、服务器网络可达性、账户设备码策略、额度与无人值守恢复仍待确认。

## 许可证

Tulpa 自有代码是 MIT，复用时保留版权和许可声明；其依赖另有许可。第三方清单特别区分了独立 FFmpeg 可执行文件的 GPL-3.0-or-later，以及未随产品分发的 SnowLuma/NapCat/QQ。仅借鉴或复用少量源代码不等于需要部署整个桌面/媒体包。[MIT](https://github.com/fumingyang2004/Tulpa/blob/d91c980677197ca4322e083d83937c2883cc943a/LICENSE)、[第三方清单](https://github.com/fumingyang2004/Tulpa/blob/d91c980677197ca4322e083d83937c2883cc943a/doc/THIRD_PARTY.md)

