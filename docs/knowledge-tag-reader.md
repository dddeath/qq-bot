# 机器人 Tag 知识只读入口

## 选择入口

现有启动文件仍为 `src/runtime/knowledge_catalog_mcp.py`。

- 未配置 `QQ_KNOWLEDGE_ENTRY_STORE`：继续读取现有 Markdown、学习库与当前群画像，工具不变。
- 配置 `QQ_KNOWLEDGE_ENTRY_STORE=/absolute/path/snapshot.json`：读取已发布条目快照，开放 Tag 只读工具。指定文件缺失时启动报错，不切回旧库掩盖配置错误。

沿用 `QQ_KNOWLEDGE_ACCOUNT` 与 `QQ_KNOWLEDGE_GROUP` 绑定。可见集合由启动入口生成：formal、该账号／群的 learning 与 profile。绑定不完整时只读 formal。普通调用参数没有更换账号、群或集合的入口。

## 工具列表

| 工具 | 返回 |
|---|---|
| get_knowledge_tag_index | 当前范围内条目数、Tag 数、分类数量和未标注条目数 |
| search_knowledge_tags | 与信息／表达需求对应的 Tag 候选 |
| find_knowledge_entries | 按 Tag 组合筛选的知识摘要，也可用 query 字面补查 |
| read_knowledge_entry | 指定修订的有界正文及续读位置 |

不注册条目修改、Tag 注册、合并、撤回及审核历史工具；直接调用这些名称也会失败。
维护入口 `knowledge_entries_mcp.py` 保持独立。

## 发布前接线

切换时需要同步配置工具白名单、检索执行器可调用名称及其启动资料。新入口以 Tag 取代旧 usage/domain 参数；不将两套工具同时拼进一个会话。
机器人启动资料、工具白名单、知识读取预算及检索子代理共用 `knowledge_tools.py` 的入口识别和检索指导。`begin_reading_task` 根据实际工具配置生成 reading-v5 协议。运行实例切换仍需发布并绑定新配置版本。

导入快照不会自动跟随原 Markdown／学习库更新。`knowledge_tag_publish.py` 已提供增量候选和显式发布入口；生产启用前需将其接入维护调度，或明确采用人工检阅后发布。见 knowledge-tag-publishing.md。

## 配置版本迁移

调用 `knowledge_migration.migrate_snapshot(snapshot, learning_root=..., entry_store=...)` 生成 Tag 配置副本；`migrate_profile` 将同样的变更写成工具配置的新版本，不自动更换 Bot 绑定。入口保留账号、群及其他工具配置，知识工具列表与 `QQ_KNOWLEDGE_ENTRY_STORE` 同时切换。重复迁移保持相同内容。

机器人常驻输入只增加当前范围的数量与简短检索指导；标签候选和正文由工具按需返回。检索子代理沿用这份配置，任务协议由实际 MCP 入参生成，逐次读取仍记录目的、结果、预算及停止原因。旧配置继续使用旧知识工具的对应指导。

上线时先发布经过检阅的条目快照，再生成并绑定新工具配置版本、重载会话工具。回退时恢复原配置版本及原快照绑定。配置切换不修改人设、原生线程或聊天历史。
