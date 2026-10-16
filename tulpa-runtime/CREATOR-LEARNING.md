# 固定 B 站账号每日学习

固定账号的公开投稿与动态在北京时间 04:00 的每日学习批次前采集，再交给现有 `gpt-6-astra / medium / normal` 学习会话。主聊天读取发布后的释义；人设、群聊线程和搜索能力保持原配置。

## 账号与采集上限

`config/creator-watchlist.json` 保存采集账号和参数。可供聊天使用的固定 UP 信息见 `knowledge/creators.md`，群友身份见 `knowledge/group-memory/`。都市零协会使用 UID `3632319835409017`。

| 配置 | 默认值 | 行为 |
|---|---:|---|
| `lookback_days` | 7 | 读取近七天目录中的新增内容 |
| `per_account_limit` | 2 | 每个账号每日的投稿与动态合计最多两条，失败也占本日名额 |
| `max_pages` | 1 | 每个账号的投稿、动态分别最多一页；存在后续页时记录截断 |
| `latest_video_check_limit` | 20 | 每个账号每批检查目录中最新的最多 20 个投稿的分 P |
| `video_check_limit` | 30 | 最新投稿与已记录多 P 投稿合计最多检查 30 个；已记录项优先复查最久未检查的投稿 |
| `max_text_chars` | 16000 | 每条动态正文或字幕的字符上限，截断状态进入审核材料 |
| `request_timeout_seconds` | 120 | 单次 MCP 子进程调用的外层超时 |

视频按分 P 的 `ctime` 筛选近七天内容，以账号 UID、BV、CID 去重，再与动态按时间统一排序；每个账号每日最多读取两条。分 P 缺失时间时记录 `needs_verification`，不以 P 序号推断时间。`ctime` 是平台返回的时间字段，审核记录保留 `time_source=part.ctime`。

投稿对应的动态通知与目录中的同一 BV 合并检查；转发动态保留独立 ID。旧 BV 即使首次投稿已超过七天，也检查本批扫描范围内的新分 P。已发现的多 P 投稿进入 `multipart_watch`，之后即使移出最新目录也会在复查额度内轮转检查。首次扫描范围外、此前未记录的旧投稿仍可能漏检。新增确认账号可在当天补采，已有账号不重复读取。已失败的内容保留状态，当前版本不自动重试该内容。

视频读取选定分 P 的平台字幕，来源链接保留 `p`，每日学习增补画面时沿用该分 P；缺字幕时只保留标题、简介和明确的读取范围。动态读取文字与转发文字；图片与音频不自动解读，本流程不调用 ASR。目录有分页截断时，近七天覆盖可能不完整。旧版已读第 1 P 的回执按保存的 CID 参与去重，原回执保持不变。

部署包需包含更新后的 `bilibili/patch-upstream.mjs`，并按既有有备份流程应用上游补丁，以保留 `pages[].ctime`。本地 Node 测试在 HTTP 边界替换响应，验证该字段经实际工具返回。

每日学习开启 `video_reading` 后，对本轮最多 3 条视频增补简介、字幕、评论、弹幕和最多 2 张关键帧拼图，再传给学习模型；采集库存放的原材料保持不变。配置、附件映射与七天保留规则见 `DAILY-LEARNING.md` 的“每批视频阅读”。

## 文件与数据流

服务器配置：
- `/home/ubuntu/tulpa-test/config/daily-learning.json`：每日学习配置，包含 `creator_watchlist` 与 `bilibili_provider`。
- `/home/ubuntu/tulpa-test/config/creator-watchlist.json`：账号与采集参数。
- `/home/ubuntu/tulpa-test/runtime/daily-learning/`：Python 采集与学习程序。

群作用域根目录下：

```text
creator-collection/
  creator-collection.sqlite3       # 每日账号领取、已读 ID 和采集材料
  runs/<UTC时间戳-随机后缀>/
    records.json                  # 本轮逐条读取状态与审核材料
    result.json                   # 本轮账号、分页和采集结果
inbox/creator-content/<日期>.jsonl # 七天有效输入
runs/<学习批次>/
  input/creator-content.jsonl
  review/evidence.json            # 引用材料、来源与读取范围
  published/meanings.json          # 可用于聊天的释义
```

采集材料独立于群消息和搜索补全记录。学习会话把可复用的版本知识、社区用语写入 `meanings`；公开投稿不充当群友原话表达样本。发布层保留释义、使用场合与日期/版本条件，来源和可信度留在审核层。学习输入七天后清理，采集回执与审核证据保留。

## 验证与运行

离线验证：`python tulpa-runtime/verify_creator_learning.py`。每次创建独立时间戳目录，分别运行原每日学习与新增采集接口测试。真实采集不触发额外模型学习或 QQ 发言；首次采集到的材料等待 04:00 批次。

服务沿用系统级 `qq-daily-learning.service`，配置读取发生在启动时。更新学习配置后重启该服务；无需重启 QQ 或主聊天。`--collect-only` 仍只采集群消息，`--once` 会执行本日采集与学习，正常运行交由既有服务。

停用固定账号采集：将 watchlist 的 `enabled` 设为 `false`，保留原每日群消息学习。完整恢复部署前程序使用本轮部署目录的 `rollback.py --apply`；该命令恢复原学习程序和配置并重启学习服务，既有材料与审核记录保留。
