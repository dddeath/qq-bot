# QQ 工具对象

## 配置归属

`ToolProfile.body.qq_tools` 保存 `core` 和 `capabilities`。能力组包含 `summary`、`tools`（按服务名列出工具）、`enabled`、`parameters`、`guide` 与可选的 `sections`。说明正文属于该配置版本。

`Bot.body.qq_tools.<能力组>` 可覆盖 `enabled` 与已声明的 `parameters`；参数以 `${qq_能力组_参数名}` 展开到服务定义的 args/env 等字段。只有实际工具读取的参数才影响执行；已有群文件大小和真实发起者校验继续由群文件服务执行。

`Bot.body.qq_context` 是简短的机器人专属聊天偏好。`qq_guide_notes.<能力组>.guide` 与 `.sections.<章节>` 给对应操作说明追加素材用途等专属资料。内容可引用 Bot bindings，如 `${owner_id}`。这些专属信息不随 `bot_inherit` 复制。

有效工具先经过账号／群作用域、Harness 兼容性与 `disabled_tools` 过滤，再应用能力开关。没有任何可用工具的能力不出现在摘要和说明读取入口中。原有非 QQ 工具保持原清单。

## 文档来源与编译

```text
config/qq-capabilities.json       能力与已有工具名称的对应表
prompts/qq-tools.md               常驻判断、信息缺口与基础收发规则
prompts/qq-tools/
  chat.md                        消息收发
  session.md                     初始化及异常恢复
  research.md                    知识、检索及学习读取
  media.md                       图片、图库与表情
  image-generation.md            明确生图请求及结果发送
  profile.md                     账号资料修改
  interaction.md                 戳一戳
  group-files.md                 群文件操作
```

`src/sessions/qq_tool_profile.py --profile <原ToolProfile正文JSON> --output <新正文JSON>` 根据已有工具清单编译能力与文档，保留原服务定义，输出文件必须不存在。编译不会写数据库或改变运行状态。已有能力参数和开关保留；新增工具名称需同时更新对应能力映射。

读取现有 Bot、ToolProfile 和 Session 后保存原始版本引用。用 `configuration_put` 登记新 ToolProfile 版本，再更新 Bot 引用。按实例现有值归位主控偏好、称呼与素材说明；`config/examples/white-dragon-qq-notes.json` 仅为公共占位示例，不替换线上资料。使用 `session_bind` 时保留原 `runtime_refs`。

## 导出与加载

`session_export_tools` 为 Codex 和 Antigravity 导出 `tool-profile.json`、`mcp_config.json`、权限 `allow` 条目及 `qq-startup.md`。目录必须为新目录。快照可能含工具连接配置，按私有运行文件管理。

Codex 当前聊天运行器通过 `--tool-snapshot <绝对路径>` 加载，也可在 policy 中指定 `tool_snapshot`。`--context-control` 核对快照账号和群，继续宿主等待；不与旧 `--event-wait` 入口组合使用。运行器关闭旧 MCP 配置入口，再以 `qq-managed-*` 命名空间注册快照中允许的服务与只读说明工具，避免绕过能力开关。

统一 Harness 通过 `runtime_refs.tool_snapshot` 加载。Codex 自动生成 MCP 覆盖；Antigravity 要求工作目录 `.agents/mcp_config.json` 与导出文件一致，权限配置沿用导出的 `allow` 条目。尚未配置的实例不自动切换。

迁移时 `prompt.txt` 或 Harness 输入保留人格与会话续接内容，不再拼接旧的完整 `qq-tools.md`。运行器追加常驻规则、当前绑定、已启用能力摘要及 Bot 简短偏好；只读说明工具从快照返回详细文档。子代理需要 QQ 操作时沿用同一快照的读取入口；不需要 QQ 工具的检索子代理仍按原技能运行。

## 按需读取

`read_qq_tool_guide(capability="media")` 读取图片操作说明；`read_qq_tool_guide(capability="media", section="image-generation")` 读取生图细则。工具不接受账号、群、路径或版本参数，始终使用本会话快照。返回实际可用工具、参数、绑定、版本引用与说明摘要哈希；不会返回服务器凭据。

关闭能力时重新导出并加载新版本，工具清单、能力摘要和可读说明同时更新。Bot 开关和参数变更不会隐式热更新已运行会话。

## 回退

恢复旧 Bot／ToolProfile 版本引用及原运行器配置。未迁移实例不受新模块影响；回退保留已产生的群消息、学习结果与聊天历史。
