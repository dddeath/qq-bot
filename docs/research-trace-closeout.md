# 网页轨迹与检索收尾

## 网页结果关联

`declare_native_read` 返回带任务及读取编号的 `reading` 标识。执行器同时校验标识、声明参数、原生线程与 `call_id`，保存对应工具输出原文。多个调用争用同一标识时保留未关联状态。

原生日志按读取的 `started_at` 筛选；已知原生线程时直接读取对应日志。轨迹文件后续写入不会改变查询起点。此前缺失的结果只有取得上述完整关联证据后才恢复，并记录原缺失原因。没有结果正文的调用状态、链接和模型总结不替代正文。

## 时间预算

新任务从总时间中预留 `min(60, timeout_seconds × 20%)` 秒收尾。300 秒任务有 240 秒读取窗口和 60 秒收尾窗口，总预算不变。

- `budget_remaining.seconds`：任务总剩余时间。
- `budget_remaining.read_seconds`：继续读取可用时间。
- `finalization_reserve_seconds`：收尾预留时间。

读取窗口结束后，新资料调用返回 `finalization_required`，不占读取次数；`finish_reading_task` 继续可用。已启动的 MCP 读取以读取窗口剩余时间作为超时上限。原生网页调用依赖模型遵守声明协议，宿主仍执行任务总时限。

## 结果回执

`completion` 保存模型的停止声明；`stop_record` 保存执行器最终判定。宿主超时优先反映在顶层 `stop_reason`，不改写模型原文。

`summary_source=model_final` 表示实际最终报告。最终文本缺失而停止声明已保存时，使用其结论原文并标记 `completion_conclusion`，整体状态保留 `partial`。两者均缺失时标记 `missing`。该回执不产生额外模型请求。
