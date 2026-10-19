# 机器人配置

## 配置对象与文件

工具定义保存在统一管理数据库的 ToolProfile，Bot 引用固定版本的 ToolProfile，Session 引用固定版本的 Bot。文件中的人格、知识和图库由运行实例引用。`config/` 中的公共参数不包含全部实例配置。

## 工具白名单

1. `configuration_get` 读取目标 Bot、ToolProfile 和 Session 的当前引用。
2. 更新 `ToolProfile.body.servers.<服务名>.tools`。新增服务还需配置 `command/args/env` 或 `url`、`harnesses` 及必要的 `binding_scope`。
3. `configuration_put` 携带当前 `expected_version` 写入新版本；保留未修改字段。
4. 更新 Bot 的 `tool_profile` 版本，再用 `session_bind` 更新目标 Session 的 `bot_ref`。传回原有 `runtime_refs`，避免覆盖运行引用。
5. `session_effective_configuration` 检查最终工具清单及 `unavailable`。
6. 使用 `session_export_tools` 向新目录导出固定版本工具快照、`mcp_config.json` 与 `allow` 条目。Codex 运行器用 `--tool-snapshot`，统一 Harness 用 `runtime_refs.tool_snapshot` 读取快照。Antigravity 还需将导出的 MCP 配置应用到该会话工作目录的 `.agents/mcp_config.json`，并将 `allow` 条目应用到其权限配置。
7. 重载对应宿主，恢复原线程，核对工具发现与实际调用。

只对某个机器人禁用工具时，修改其 `disabled_tools.<服务名>`。`prompts/qq-tools.md` 描述工具使用规则，权限由工具配置控制。

QQ 能力组、渐进披露文档及兼容迁移见 [QQ 工具对象](qq-tool-object.md)。

版本对象修改不自动热更新模型宿主。回退时重新绑定旧版本并恢复旧宿主配置，保留新产生的聊天与发送记录。

## 知识库

正文、群画像范围、索引与进程缓存的更新方法见 [知识存储与发布](knowledge/storage-layout.md)。

## 图库

素材目录、生成图目录和素材条目属于 Bot 的 `gallery`。使用该机器人现有目录作为基准，新增图片后填写对应文件、描述与标签。公共 `assets/` 文件需要发布到实际素材目录才可供实例使用。

`src/runtime/bot_gallery.py` 提供按账号查找最新 Bot 图库的解析入口。Tulpa 侧接线必须将 `mcp-community.json` 中的 `bot_gallery.database`、`bot_gallery.bot_id` 交给该解析入口；发送权限仍由当前群授权检查。公开接线补丁为 `patches/bot-gallery.patch`，安装方法见 [Tulpa 图库接线](gallery-wiring.md)。

## 示例与私有数据

`config/examples/` 只保存占位路径与结构，不包含真实账号、群、凭据或画像正文。应用示例前替换实例路径，读取当前对象并保留未修改字段。现有会话的模型、原生线程、账号、群与运行引用保持不变。

## 群消息激活参数

`Bot.body.activation` 保存消息权重、激活阈值、活跃超时、缓冲过期时间和立即激活条件。配置与接线见 [群消息激活](message-activation.md)。
