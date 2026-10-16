# bili-note 可借鉴部分

结论：保留现有视频链路，优先借鉴材料预检、带楼中楼的评论材料和按需补单帧；浏览器字幕作为后备方案。整套安装的增益小于针对性接入。

核验日期：2026-10-15。上游固定版本：`08fe81297ef876a668a7e187409fa2c3366b9faa`。本次为源码静态研究，未运行上游、安装依赖或修改服务器；稳定性和耗时收益尚未实测。

## 优先借鉴

### 1. 在下载画面前判断材料缺口

上游 `visual_preflight` 统计所选分 P 时长、字幕字数、字/分钟和字幕覆盖分 P 数。长视频字幕稀疏时提示增加视觉材料。例如 ≥30 分钟且字幕不足 120 字/分钟判高风险。它不下载视频。[预检实现](https://github.com/Rimagination/bili-note/blob/08fe81297ef876a668a7e187409fa2c3366b9faa/scripts/run_bili_note.py#L250-L317)

本地 `E:\qq-bot\tulpa-runtime\daily_video.py` 的 `enrich_videos` 对预算内视频依次读取文字和画面，没有这一预检。可将字幕覆盖和用户问题结合，用于决定是否补材料，而非仅凭字幕字数跳过画面：上游阈值偏长课程，十分钟以下无字幕视频的 risk 仍可能为 low，status 为 partial；游戏精彩片段也可能对白密集而画面更重要。先加覆盖报告比立即改读取策略更稳妥。

### 2. 保存评论承接关系，帮助理解梗与反讽

上游实际抓取主评论和子回复，保留 `rpid/root/parent`、作者、时间、点赞、UP 点赞/回复标志及图片链接；归档为逐条 JSONL，可回看一句评论所回应的对象。[评论采集](https://github.com/Rimagination/bili-note/blob/08fe81297ef876a668a7e187409fa2c3366b9faa/scripts/extract_bilibili.py#L684-L853)、[层级归档](https://github.com/Rimagination/bili-note/blob/08fe81297ef876a668a7e187409fa2c3366b9faa/scripts/archive_bili_materials.py#L433-L525)

本地 `E:\qq-bot\tulpa-runtime\bilibili\video-context.mjs` 的 `collectVideoContext` 固定 `include_replies:false`，因此现有聚合材料缺少楼中楼。建议按预算读取少量讨论串，保留原话及父子关系；社区纠错、强度梗和接梗较可能受益，此收益仍需样本验证。

上游“筛选有价值评论”是交给模型的技能规则，代码并没有语义分类器。主评论最多 40 页，子回复没有独立的总条数预算，不适合直接搬到低延迟群聊。技能默认过滤技术无关闲聊，也不宜照搬到以社区梗为目标的学习。[评论写作规则](https://github.com/Rimagination/bili-note/blob/08fe81297ef876a668a7e187409fa2c3366b9faa/SKILL.md#L207-L223)

### 3. 拼图初看后，仅补读有信息的单帧

上游最多 12 帧、4×3 拼图；清单保存 BV、P、CID、时间戳、拼图格坐标及单帧路径。技能要求先看拼图，看不清文字或图表时再打开对应单帧。[抽帧与清单](https://github.com/Rimagination/bili-note/blob/08fe81297ef876a668a7e187409fa2c3366b9faa/scripts/extract_video_keyframes.py#L210-L434)

采样实际是时间均匀点加分 P 中点，没有自动识别精彩场面。值得借鉴的是两阶段读取，而非抽帧算法。本地 `E:\qq-bot\tulpa-runtime\video\learning-frames.mjs` 仅将有界拼图传入每日学习；已有聊天视频工具具备 `get_frame_at`。每日学习若加入按需单帧，需要先增设有界补读阶段，不能只修改一次性无工具学习提示词。

## 已有重合及可小幅补齐

- **原材料与最终内容分离：** 上游按字幕时间段、评论 ID 建索引。本地已分离审核记录与发布释义；可补更细片段索引，但无需重建文件体系，也无需将引用编号带入角色聊天。[归档实现](https://github.com/Rimagination/bili-note/blob/08fe81297ef876a668a7e187409fa2c3366b9faa/scripts/archive_bili_materials.py#L207-L278)
- **控制输入预算：** 上游按材料量、时长及互动信号设定笔记字数。本地已有每批视频数、拼图数、评论和弹幕上限。可参考按信息量分配预算；不引入课程笔记的固定章节、自测题及按热度扩写。[预算实现](https://github.com/Rimagination/bili-note/blob/08fe81297ef876a668a7e187409fa2c3366b9faa/scripts/archive_bili_materials.py#L903-L1019)
- **字幕备用路径：** 自动入口在公开字幕缺失时可调用已登录浏览器的字幕接口；无浏览器则记录跳过。ASR 有独立脚本及技能步骤，但 `run_bili_note.py` 没有自动串起完整 ASR 回退。我们可保留浏览器方案应对特定失败，不据此声称能解决当前服务器的风控。[入口判断](https://github.com/Rimagination/bili-note/blob/08fe81297ef876a668a7e187409fa2c3366b9faa/scripts/run_bili_note.py#L659-L701)、[浏览器读取](https://github.com/Rimagination/bili-note/blob/08fe81297ef876a668a7e187409fa2c3366b9faa/scripts/fetch_browser_ai_subtitles.py#L100-L170)

## 建议顺序

1. 材料覆盖报告和少量楼中楼：改动集中，直接对准目前知识学习的遗漏。
2. 在现有拼图工具上增加按需单帧：用游戏 UI、数值、战况样本核验收益和耗时。
3. 浏览器字幕兜底：仅在现有路径确实失败的样本上比较，确认服务器运行方式后再决定是否引入。

当前没有待安装或待部署项。实施范围仍待用户选择。
