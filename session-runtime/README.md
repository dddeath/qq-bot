# Unified CLI sessions

控制台与 MCP 使用稳定的 session_id；harness 为 codex 或 antigravity，native_session_id 用于恢复原生上下文。模型、思考强度、账号、群、状态存于同一会话记录。

## MCP

`python mcp_server.py --config CONFIG.json` 提供 stdio MCP：session_create、session_list、session_get、session_history、session_send。
配置包含 database、evidence、harnesses。每个 harness 具有 command（参数数组）、cwd、可选 env、timeout_seconds。
配置只供主控管理，不暴露为群消息可修改的工具。stdio 通过现有 SSH 通道使用，不新增公网端口。

session_send 使用 request_id 去重，恢复已存 native_session_id，记录输入、回答、原始CLI事件、退出状态、耗时和证据路径。相同请求不重复执行；结果未知的会话停在 unknown。运行期间中断的记录保持 running，主控核对进程与原生轨迹后再决定恢复，不自动重放。

当前执行器每条请求启动CLI并恢复原生线程；尚未将Antigravity常驻进程纳入管理。白龙娘现有运行器已通过 session_adopt 纳入目录、状态与轨迹读取，执行控制继续由原运行器负责。控制台前端尚未接入。

## QQ测试入口

`python qq_worker.py --config CONFIG.json` 在已有配置上增加 session_id、qq（http/ws/token）、event_log、test_window_seconds（默认600）。需要现有websockets库。
仅处理绑定账号、绑定群、明确@、非自身、启动后到达的文字消息。会话绑定的工具规则决定可调用的资料工具；未绑定时沿用知识库两工具规则。QQ 图片消息输入与图片发送未在该入口接通。
消息持久化去重；每次发送前核对实际登录账号，先预留发送状态再请求QQ。成功记录message_id，发送结果未知不自动重发。
qq_worker接收进程一次只处理一个模型请求，WebSocket心跳继续运行。执行时间计入会话历史与CLI证据。

## 验证

`python verify.py` 每次创建独立时间戳目录，保存测试输出、退出码、源码归档和补丁。测试覆盖统一会话持久化、恢复、去重、原生事件转换、审批拦截、MCP入口、QQ账号/群/@边界和发送未知状态。外部CLI与QQ边界使用测试替身；真实结果另存于服务器session-evidence。

## 停用与回退

停止本次qq_worker进程即可停用测试接收；不调用旧Codex运行器的stop脚本。MCP以stdio启动，退出其进程即可停用。数据库、证据及原生线程保留。
新增源代码位于session-runtime，服务器使用独立时间戳stage，未替换线上Tulpa文件；没有修改控制台工作树。

## 已有白龙娘运行器

`session_adopt` 登记现有运行目录、原生线程 ID 和 Tulpa 会话 ID；不启动、终止或恢复进程。统一列表和详情读取进程状态，历史入口读取原有 `run.jsonl`，原始证据保留原位。`management=existing-runner` 的会话由现有聊天运行器持续接收消息，`session_send` 拒绝另启同一线程，避免重复执行。运行器控制仍沿用 `control_current.py`；本次没有把停止、恢复功能加入 MCP。

原生线程已登记时，`session_create` 拒绝重复登记。解除接管调用 `Sessions.detach(session_id)`，仅移除统一目录条目，保留正在运行的聊天及原证据。服务器验收目录中的 `rollback.py` 提供该操作。

Gemini 与 Codex 可指向同一版本化知识库根目录，各自配置账号和群标识。公开领域文档共享，成员正文按账号和群过滤。人格卡单独审核和加载。

## 配置对象与继承

`ControlPlane` 与 `Sessions` 使用同一个 SQLite 数据库。`bot`、`learning_job`、`tool_profile` 是版本化配置对象；Session 记录用途和原生线程；`session_runs` 返回现有执行记录。

- Bot 引用固定版本 ToolProfile。`bot_inherit` 复用来源机器人的工具配置引用，要求传入新账号和绑定参数；不复制来源人格或 QQ 凭据。
- LearningJob 引用用途为 learning 的 Session。既有每日学习仍由原调度器执行；各批原生线程从对应执行日志读取。
- Session 的 `runtime_refs` 引用人格以外的实际配置文件、工具快照和执行器配置。`harness_config` 可为每个会话指定独立 command、cwd、env 和 timeout_seconds；不指定时沿用原执行器默认配置。
- 工具模板使用 `${account_id}`、`${group_id}` 及 Bot 的 `bindings`。账号和群由会话决定，不能被普通绑定参数覆盖。
- `binding_scope` 标记账号/群专属工具，跨范围继承时列为待适配；`harnesses` 标记已适配执行器。
- `disabled_tools` 仅缩小该 Bot 的工具清单。更新配置要求 `expected_version`，旧引用保持原版本。

主控 MCP 新增 `configuration_list/get/put`、`bot_inherit`、`session_bind`、`session_effective_configuration`、`session_runs`、`session_export_tools`。不把这些接口注册给群聊角色。

`session_export_tools` 为 Antigravity 创建新的独立导出目录，返回 MCP 配置与权限白名单；已有目录拒绝覆盖。`tool_proxy.py` 在工具发现和调用两个入口执行允许清单。导出不自动替换在线文件；应用后记录 `runtime_refs.applied_configuration`，真实调用结果保留在执行证据中。

### 新机器人配置顺序

1. `bot_inherit`：传入来源 Bot 的版本引用、新账号、接收方绑定参数和自身人格引用。
2. `session_create`：指定 Bot 引用、群、harness、模型和思考强度。
3. `session_effective_configuration`：检查可用工具及待适配项目。
4. `session_export_tools`：导出接收方工具配置，核验后应用到该会话独立工作目录及权限配置。
5. `session_bind`：登记实际配置文件与已应用版本；原生线程及历史保持。

### 现有实例迁移边界

白龙娘登记原 Tulpa 人格预设及 Codex 配置引用，原运行器不变。噗伊共享工具配置档，知识库、B 站和视频 MCP 已导出；Tulpa QQ 操作、群文件和学习收集工具仍需要噗伊自身的事件/连接适配。执行器原生搜索、子代理和生图不由 MCP 工具导出代替。

迁移回执记录独立配置绑定的 before/after；`rollback_binding` 在当前值匹配本轮 after 时恢复 before，不回滚消息数据库或进程。在线文件与接收器回退使用本轮部署证据中的脚本。任何实际工具调用和 QQ 收发验收应单独记录。
