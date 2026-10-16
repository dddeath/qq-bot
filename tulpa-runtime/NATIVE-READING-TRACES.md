# 原生子代理阅读轨迹

`native_reading_traces.py` 按原生会话元数据中的父线程关系发现指定主线程的子孙线程，以 `call_id` 配对调用与返回，生成独立 `report.json` 快照。原日志只读，变化产生新目录；相同内容重复采集不产生新快照。

## 每日自动汇集

在每日学习的 `video_reading.reading_review` 中配置：

```json
{
  "enabled": true,
  "records_directory": "/absolute/path/reading-records",
  "scope": "explicit-group-scope",
  "native_traces": {
    "enabled": true,
    "sessions_directory": "/absolute/path/codex-home/sessions",
    "parent_thread_ids": ["explicit-main-thread-id"]
  }
}
```

每日回放选取记录前先汇集，按配置范围和记录末尾时间的北京时间日期筛选，同一子线程仅选最新快照。范围由配置指定，不从聊天文本猜测。父线程应限定在对应阅读工作流；采集器不根据自然语言猜测子任务类别。跨日线程仍保存完整快照，未按调用逐日切分。

## 记录字段

- `raw_call`、`result.raw_outputs`：原生日志中的完整调用行及匹配的返回行；日志已截断的内容保持原样。
- `source_line`、`native_source`：源文件实际行号与路径。
- `started_at`、`finished_at`、`elapsed_seconds`：调用记录到最后匹配返回记录的墙钟跨度。没有有效时间戳时为空。
- `purpose_record`、`purpose_source`：当时明确记录的目的和记录位置；没有记录时为空。
- `missing`、`orphan_outputs`、`issues`：缺失字段、未配对返回及重复调用编号等问题。
- `continuation_of_call_id`：仅凭明确的运行 cell ID 关联 `exec` 与 `wait`，各段耗时保持独立。

`output_recorded` 表示原生返回已留存，操作是否成功查看原始返回。`exec` 保留整个脚本和全部返回，不执行脚本来重建历史，也不把整段耗时分配给内部工具。返回中的工具自身计时仍保留在原文。

## 调用前目的记录

后台阅读子代理在调用前输出一行 commentary：

```text
READING_PURPOSE {"tool":"exec","purpose":"targeted","question":"核对技能消失时间","relation":"high","relation_reason":"直接回答原请求","expected_gain":"定位变化发生的回合"}
```

`purpose` 使用 `targeted` 或 `explore`，`tool` 必须匹配下一次真实外层调用。标记只消费一次；用户文本、工具返回或事后标记不改写已发生调用的目的。不同目的分开调用。协议随 `skills/qq-background-work/SKILL.md` 下发，标记不发送到 QQ。

旧记录没有标记时保留空值。完全缺少目的记录的原生任务，其目的偏差评分固定为空；没有明确单视频映射时仅审核现有材料，不猜视频地址自动扩展。新协议及自动汇集须在部署配置后生效。

## 验证

`tests/test_native_reading_traces.py` 覆盖配对、缺失、跨轮标记、后代发现、独立快照、继承历史边界和等待关联；`tests/test_reading_review.py` 覆盖缺失目的时的评分。`verify_video_exploration.py` 每次生成独立验证目录，保存命令、标准输出、错误输出和退出状态。

## 日常检索入口

`qq-background-work` 将阅读轨迹协议随原生派发下发。子代理在首个调用前记录含 `first_read` 目的对象的 `READING_TASK`，后续目的优先保存在前一条 `READING_OBSERVATION.next_read`，独立调用也可用 `READING_PURPOSE`、返回后记录 `READING_OBSERVATION`，结束时记录 `READING_END`。任务声明保留原目标、event_id、单视频链接和预算；单视频链接包含分 P，供独立回放补读使用。

转换器只接受 assistant 消息中的标记。任务声明必须早于首个调用；观察关联最近一项已有返回的调用，保留原始返回作为核验依据。目标及预算标为模型声明，新增信息标为模型评估，实际调用与墙钟耗时仍取原日志。停止后又发生调用时清除旧停止状态。旧轨迹不补写。

这套标记不新增 MCP 工具。技能文件更新后，新派发必须读取并传递完整协议；已经启动的子代理不自动获得协议。线上原生线程是否读取新版应通过新任务轨迹验收。

`trace_quality` 列出缺失目的、结果、观察的 call_id 及入口/停止状态。`complete` 只说明这些记录齐全，模型结论仍须对照真实返回审阅。
