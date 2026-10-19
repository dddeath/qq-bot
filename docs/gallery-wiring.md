# Tulpa 图库接线

在已应用 `community-media.patch` 的 Tulpa `source` 目录执行：

```sh
git apply --check /absolute/release/patches/bot-gallery.patch
git apply /absolute/release/patches/bot-gallery.patch
```

`generated-gallery.patch`、`sticker-pipeline.patch` 沿用现有安装流程；Bot 接线只替换配置解析，不改素材读取、生成图枚举或发送授权。已安装机器人级接线的实例先检查反向补丁或现有方法，避免重复应用。

Tulpa 进程的 `PYTHONPATH` 必须包含 `/absolute/release/src/runtime`，以导入 `bot_gallery`。在原 `mcp-community.json` 中使用 `config/examples/mcp-community.json` 的 `bot_gallery` 引用，账号和素材配置来自数据库的最新 Bot 版本。旧 `conversation_ids` 配置仍由解析器兼容。

同账号不同群共用 Bot 图库；不同账号不返回该图库。图库变更每次读取最新 Bot，而 ToolProfile 与 Session 仍采用固定版本引用。素材文件与 Bot.gallery 目录项需要同时存在。

首次部署代码需重载 Tulpa 服务；之后 Bot 图库条目的更新由读取时生效。群聊发送仍经过既有授权，不由图库配置授予权限。

回滚接线：

```sh
git apply --reverse --check /absolute/release/patches/bot-gallery.patch
git apply --reverse /absolute/release/patches/bot-gallery.patch
```

同时恢复部署前 `mcp-community.json`，再重载服务。仅恢复旧代码而保留新式配置会失去图库入口。
