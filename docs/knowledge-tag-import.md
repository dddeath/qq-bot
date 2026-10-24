# 知识快照导入与 Tag 质量

## 输入与输出

入口为 `src/runtime/knowledge_tag_import.py`，接收 KnowledgeCatalog 审计导出的条目数组、Tag 策略，以及可选的逐条审阅标注。

```text
python src/runtime/knowledge_tag_import.py 
  --entries /absolute/path/entries.json
  --policy /absolute/path/knowledge-tag-policy.json
  --annotations /absolute/path/annotations.json
  --output /absolute/path/new-candidate-directory
```

输出目录必须不存在。生成隔离 `snapshot.json`、`mappings.json`、`quality.json` 和输入副本。
未写回现有 Markdown 或学习数据库，也未接入机器人配置。

## 分类依据

- Tag 定义来自受控词表；别名复用同一个 ID。同类别的名称或别名规范化后发生冲突时中止导入。
- 领域可依据原文档所属领域以及学习正文明确的作品语境。
- 对象优先依据标题，不因为正文顺带提到来源作者而给作者贴对象标签。
- 学习表达依据 situation 中的交流用途。已审阅的逐条标注带正文 SHA-256；正文变化后需重新审阅。
- 规则只在声明的字段匹配，保存命中的字段、文本和规则；审阅标注保存依据和正文哈希。
- 无匹配时保留空 tags 并列入待核验。未关联条目的预设标签不写入快照。

## 保留与范围

每个原条目保留标题、完整正文及条件。导入不自动修正事实、合并知识条目或撤回矛盾条目。
新 ID 与原 ID、原版本及原更新时间通过 mappings.json 对应。created_at/updated_at 记录候选条目的建立时间，不冒充原知识日期。
来源引用定位到审计快照中的原条目，原始网络证据仍需按原系统记录追溯。

正式知识、指定账号／群的已发布学习、群画像分别保存集合归属。检索宿主只授予所需集合。
群画像及其审阅映射不进入公开 Tag 策略文件。

## 质量报告

报告包含各类 Tag 数量、关联条目数、无 Tag 条目、单条目 Tag、覆盖超过全库 25% 的 Tag，以及超过 8 个 Tag 的条目。
这些阈值只生成审阅信号，不自动删改。专有对象即使只出现一次仍可能有检索价值。
数量检查不能证明语义正确；验收还需查看代表性 Tag 查询、候选和正文。

当前流程使用确定性规则与审阅标注；不自动请求模型或联网。新材料的增量候选与显式发布见 knowledge-tag-publishing.md；维护调度、生产配置及模型自主选 Tag 仍待接线。
