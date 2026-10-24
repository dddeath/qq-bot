# 知识条目与 Tag 协议 v1

## 入口与存储

`src/runtime/knowledge_entries_mcp.py` 提供独立的维护与读取入口。宿主通过
`QQ_ENTRY_STORE` 指定 JSON 快照文件，通过 `QQ_ENTRY_COLLECTIONS` 指定可访问集合的 JSON 数组。
该入口尚未注册到机器人工具配置；现有 Markdown 知识库及学习 SQLite 不变。
集合名称由宿主配置，群画像使用独立集合。工具参数不接受账号或群绑定变更。

维护入口只交给具备知识修改职责的调用方；不能直接把整组工具开放给普通群聊模型。

## 条目与 Tag

条目公开模型：`id/title/content/tags/sources/created_at/updated_at/revision/status`。
快照内部另外保存集合归属；合并条目保存 `merged_into`。创建和更新时间由系统写入 UTC 时间。
知识的时间条件、适用条件写在正文，不从更新时间推断。

Tag：`id/name/category/aliases/description`，类别为领域、主题、对象、需求。
Tag 注册支持相同内容重复提交；已有 ID 的不同内容返回 `tag_exists`。
本版尚未实现 Tag 定义修改、Tag 合并和旧库自动导入。

## 渐进读取

1. `search_knowledge_tags(query, limit=6)`：匹配名称、别名、描述，返回当前可见有效条目的计数。
2. `find_knowledge_entries(all_tags, any_tags, limit=6, query='')`：满足全部 all_tags，且 any_tags 非空时至少命中一个；返回标题、80 字符摘要、Tag 和修订号。query 可用于标题／正文的字面补查。
3. `read_knowledge_entry(entry_id, revision, offset=0, limit=1200)`：按字符读取，单次最多 2400 字符；用 next_offset 继续。修订已改变时返回 revision_conflict。
4. `read_knowledge_revision(entry_id, revision)`：维护时按需读取历史正文、来源及修改原因。普通正文读取不附带审核信息。

候选最多返回 20 项。Tag 检索为字面匹配，尚未验证真实模型选择标签的质量。

## 维护结果

- 新增：已有 Tag ID 与来源定位符 → 稳定条目 ID、revision=1。
- 修改：条目 ID、base_revision、changes、add_sources、reason → 新修订号。changes 仅接受 title/content/tags/sources；列表替换，add_sources 去重追加。
- 合并：两条 ID 和双方修订号 → 目标合并来源、Tag；原条目变为 merged。正文沿用目标条目，调用方先读取两条并修订目标正文。仅允许同集合合并。
- 撤回：条目 ID、修订号、原因 → withdrawn，退出普通检索，历史仍可按需读取。

写入以整个快照为原子单位。排他锁冲突返回 store_busy；修订不符返回 revision_conflict，调用方应先重新读取。
工具的领域错误以 `{"error":"错误码"}` 返回；正常结果不含 error 字段。
来源为定位符，本入口不自动联网验证来源内容。

## 接线边界

当前端到端链路在隔离快照中实际调用 MCP。已提供正式库与已发布学习的导入、增量候选、显式发布及可选只读入口。机器人白名单接线、维护调度、模型自主维护与线上部署仍需后续完成。
