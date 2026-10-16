# 阅读目的与每日回放

## 阅读入口

`video_exploration_runtime.read_exploration` 在第一次模型判断前获取基础概览，复用已返回材料，补读缺少的元数据、章节及字幕；失败状态保留。基础概览与已有基础材料耗时计入总时限，不扣补读次数。

`task_mode=reading` 使用 `question` 作为固定基准；`task_mode=learning` 使用视频标题作为当前主题。标题缺失时可显式提供 `video_topic`；无基准时定向读取停止。

每次动作记录 question、relation、relation_reason、parent_read、expected_gain，下一轮 observation 记录新增信息。定向要求 relation=high；探索允许 partial/unrelated。引用父读取时使用本任务从1开始的read_id。语义相关度由模型判断，执行器验证字段、关联编号和分类契约；每日审核负责检查语义偏差。

简介、章节、字幕、弹幕、评论、概览与时间帧均可按目的归类。chapters读取平台目录；chapter_grid按绝对起止秒读取一张9格章节概览，记录chapter_title及chapter_source(platform/inferred)。有平台章节时优先按目录选择，无章节时结合全片概览与字幕推定范围。最多细化一层，然后补事件相邻帧。

每轮显式提供剩余时间、决策轮数、定向及探索额度。停止状态区分 sufficient、low_expected_gain、materials_unavailable、read_budget_exhausted 及现有错误状态。

## 回放入口

`reading_review_runtime.py --config CONFIG --output DIRECTORY REPORT...` 对指定结构化阅读记录进行独立扩展和评分，使用 gpt-6-astra / medium / 正常速度。

默认每批最多3个任务，总时限300秒；每个任务扩展最多2次读取、3轮判断、60秒，探索占比0.5。均可在reading_review配置中调整。它们是回放自身的预算，不改变日常阅读配置。

每日学习的video_reading.reading_review支持 enabled、records_directory、scope、day（可选，默认北京时间当天）及上述预算字段。启用后只选择记录时间属于指定日期、context.task_mode=reading、context.audit_scope匹配的report.json。缺失日期或范围的旧记录不自动归入当天。

三项评分为purpose_deviation、exploration_insufficient、targeted_insufficient，0至3；证据不足为null。每项发现引用原读取与扩展读取编号，并分别记录信息收益和依据当时材料的决策评价。参数只生成建议。

审核输出存放在每日运行review/reading-replay下，使用时间戳和随机后缀创建独立目录；不进入人格输入或知识发布结果，不覆盖原记录。

## 当前接入状态

结构化阅读执行器、原生子代理轨迹转换及每日学习前的自动汇集入口已接入本地源码。原生记录保留真实外层调用、原始返回和时间戳；读取目的仅接受调用前显式记录，缺失保留为空。配置与字段见 NATIVE-READING-TRACES.md。服务器配置尚未启用本轮自动汇集，未部署或重载。

## 视觉预算

全片概览最多一次、两张18格；章节概览由max_chapter_reads限制，默认最多两次，每次一张9格，合计最多36个概览采样位置。指定时刻单帧和相邻帧仍累计最多24帧。章节读取与其他补读共享10次读取、12轮判断和300秒总时限，不按章节重置预算。
