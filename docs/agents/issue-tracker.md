# 本地 Markdown 任务跟踪

本仓库的任务和规格存放于 `.scratch/`。

## 文件约定

- 每个功能使用独立目录：`.scratch/<feature-slug>/`。
- 功能规格：`.scratch/<feature-slug>/spec.md`。
- 实现任务：`.scratch/<feature-slug>/issues/<NN>-<slug>.md`，从 `01` 开始编号，每个任务一个文件。
- 任务分类状态写在文件顶部附近的 `Status:` 行，取值见 `triage-labels.md`。
- 评论和讨论按时间追加到文件底部的 `## Comments` 标题下。

## 发布与读取

技能要求“发布到任务跟踪系统”时，按照上述约定创建对应文件，按需创建目录。

技能要求“读取相关任务”时，读取指定路径的文件。仅提供编号时，在对应功能目录中定位；多个目录存在同号任务且上下文不足时，先确认所属功能。

## Wayfinder 约定

Wayfinder 使用一份探索地图和多个子任务文件：

- 地图：`.scratch/<effort>/map.md`，包含 Notes、Decisions-so-far、Fog。
- 子任务：`.scratch/<effort>/issues/<NN>-<slug>.md`，从 `01` 开始编号，正文记录待解决的问题。
- 类型：`Type:` 取值为 `research`、`prototype`、`grilling` 或 `task`。
- 执行状态：未领取的开放任务使用 `Status: open`，领取后为 `claimed`，完成后为 `resolved`。这些状态用于 Wayfinder 子任务；普通任务使用分类标签。
- 阻塞关系：在文件顶部附近使用 `Blocked by: NN, NN`；列出的任务全部为 `resolved` 后解除阻塞。
- 选择任务：扫描对应 issues 目录，选择编号最小、开放、未阻塞且未领取的任务。
- 领取任务：开始工作前先写入 `Status: claimed`。
- 完成任务：在 `## Answer` 下追加答案，设置 `Status: resolved`，并在地图的 Decisions-so-far 中追加结论摘要和任务链接。
