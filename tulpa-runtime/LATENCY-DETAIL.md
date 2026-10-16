# 逐条消息时延追踪

`latency_detail.py` 只读取现有日志和消息库，输出独立时间戳目录中的 `timeline.json` 与 `report.md`。运行不发送群消息、不调用模型、不重启聊天。

## 运行

服务器当前线程的报告命令：

```bash
cd /home/ubuntu/tulpa-test
RUN=$(cat current-live-path.txt)
NATIVE=$(find /home/ubuntu/.local/qq-bot-runtime/codex-home/sessions -name '*01a12fa6-2ca0-7692-a2fe-0a82b135e151.jsonl' -print -quit)
python3 runtime/latency_detail.py \
  --trace "$RUN/timed.jsonl" \
  --native "$NATIVE" \
  --inbox-db source/data/mcp-access.sqlite3 \
  --output evidence/latency-detail
```

更换原生聊天线程后更新 `NATIVE` 的线程编号。`--trace` 可以重复传入，合并同一原生线程的多个宿主运行记录。`--session` 可重复指定 Tulpa 会话编号；默认采用输入日志中的会话。`--tail-seconds` 默认 60，控制长尾标签阈值。

## 输出字段

- `messages`：按 Tulpa 会话编号和事件编号关联。记录 QQ 时间、服务端接收、首次交付、全部规划与拒绝、发送尝试、每个回复气泡的发送开始、服务端回执和宿主观测时间。保留仅接收、已交付未回复及发送无回执的消息。
- `tools`：搜索和生图从初始调用至最终结果的生命周期，包含每次请求、让出执行、等待、返回结果及时间；跨 `exec/wait` 合并，运行切换后隔离复用的 cell ID。`completed` 表示调用返回，`outcome` 单独标记观测到的错误。
- `compactions`：日志明确记载的压缩事件；有开始、结束时间时计算耗时，单独结束事件保留未知起点。只有 token 数量下降时不推断压缩。
- `context_usage`：原生日志的输入、缓存输入、输出 token 和模型窗口记录。
- `summary`：首条及末条回复的均值、P50/P90/P95/P99 和最大值。分位数采用 nearest-rank；统计范围是有相应时间戳的已回复消息。

长尾标签包括搜索重叠、生图重叠、压缩重叠、stale 后重新规划、交付排队、发送回执等待及未归因宿主区间。标签允许重叠，工具重叠耗时按时间区间并集计算。

## 解释边界

工具与消息等待区间重叠，只能证明它们同时发生；群内其他消息也可能触发该工具。不能把整段等待直接算成模型推理或搜索耗时。完整生图生命周期包含宿主轮询间隙，后端真实生成时间没有单独暴露。

QQ 原消息时间为秒级，服务端回执不等于客户端显示时间。未回复可能是正常沉默。报告保留未知时间；日志未出现压缩事件时写 `not_observed`。读取进行中的 JSONL 遇到未写完的行，会在 `sources.invalid_lines` 计数。

原始日志和数据库可能含群聊内容。报告只输出编号、时间、状态、耗时和模型配置观测，不复制消息正文、搜索正文、图片数据或凭据。

## 验证与撤销

```bash
cd /home/ubuntu/tulpa-test/runtime
python3 -m unittest discover -s tests -p 'test_latency_detail.py'
```

工具没有后台进程；停止执行报告命令即可停止生成新报告。移除 `runtime/latency_detail.py` 和 `runtime/tests/test_latency_detail.py` 即可撤销部署，原 `latency.py`、聊天配置、消息库和已有证据保持原状。
