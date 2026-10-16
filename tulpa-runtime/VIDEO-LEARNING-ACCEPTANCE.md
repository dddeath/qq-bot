# 视频学习与阅读回放验收

每日视频学习先读取标题、作者、分 P、简介、字幕及章节，再进行一次全片稀疏采样。模型看到实际样本后选择定向补读、探索或结束。

- `frames.coverage` 保存采样范围、位置、缺失槽位和时间依据；`continuous` 始终为 false。缺少覆盖元数据时标为 unknown，图片返回成功不代表看完视频。
- 同一视频共用 `video-reading-policy.json` 中的读取、时间、章节和帧数预算。探索占比默认 20%；初始稀疏概览计入读取预算。单段至多 12 秒、8 帧，细读累计至多 24 帧。
- 定向读取关联学习视频主题；探索可发现旁支，转定向时须说明与主题的关联。每轮保存目的、实际新增信息、预算及耗时。
- 每日回放默认选择北京时间前一日、当前群的真实阅读记录。原记录保留，补读使用独立预算；当时缺失的目的不补猜。
- `change-requests.json` 保存 `pending_controller_review` 修改请求及来源。请求不修改线上参数、程序、人设或知识。
- 仅视频验收不发布结果、不推进原学习游标、不重复学习群聊表达。聊天和每日调度在正式切换前继续使用原版本。

验证入口：Python unittest 的 `test_learning_upgrade.py`、`test_daily_video.py`、`test_video_exploration.py`、`test_reading_review.py`、`test_native_reading_traces.py`，以及 `video/test/*.test.mjs`。
