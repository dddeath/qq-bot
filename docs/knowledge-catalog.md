# 知识候选与片段读取

`src/runtime/knowledge_catalog_mcp.py` 提供独立的只读 MCP 服务。运行器已能识别启用该入口的工具快照；线上工具配置尚未切换。

## 数据来源

- 正式知识：`QQ_KNOWLEDGE_ROOT` 下现有领域 Markdown。
- 群画像：同一根目录下 `group-memory/<account>/<group>/`，范围取自宿主环境变量。
- 已发布学习：`QQ_KNOWLEDGE_LEARNING_ROOT/groups/<account>/<group>/learning.sqlite3` 的 `published` 表，以只读连接访问。读取字段与学习发布器的角色可见字段一致。

宿主通过 `QQ_KNOWLEDGE_ACCOUNT`、`QQ_KNOWLEDGE_GROUP` 绑定账号和群。工具入参不接受范围覆盖。未配置或缺少学习数据库时返回来源状态，不创建数据库。

## 分类

`knowledge/catalog.json` 显式标记文档用途：`expression` 表达语境、`reference` 事实资料，两者可以并存。当前群画像使用 `profile`。新增文件尚未登记时标为 `unclassified`，仍可检索。

学习 `expressions` 使用表达分类；`meanings.kind=fact` 使用资料分类，`community`、`group` 使用表达与资料分类。分类不代表已完成事实审核。正式文档保留原位置，学习结果不复制进正式知识库。

## 工具

1. `get_knowledge_index()`：来源状态、领域与用途计数，不展开正文。
2. `search_knowledge(query, usage, domain, limit)`：小规模候选及 `read` 句柄。命中章节优先作为读取起点。
3. `read_knowledge(entry_id, version, section, offset)`：正文片段及 `next` 句柄。需要剩余内容时传入 `next`。条目更新后返回 `version_changed`，重新检索获得新版本。

条目版本为内容 SHA-256；学习条目只对角色可见字段计算版本。每次读取刷新来源，不缓存旧发布结果。发布表没有时间字段时返回 `updated: null`。

## 披露预算

通过 `QQ_KNOWLEDGE_DISCLOSURE_POLICY` 的 JSON 对象覆盖下列正整数：

| 字段 | 默认值 | 作用 |
|---|---:|---|
| max_candidates | 6 | 单次候选条数上限 |
| summary_chars | 80 | 每条摘要字符上限 |
| max_fragments | 2 | 单次正文片段上限 |
| read_estimated_tokens | 1200 | 单次正文估算预算 |

正文估算使用每片段 UTF-8 字节数除以 2 后向上取整。回执标明 `estimated_tokens` 和 `fragment_text_only`；不含 JSON 字段开销，也不是实际模型或计费 token。长章节按字符边界分页，返回继续位置，不静默丢弃剩余正文。

## 启动与检索轨迹

工具快照启用 `search_knowledge`、`read_knowledge` 时，`startup_prompt` 从该工具服务的绑定环境读取领域索引和当前群简短映射。默认知识启动区为 800 估算 token，可通过 `QQ_KNOWLEDGE_STARTUP_BUDGET` 配置；不展开领域正文或完整画像。

配置 `reading_trace` 的既有工具代理与学习检索网关均可调用知识工具。`begin_reading_task.needs` 接受 expression、reference、profile 数组，生成 reading-v3 协议。搜索与索引计入原有概览预算，正文片段计入补读预算；仍保留 300 秒默认总时间及 20% 探索上限。

执行器保存实际入参、读取目的、结果和返回投影（含预算回执）；图片投影引用真实保存的像素文件。主会话预算与迁移入口见下节。

## 工具快照迁移与主轮次预算

`knowledge_migration.migrate_snapshot(snapshot, learning_root=...)` 返回新的工具快照副本。它保留会话绑定和其他工具，把旧知识读取入口替换为目录入口，移除独立 `read_group_learning` 读取白名单，保留 `record_completed_search`。学习根目录由宿主显式传入；函数不写配置、不激活快照。无法唯一确定知识服务或同一服务混有其他工具时返回错误，留给配置调用方拆分。

宿主等待运行器每次交付主模型前建立独立的知识披露账目，默认 2500 估算 token，配置字段为 `main_context.knowledge_turn_estimated_tokens`。同轮知识调用共享预算，工具续接不会刷新额度。MCP 返回采用一个语义载荷的 JSON UTF-8 字节数除以 2 向上取整，避免重复计算 text 与 structuredContent；预算回执自身不计入。超过剩余额度时不交付本次资料正文，返回停止原因及剩余额度。该账目保存在运行目录 `knowledge-budget.sqlite3`，不表示实际模型计费 token。

该预算接入宿主等待的 Codex 主会话。独立检索任务继续使用各自的任务预算，其他 harness 尚未接入主轮次账目。

## 配置版本与学习入口

`knowledge_migration.migrate_profile(control_plane, profile_ref, learning_root=...)` 通过现有 ControlPlane 写入新 ToolProfile 版本，保留旧版本和 Bot 的固定引用。相同迁移重复执行返回已有结果；若期间出现不同配置版本，则按既有版本冲突规则停止。生成版本与应用到机器人分别执行。

学习／独立检索配置使用 `tool_snapshot` 指向已展开账号、群和路径的工具快照。执行器从快照选取统一知识服务，保留配置中的工具白名单，校验学习配置的 account、group 与知识绑定一致；网络服务仍沿用原有配置。未配置 tool_snapshot 时保留原先的网络读取流程。

`begin_reading_task` 返回的协议携带 `knowledge_index`。该索引由 MCP 入口根据实际工具配置生成，与主会话启动索引共用 render_servers；目录和简短映射受启动预算限制，正文继续按需读取。独立检索入口可传 needs，供表达、资料、画像需求使用。

主会话 `knowledge-budget.sqlite3` 的 deliveries 保存每次调用的工具、参数、原始返回、实际披露、耗时和预算回执，包括被预算拦截的读取。原始资料仅保留在审计记录中，超限结果不会进入模型。检索任务继续保留自身 task_id、read_id 及读取目的。
