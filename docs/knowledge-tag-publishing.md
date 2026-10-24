# Tag 知识增量候选与发布

## 数据链路

原 Markdown 与已发布学习库 → KnowledgeCatalog.export_snapshot → 增量候选 → 主控检阅 → 单文件发布 → 机器人只读入口。

`export_snapshot` 与原知识读取共用范围及字段规则，仅导出当前群可读画像和学习 published 内容，未发布材料、审核字段不进入正文。
所有命令均由宿主执行，未开放到群聊工具，也未接入学习调度。

## 生成候选

命令入口：`python src/runtime/knowledge_tag_publish.py prepare`。

必填参数：
- `--base`：当前快照文件。
- `--policy`：已经确认的 Tag 词表及规则。
- `--output`：新的候选目录，必须尚不存在。
- `--entries`：审计条目数组；或者 `--knowledge-root` 直接从现有知识目录读取。

首次增量需要 `--mappings` 指定首次导入的对应表。发布后的快照内含 import_mappings，后续无需另传对应表。
直接读取知识目录时沿用 `--account`、`--group`、`--learning-root`。
已有逐条审阅标注可以通过 `--annotations` 提供；省略时，原文未改变的已审阅标签继续保留，原文已改变则要求重新审阅。

候选目录保存：base.json、snapshot.json、manifest.json、输入副本及 source-status.json。manifest 给出新增、修订、未变、来源缺失和冲突数量，以及候选哈希。

## 增量规则

- 同一原条目沿用新库 ID。正文、标题、Tag 未变化，不增加修订号。
- 原材料更新且新库条目仍与上次导入一致时，生成新修订。
- 本地修订、合并、撤回或范围变化列为冲突，不覆盖。
- 原材料缺失时保留已有知识并标记 source_missing；候选报告交由主控判断，不自动删除。
- 新材料只能复用受控词表；未命中时保留空 Tag。导入过程不自动增加词表或裁决事实矛盾。

## 发布

命令入口：`python src/runtime/knowledge_tag_publish.py publish`。
参数为 `--candidate`、`--target`、`--approved-sha256`。target 是只读 MCP 配置中的快照文件。

发布核验检阅过的候选哈希、基线哈希及目标当前哈希。存在冲突或基线过期时停止。
在与条目维护共用的文件锁内原子替换单个快照，条目与导入对应表同时生效。写入带时间的 publish.json 回执。
相同候选已成功发布且目标未变化时，重复执行返回原回执。

运行中的读取入口每次读取当前文件，不需要为快照内容更新重启 MCP。旧修订读取句柄会收到 revision_conflict，调用方重新查询即可。

## 回退

`python src/runtime/knowledge_tag_publish.py rollback --candidate <candidate-directory>`

仅在目标仍等于本次发布结果时恢复 base.json，写入 rollback.json。发布后若又有更新，回退会停止，避免覆盖后续维护。
文件替换已完成而回执写入失败时，应核对目标与候选哈希后人工恢复回执；不据一次命令失败认定目标未变。

## 接线状态

已具备候选生成、显式发布、读取生效和回退入口。生产工具白名单／提示词切换、学习调度触发及模型自主选 Tag 尚未启用。当前隔离验证不改变上线审批或知识收录规则。
