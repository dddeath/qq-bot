# QQ 自主资料与戳一戳

在已有持续群聊与图库基础上提供六种操作：头像、账号昵称、个性签名、当前群内自己的群名片、自定义在线状态、戳当前群成员。另有 `get_self_qq_capabilities` 和 `get_self_qq_profile` 供模型主动查询能力和当前资料。

## 部署

`mcp_self_qq.py` 安装到 Tulpa 的 `chatlocal/`。`patches/self-qq.patch` 包含该模块及 MCP 注册、OneBot 接口名单、戳一戳接收改动。该补丁基于已安装社区图库的服务器版本。

服务器 `source/data/mcp-self-qq.json` 中 `enabled`、`grant_ids`、`conversation_ids` 指定自主操作连接与群。该配置不提供给模型修改。当前仅开放测试小号及测试群。资料操作不接受其他账号目标，群名片目标由会话确定。

Codex 的 `mcp_servers.tulpa.enabled_tools` 需要加入上述两个查询工具和 `set_self_qq_avatar`、`set_self_qq_nickname`、`set_self_qq_signature`、`set_self_qq_group_card`、`set_self_qq_status`、`poke_chat_member`。

头像接受本会话已看过的 `sticker_id`，继续使用现有图片读取与图库。在线状态需要 QQ 图标编号；资料读取会返回实际存在的状态字段，缺失字段保留 null。戳一戳使用已交付群事件的 `event_id` 确定对象。收到戳向自己的通知时进入现有群消息等待通道；他人互戳、自己的通知回声及其他群的通知不触发该聊天。

## 回执与验证

写操作在 `self_qq_operations` 留存操作前资料与回执。同次操作重复调用返回原回执；结果 UNKNOWN 时不自动重试。SUCCEEDED 表示获得上游成功回执，客户端显示效果仍由实际观察确认。

`tests/test_self_qq.py` 和 `tests/test_poke_ingress.py` 覆盖资料目标、头像读取前置、戳一戳对象、工具发现和参数、幂等回执、未知结果以及事件接收、规划后纯文本回复和拒绝引用戳通知。`verify-self-qq.py` 保存基线/修改后命令、输出、退出状态、补丁和归档，每次使用独立时间戳目录。

部署证据：`/home/ubuntu/tulpa-test/evidence/self-qq-live-20261011T184535.886989Z/`。

当前实际验证：模型已调用能力查询和资料读取；自身群名片已成功改为“GPT 白龙娘”并回读一致。账号昵称更新返回原生 `result=55`、`errMsg=UpdateUdcFail`，回读仍为 QA；该错误的 QQ 侧原因未确认。真实戳通知已交付模型；发送校验已修复并通过离线接收—规划—发送回归，群内回复待再次验收。其余资料写入尚待实际使用验证。

## 回退

`rollback-self-qq.py --deployment <上述部署目录>` 只检查；加 `--apply` 恢复部署前代码、人设、工具白名单与自主权限配置，重启 Tulpa，并暂停 Codex 聊天。已发生的 QQ 资料变更不会随代码回退自动撤销；原资料与操作回执保留在 `self_qq_operations`，按需恢复。头像原件未由资料读取接口提供时，恢复头像需要原图。

### 戳事件回应校验

戳通知没有 QQ 消息编号。`MCPChat.response_target` 按已读取的本会话缓存、通知类型、自身目标和内部事件键验证该通知，使其可作为普通文本的回应目标；原生引用仍要求有效 QQ 消息编号。

`patches/poke-response.patch` 是从六项工具首次部署版本到该修复的增量补丁。回退此修复时先停止当前聊天，在服务器 Tulpa 源码目录对该补丁运行 `git apply --reverse --check`，通过后运行 `git apply --reverse` 并重启 Tulpa。原六项部署回退脚本校验的是首次部署版本，需要先撤销此增量补丁再使用。

## 人设与工具规则

`personas/gpt_white_dragon_user.v2.md` 维护身份、性格和表达；同目录无版本后缀文件保留为部署兼容副本。`qq_tools.md` 独立维护账号授权、直接回应、头像选择和工具收发规则。

服务器人设位于 `/home/ubuntu/tulpa-test/source/chatlocal/prompts/mcp_chat/gpt_white_dragon_user.md`，工具规则位于 `/home/ubuntu/tulpa-test/runtime/qq_tools.md`。启动时将工具规则作为 Codex 指令，人设由 Tulpa 预设完整返回，不把运行流程写入人设。

直接 @、引用自己和戳自己不走随机插话抽样；自然语言指向由模型结合上下文判断。当前 Tulpa 运行路径没有新增概率抽样器。头像按实际看图后的审美选择，背景、文字和其他角色不自动排除；两张已标注券图仍不作头像。

本次部署前的人设、工具模块与运行入口保存在 `/home/ubuntu/tulpa-test/evidence/persona-tools-20261011T203203.639010Z/`。回退时停止当前聊天和 Tulpa，恢复 `persona.before` 到人设路径、`module.before` 到 `source/chatlocal/mcp_self_qq.py`，再使用前一运行的 `prompt.txt` 启动。旧证据与已发生的 QQ 资料修改不撤销。
