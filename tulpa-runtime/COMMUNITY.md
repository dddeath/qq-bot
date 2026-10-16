# 社区图库

`patches/community-media.patch` 为 Tulpa 的 `list_chat_stickers` 增加 `source="community"`。目录由服务器 `source/data/mcp-community.json` 配置，只对其中的 `conversation_ids` 开放。工具调用仅使用不透明的 `sticker_id`，不接受模型提供的本地路径。

列出目录后先调用 `read_chat_sticker` 查看像素，再按语境选择发送；`note_chat_sticker` 保存含义和标签后，图片进入原有 `source="library"` 检索与候选机制。读取过的社区原件会留存在原有本地图库中，不修改 QQ 收藏。群消息图片仍使用 `read_chat_image`。

Codex 的 `mcp_servers.tulpa.enabled_tools` 需包含 `list_chat_stickers`、`read_chat_sticker`、`note_chat_sticker`、`send_chat_sticker`，并保留 `read_chat_image` 与原有聊天工具。修改工具白名单后重新启动 Codex 聊天进程。服务端提供工具并不表示宿主白名单已开放。

图库目录通过 `source/data/mcp-community.json` 指向服务器的独立版本目录。2026-10-13 目录元数据保存于 `tulpa-runtime/assets/gallery-catalog-20261013.json`：原有 41 项逐图细化标签，追加用户 QQ 收藏目录中的 324 张原图，共 365 项。150 张缩略图均有对应原图，不重复导入；未完成的 `.tmp` 文件跳过，GIF 保留动画。158 张新增素材有具体用途/情绪描述，余下主要为聊天截图，发送前仍需实际看图。

原图保存在本地私有暂存目录与服务器版本目录，不进入 Git。超过既有 6 MiB 限制的 `creeper-1686.png` 保留原件并明确标记不可通过此工具发送。代码生成图片目录保持接入。

QQ 自带收藏目录与 Tulpa 本地素材记录分别核对：本轮快照 QQ 收藏 11 项，Tulpa 本地素材 72 项；`sticker_collections` 和收藏操作记录为空，因此没有已确认的机器人主动收藏成功证据。此快照不代表后续固定数量。

`tests/test_community_media.py` 在离线临时数据库中验证图库调用、原有群图片读取、群范围、超限提示和工具参数。`verify-community.py` 对服务器保留的 `community-baseline` 与 `community-stage` 运行测试，每轮生成独立时间戳证据目录。

本次部署备份位于 `/home/ubuntu/tulpa-test/evidence/community-live-20261011T180949.323961Z/`。回退时先停止当前聊天与 Tulpa 进程，用 `media-before.py` 恢复 `source/chatlocal/mcp_chat_media.py`，用 `persona-before.md` 恢复人设，按 `config-before.json` 恢复或移除本轮目录配置；重启 Tulpa 后再开启聊天加载旧快照。保留上传原件与历次证据。

当前验证已覆盖真实 MCP 列表和图片像素读取。真实 QQ 收图与按语境选图仍需群内验收。戳一戳不在本次实现范围。
