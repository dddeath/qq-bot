# 每日独立学习

当前群 `1000000011:group:2000000001` 的语言学习由独立 Codex 会话完成：`gpt-6-astra`、`medium`、`service_tier=default`。每天北京时间 04:00 起运行一次，使用 ChatGPT 登录凭据。主聊天模型、人设与 Fast 配置保持原样。

## 文件结构

服务器根目录 `/home/ubuntu/tulpa-test/learning/`：

```text
config.json
groups/1000000011/2000000001/
  learning.sqlite3
  inbox/messages/YYYY-MM-DD.jsonl
  inbox/search-completions/YYYY-MM-DD.jsonl
  state.json
  runs/<UTC时间戳-随机后缀>/
    manifest.json
    input/messages.jsonl
    input/search-completions.jsonl
    input/existing-learning.json
    input/video-reading.json
    input/video/<序号>/calls.json
    input/video/<序号>/result.json
    input/video/<序号>/grid-*.png
    review/candidates.json
    review/evidence.json
    review/assessments.json
    review/validation.json
    published/expressions.json
    published/meanings.json
    execution.json
    execution.jsonl
    execution-result.json
    apply.json
    summary.md
```

`learning.sqlite3` 保存去重材料、已发布内容和每日执行状态。原 `mcp-language.sqlite3` 保留，已启用的表达及已形成含义的术语首次导入新库。每轮成功后在单个事务中发布结果并推进读取位置。

原始消息和搜索材料保留七天，按账号与群归集，不因接收会话重启清空。每日输入保留七天；入选条目的最小来源、审核、发布内容与执行回执长期保留。现有聊天日志不由学习任务删除。

## 采集与发布

- 采集器每分钟只读 Tulpa `chat_inbox`，只接收当前账号与群的真实群友文本，保留发送者与接收会话信息。
- 主聊天搜索补齐信息缺口后调用 `record_completed_search`，将原消息、缺口、补全内容和来源加入材料。异步搜索完成后同样由主聊天记录。
- 每日会话读取上次成功发布之后的新材料，关联仍在七天窗口内的原问题。模型工具关闭，负责提取、语境判断和逐项自检；程序核对来源、原话和发布字段。
- `read_group_learning` 只返回表达、释义、适用场景、条件和稳定条目 ID。来源、可信度及审核结论留在 `review/`。
- 失败保留独立运行目录，当天不自动再次调用模型。检阅失败原因后由主控决定重跑；不推进成功读取位置。

## 每批视频阅读

`video_reading.enabled` 控制每日学习的视频阅读，缺省关闭。开启后，从本轮新增投稿材料中按输入顺序选择最多 3 条视频，每视频最多 2 张关键帧拼图。超额材料保留原有元数据和字幕，记录 `skipped_budget`。抽帧使用现有 `video/server.mjs` 的 frames-only 接口；学习模型通过 `--image` 接收实际图片，工具仍保持关闭。

每日学习配置中的可选字段：

```json
{
  "video_reading": {
    "enabled": true,
    "max_videos_per_batch": 3,
    "max_grids_per_video": 2,
    "video_timeout_seconds": 180,
    "comment_limit": 10,
    "danmaku_limit": 80,
    "node": "node",
    "env": {
      "QQ_VIDEO_PYTHON": "/absolute/path/to/yueying/python",
      "QQ_VIDEO_EVIDENCE": "/absolute/path/to/video/evidence",
      "QQ_VIDEO_BILIBILI": "/absolute/path/to/bilibili",
      "YUEYING_OUT_DIR": "/absolute/path/to/video/cache"
    }
  }
}
```

文字资料沿用顶层 `bilibili_provider` 的 Node、调用脚本与超时配置。视频环境变量可由服务继承，也可在 `env` 中指定；部署时复用已验证的抽帧环境。`max_videos_per_batch` 和 `max_grids_per_video` 可设为 0，以分别停用视频增补或画面读取。

