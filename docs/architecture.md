# 架构与消息链路

## 对象

Bot 保存账号、人格和配置引用；LearningJob 保存学习来源与调度配置。两者关联各自用途的 Session；Session 保存稳定标识、harness 和原生线程，Run 记录每次执行。ToolProfile 可由多个机器人继承，接收方绑定自身账号和群。

## 群聊

```text
QQ / OneBot
  → Tulpa 接收、授权与消息缓存
  → 宿主等待、消息激活与批量收集
  → Luna 判断是否唤醒（理由留在追踪记录）
  → 指导按固定字段和场景变化去重
  → 主聊天接收原始消息与图片
  → 结合原生上下文、角色、知识库决定回应
  → 规划与发送前检查
  → QQ 发送及回执
```

后台话题关联只辅助发送前的新鲜度判断，45 秒宽限及记录数量、年龄和字数上限由配置决定。主聊天保留发言对象、交流意图及回复选择；关联缓存最多 5 个话题，默认 10 分钟无更新回收。

## 异步任务

主聊天派出搜索、视频阅读或生图任务后继续接收消息。后台结果带回原问题和来源，主聊天检查当前语境，再向原请求者发送。工具轨迹记录目的、真实调用结果和耗时。

## 源码边界

`src/sessions` 负责管理与执行器适配；`src/runtime` 提供机器人能力。Tulpa、QQ 接入、模型 CLI 及其登录态独立安装。角色、提示词、配置、知识及图片资源位于源码目录之外。


## 发布登记

部署入口通过私有管理工具 `session_publish_runtime(session_id, release, run_path, tool_snapshot?)` 登记已观察到的发布。该接口不启动、停止或验证进程。发布前须确认实际进程和原生线程，登记后读取 `session_get` 核对。

`runtime_refs` 统一保存在 `session_configuration`；发布登记将旧基础记录中的该字段迁入此处。`run_path` 保存在会话基础记录，两者在同一事务中更新。省略的其他绑定保持。部署脚本不再直接更新 `sessions.body.runtime_refs`。

接口返回变更前后回执，`session_rollback_publication` 仅在记录仍与回执一致时恢复登记，不修改聊天进程、消息或原生上下文。

## Session 与 Run

Session 表示持续的上下文及绑定；Run 表示一次执行。`session_runs` 返回共同字段：`schema_version`、`run_id`、`session_id`、`purpose`、`harness`、`native_session_id`、`status`、`started_at`、`finished_at`、`elapsed_seconds`、`result`、`error`、`evidence`、`configuration`。

状态为 `running / succeeded / failed / cancelled / unknown`。缺失时间、原生标识及结果保持空值。进程消失且没有结束回执时读取为 unknown。原生子代理的完成事件与中止事件分别映射为 succeeded、cancelled；状态是执行状态，不代表回答质量已通过验收。

- 普通聊天与研究请求沿用去重后的请求记录，返回 `run_receipt`；原有 `session_send.status` 保持兼容，统一状态从回执及 `session_runs` 读取。
- 常驻聊天运行目录保存 `run-receipt.json`；生命周期由运行器入口记录。强制杀进程可能没有结束回执，管理读取不推断成功。
- 每日学习回执覆盖整批运行与发布验证，模型进程退出码为零不单独代表学习发布成功。
- 视频阅读保存相同回执和材料报告；读取预算停止原因保留在 result。
- 原生子代理的已观察启动、完成及中止事件写入 `background-runs.jsonl`，按 run_id 合并为当前状态，并关联父原生线程。未登记的子代理 Session 标识保留空值，通过 parent_session_id 关联管理会话。回执不注入扮演会话。

旧记录通过读取适配返回相同字段，不重写旧证据。已有学习目录和普通请求历史仍可读取；常驻聊天登记只指向当前运行目录，历史发布目录的自动发现尚未加入。

## 已加载配置

新常驻运行回执记录发布目录、模型与思考强度、等待模式、上下文配置、人格文件 SHA-256，以及工具快照路径、SHA-256、Bot 与 ToolProfile 引用。只记录加载信息，不保存工具快照中的凭据。学习回执记录模型、思考强度、服务档位及发布目录；旧记录或原生子代理没有提供的配置不补猜。

## 提示词交付

启动时将人格卡、工具快照中的核心规则和已开启能力摘要、Bot.qq_context、宿主等待说明作为原生线程指导。操作细则按能力组读取。逐批交付保留原始消息、图片和动态状态，固定指导不变则省略；场景 reminders 按增删更新，examples 变化时单独替换。首次、版本变化及压缩后刷新指导；成功完成轮次后才提交已交付状态。

宿主模式由 `src/sessions/host_wait.py` 按工具名、next_call.tool、计划状态和事件字段输出 control v1，不匹配中文句子。messages、context、persona、examples、图片及发送回执原样保留。宿主专用操作说明位于 `prompts/qq-tools/host/`，随发布版本固定。Tulpa packet v1 的动态交付提醒采用“三条基础提醒后一个条件提醒”的现有结构；该布局仍是适配边界，升级上游时须回归核验。
