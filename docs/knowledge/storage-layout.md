# 聊天资料存储

| 类别 | 仓库位置 | 服务器位置 | 用途 |
|---|---|---|---|
| 配置 | `config/` | `/home/ubuntu/tulpa-test/config/` | 每日学习开关、时刻、账号名单与采集上限 |
| 运行程序 | `src/runtime/`、`src/sessions/` | `/home/ubuntu/tulpa-test/runtime/` | MCP、采集程序、启动程序和工具规则 |
| 运行状态与证据 | `.local/` | `/home/ubuntu/tulpa-test/evidence/`、既有 Tulpa `source/data/` | 聊天运行状态、回执和独立验证记录 |
| 学习数据 | 本地仅保存验证副本 | `/home/ubuntu/tulpa-test/learning/groups/<账号>/<群>/` | 学习数据库、原始输入、审核材料与发布结果 |
| 知识库 | `knowledge/` | `/home/ubuntu/tulpa-test/knowledge-releases/<版本>/knowledge/` | 稳定领域知识、固定 UP 与群员画像 |

密钥继续留在既有忽略目录和专用 Codex home，不放进知识库。既有运行证据保持原路径。

## 知识入口

`knowledge/INDEX.md` 是唯一总索引。启动输入只附总索引和 `group-memory/<账号>/<群>/INDEX.md` 的简短成员映射。成员画像位于同分区 `members/<QQ号>.md`，包含身份、称呼、账号对应关系及已有记录。固定 UP 正文位于 `knowledge/creators.md`。

知识已有且适用时直接使用。缺少详细信息时先展开知识正文或按需查询独立学习结果，仍有信息缺口再联网。每日学习成果保留在学习数据库，本轮不合并成知识库 Markdown。

## 更新与部署

账号采集配置与聊天知识各有用途：修改采集频率只更新配置；确认账号身份时同步更新相关画像、成员映射或固定 UP 正文。知识发布为独立版本，切换 `QQ_KNOWLEDGE_ROOT` 并恢复同一聊天线程加载新版本。

每日学习配置为 `config/daily-learning.json`，固定采集配置为 `config/creator-watchlist.json`。运行服务和学习 MCP 均引用前者；学习数据库路径保持不变，当日完成记录保持不变。
