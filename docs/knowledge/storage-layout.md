# 聊天资料存储

| 类别 | 公开仓库 | 运行实例 |
|---|---|---|
| 公共参数 | `config/` | 由实例配置引用的参数文件 |
| 机器人与工具配置 | `config/examples/` 提供结构示例 | 统一管理数据库中的 Bot、ToolProfile、Session 引用，以及模型宿主配置 |
| 程序 | `src/runtime/`、`src/sessions/` | 当前发布版本下的同名目录 |
| 运行状态与证据 | 不公开 | 私有运行目录、Tulpa 数据库与每轮独立证据目录 |
| 学习数据 | 不公开 | 每日学习配置指定的数据库、材料、审核与发布目录 |
| 知识库 | `knowledge/` | `QQ_KNOWLEDGE_ROOT` 指向的独立知识发布目录 |
| 图库 | `assets/` 提供公共素材 | Bot 的图库目录和素材目录项 |

账号、群绑定、凭据、群友画像正文和运行数据保留在私有配置及数据目录。发布代码或公共知识时，不覆盖这些文件。

## 知识入口

`knowledge/INDEX.md` 是总索引。启动资料只附总索引与 `group-memory/<账号>/<群>/INDEX.md` 的简短成员映射。画像正文位于同分区的 `members/<QQ号>.md`；固定创作者资料位于 `knowledge/creators.md`。

现有领域正文位于 `apex-legends`、`arknights`、`mental-omega`、`project-moon`、`ai-personification` 的第一层 Markdown 文件。新增领域需要更新 `src/runtime/local_knowledge.py` 的 `DOMAINS`；群画像按当前账号与群递归读取。

## 发布与生效

1. 修改知识正文、总索引及适用的成员索引。
2. 生成独立知识发布目录，并保留该实例的私有画像正文。
3. 更新知识 MCP 的 `QQ_KNOWLEDGE_ROOT`，保留 `QQ_KNOWLEDGE_ACCOUNT` 与 `QQ_KNOWLEDGE_GROUP`。
4. 重载知识 MCP，刷新启动时缓存的正文。索引变化时重新生成启动资料，并恢复原聊天线程加载。
5. 用 `read_local_knowledge` 和 `search_local_knowledge` 检查新正文及群资料范围。

学习结果继续留在学习数据库，按工具读取。修改采集频率使用每日学习配置；修改创作者身份资料使用知识正文。两类更新分别发布。

具体工具配置流程见 [机器人配置](../bot-configuration.md)。