每条视频保留简介、字幕、评论、弹幕的独立状态，画面单独记录时间标注与附件序号。单项失败保留其他材料，超时不自动重新提交视频。`input/video-reading.json` 保存完整增补结果；发布释义沿用既有字段白名单，来源和读取状态留在审核层。图片与本轮视频输入保留七天，审核及发布记录继续保留。配置仅在学习工作进程启动时读取。

## 线上切换

先运行一次独立学习并核验输出，再关闭当前群的旧学习开关，移除主聊天的领取/提交学习工具，加入新学习 MCP。恢复原生聊天线程并验证新知识库、新学习读取和消息等待。

`qq-daily-learning.service` 在服务器运行批处理及采集循环；本机 Codex App 无需常驻。配置 `enabled` 控制每日模型调用，`hour` 为北京时间启动小时。日志由 systemd journal 保存。

## 验证入口

```powershell
& 'C:\Users\USER\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' E:\qq-bot\tulpa-runtime\verify_daily_learning.py
```

每次创建独立证据目录，记录命令、退出码和测试输出。测试边界是学习材料接口和每日执行/发布接口；真实 QQ 接收与角色聊天由主控验收。

回退使用本轮部署目录内的 `rollback.py`：停止新学习服务，恢复旧宿主配置、工具规则与图库配置，重新启用旧群学习，恢复同一原生聊天线程。新的学习结果、图库原件和旧证据均保留。

## 模型驱动的材料探索（待部署）

`video_reading.exploration.enabled=true` 启用下载前判断与迭代读取。基础材料首先读取结构化顶层评论、简介、字幕和弹幕；探索阶段按缺口展开讨论串、补读时间区间或读取实际画面，随后仍由原每日学习模型一次提炼、审核和发布。

默认参数在 `tulpa-runtime/video-reading-policy.json`，可由 `video_reading.exploration` 覆盖：

- `max_read_units=10`：每个视频最多十次补充读取，基础材料不占次数。
- `exploration_budget_ratio=0.2`：探索额度向下取整为两次，其余八次用于定向补读。两类额度分别封顶，失败也占次数；占比为零时关闭额外探索。无需用完额度。
- `timeout_seconds=300`：每个视频探索阶段总时间，包含模型判断与补读，不含初始基础材料读取。
- `max_decisions=12`：判断轮数上限，停止判断也算一轮。
- `comment_page_size=10`：每次补读最多十条评论，分页保持大小不变。
- `max_grids=2`：一次最多两张拼图；指定时间读取为一张原始视频帧。

每次决策使用原订阅 `gpt-6-astra / medium / default` 的独立无工具调用；通过图片附件传入已读画面。程序执行有界只读动作，模型不持有 QQ 工具。判断足够但尚未探索时提醒模型选择未展开材料；确无可读材料时允许说明后停止。模型或读取失败保留已取得的材料，最终发布不夹带审核字段。

`input/video/<序号>/exploration/` 保存逐轮输入、模型输出、耗时、读取结果和最终 `report.json`。本阶段处于七天输入保留范围；入选内容的审核记录仍长期保留。现有每批三个视频上限不变。

群聊后台任务读取 `get_video_context` 返回的同名 `reading_policy`，按技能执行相同读取约定；此路径的累计预算由后台模型遵循，单次工具参数上限由程序执行。每日学习的累计预算和时间由 Python 执行器强制检查。服务器可通过 `QQ_VIDEO_EXPLORATION_CONFIG` 指向同结构的策略文件；部署时需一并同步该文件和新增模块。

验证入口：`python tulpa-runtime/verify_video_exploration.py`。每次创建独立时间戳证据目录，包含完整命令、输出、退出码和代码快照。离线测试中的模型决策为固定外部响应，语义质量、真实评论接口兼容性和服务器耗时仍需主控实测；不自动启动真实学习或重载聊天。
