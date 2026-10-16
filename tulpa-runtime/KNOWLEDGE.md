# 本地知识读取

`local_knowledge.py` 通过只读 stdio MCP 提供 `search_local_knowledge` 和 `read_local_knowledge`。复用服务器已有的 Tulpa Python 环境，不新增网络监听端口。`QQ_KNOWLEDGE_ROOT` 指向按 Git 提交固定的知识版本目录。

可读范围为总索引、固定 UP 正文、四个游戏领域、AI 拟人二创领域以及当前账号当前群的成员画像。配置与凭据、运行文件、学习数据库和审核材料分别保存，知识工具只读取知识库文档。

运行规则保存在 `qq_tools.md`：启动通过 `startup_knowledge.render` 附总索引与当前群简短成员映射，详细文档按需展开；当前上下文已有内容直接复用。库内缺失、资料日期之后的更新、当天信息或记录冲突才联网。学习结果通过 `read_group_learning` 单独按需读取。

## 服务器配置

专用 Codex home 的 `config.toml` 增加：

```toml
model_context_window = 1000000
model_auto_compact_token_limit = 900000

[mcp_servers.local_knowledge]
command = "/home/ubuntu/tulpa-test/venv/bin/python"
args = ["/home/ubuntu/tulpa-test/runtime/local_knowledge.py"]
tool_timeout_sec = 30

[mcp_servers.local_knowledge.env]
QQ_KNOWLEDGE_ROOT = "/home/ubuntu/tulpa-test/knowledge-releases/<knowledge_commit>/knowledge"
QQ_KNOWLEDGE_ACCOUNT = "1000000011"
QQ_KNOWLEDGE_GROUP = "2000000001"
```

配置值与运行时窗口分别核验。2026-10-12 本次账号的模型目录返回 `max_context_window=872000`、`effective_context_window_percent=95`；实际调用日志报告 `model_context_window=828400`。已写入的 1M 请求仍受到当前 CLI 模型目录上限约束。

## 部署与恢复

知识按提交归档上传，解包到独立版本目录；配置和规则修改前保存到独立部署证据目录。重启宿主时沿用原 Codex 线程，重新加载现有人设、创建当前群聊天会话，核验接收器连接及学习状态。

`rollback-knowledge.py <deployment>` 检查当前配置与本轮部署副本一致；加 `--apply` 停止聊天后恢复原配置和规则，聊天保持暂停。知识版本、学习数据、人设和历史证据保留。重新启用聊天由主控执行。
