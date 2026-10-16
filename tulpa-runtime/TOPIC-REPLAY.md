# 群聊话题离线回放

回放入口读取历史消息，输出话题分配、搭话建议、回应目标队列和维护者生命周期记录，不发送QQ消息。实时适配入口见 `TOPIC-LIVE.md`；两者共用状态与维护者判断接口。

架构决策见 `docs/adr/0001-topic-maintainers-and-offline-replay.md`。

## 接口

- `TopicState`：有界群消息窗口、话题和独立回应目标。`create_topic` / `retire_topic` 由主会话调用；`assign` 提交维护者的唯一归属和搭话结果。
- `check_reply`：话题级45秒快照宽限；相关版本变化且超过宽限时返回 `needs_refresh`。`refresh_reply` 接受主回答者的语义复核；`cancel_target` 即时取消目标。
- `replay`：按接收时间逐条向维护者提供当前状态。未匹配消息交主会话选择新建、复用或暂缓；异常写入报告，不伪造模型输出。
- `CodexProvider`：维护者使用订阅 `gpt-6-luna / low`；离线主会话使用 `gpt-6.1-sol / low`。每次推理为短上下文隔离调用，禁用所有已配置MCP、搜索和生图。话题的维护者是独立的逻辑状态标识；不为每个话题常驻一个CLI进程。

维护者一次调用分别输出 `addressee`（bot/other/group/unknown）、`intent`（question/request/followup/correction/answer/comment/chat）、`reply_to_message_id`、`topic_id` 和 `should_interject`。明确向机器人的提问、要求、追问或纠正使用上下文回应概率，不受主动插话意愿影响。群消息中的QQ实际@仍由程序识别并优先选择@分支；没有二次复核。

`dialogue_context` 从当前群的已有窗口突出真实引用、当前发言者近期消息、近期机器人发言、最多两组有实际引用依据的问答，以及每个话题最近两条机器人发言；缺失引用仅列出ID，不补造内容。语义承接ID属于可见既往消息；实际QQ引用可保留窗口外编号，并记录 `reference_status=missing_content`。逐条报告包含对象、意图、承接ID和维护者耗时。

通过 `--member-root /path/to/knowledge/group-memory` 读取成员 Markdown 文件头的 `participant_type` 和 `source`。按账号/群隔离，仅向模型提供当前窗口内发言者画像；缺失记录显示“未标记成员”。画像辅助辨认另一 AI 的交流对象，不改变三个概率。报告按已标记真人、另一 AI、未标记成员和本机器人分别汇总，证据目录保存本轮画像快照。

## 参数

`topic-replay-config.json` 是离线试验配置。已确认的参数为活跃话题最多5个、无更新600秒进入回收检查、快照宽限45秒；其他初始数值用于回放观察，可调后再验收。

| 参数 | 初始值 |
|---|---:|
| 群窗口消息数/年龄/总字数 | 200 / 1800秒 / 24000字符 |
| 话题消息数/年龄/总字数 | 50 / 1200秒 / 8000字符 |
| 单条正文上限 | 2000字符 |
| QQ实际@回应概率 `mention_reply_probability` | 1.0 |
| 上下文指向回应概率 `context_reply_probability` | 1.0 |
| 普通主动插话概率 `participation_probability` | 0.15 |

三个概率取值均为0–1，0关闭对应来源，1必选。按实际@、上下文指向、普通主动插话的顺序选择唯一来源，每个已归属消息机会仅抽样一次。实际@由原始 `segments` 与 `bot_id` 比对；文字称呼、无@追问和能力询问由模型根据上下文判断。普通插话先要求模型建议搭话；自身消息仅归类。报告逐条记录来源、模型建议、采用概率、抽样值与入队结果，并按来源汇总。未归属消息记录为defer，不参与入队抽样。记录淘汰不删除历史输入或验证记录。

话题归属结合跨消息语义承接；同一发言者最近参与的话题只作为线索。询问机器人对话、解题与识图功能可连续归入“机器人能力”，首条出现时即可交主会话新建。梗的归属与是否值得回应分别判断。

## 运行

在已登录订阅的Linux隔离目录中加载现有Codex环境后执行：

```sh
source "$HOME/.local/qq-bot-runtime/env.sh"
python3 /path/to/replay_topics.py --input /path/to/messages.json --config /path/to/topic-replay-config.json --output /path/to/evidence
```

输入是按 `at` 升序的JSON数组。每条包含 `id`、`at`（秒时间戳）、`sender`、`text`；可保留 `is_self`、`segments`、媒体存在标记等原始信息。本轮只分类文本和消息元数据，没有重做图片视觉推理。

每次创建新时间戳目录，保存输入、配置、源码快照、模型调用及分配/决策/维护报告。具体调用与报告目录由入口输出。模型输出与实际发送分开：`reply` 表示加入模拟回应队列，不代表已发送。

若数据含经历史成功回执核对的 `historical_reply_to`，对应自己的历史消息到达时关闭其原目标，状态为 `historical_confirmed`。这用于回放原对话的任务结束，不预测新策略的回答内容或时延。空闲达到600秒时，主控制层回收话题，将尚未执行的待答项标记取消并保留原因和记录。已完成搜索/生图产物可保留，但失效话题不继续发送。

## 验证与上线边界

```sh
python -m unittest discover -s tulpa-runtime/tests -p 'test_topic*.py' -v
```

状态测试覆盖容量、归属、队列隔离、维护者回收、历史回执与45秒边界；回放测试覆盖只读过去输入、异常模型输出和独立证据目录。

真实模型回放验证语义分配与决策，离线记录缺失图片内容、先前上下文或发送回执时保留缺口。新策略的实际回答质量、完整端到端时延及实时接收调度留待验收后线上接入。

撤销本轮改动可通过对应Git提交回退；线上进程和配置不受本离线模块影响。原始输入与独立回放证据保留在 `.local/` 及服务器evidence目录。
