# Tulpa 服务器运行与延迟统计

当前服务器使用 `gpt-6.1-sol`，显式 `model_reasoning_effort="low"`。运行脚本也显式传入这两个参数。持续群聊保持小鲸鱼2号；新龙娘卡与表情包尚未安装。

## 文件

- `runner.py`：运行/续接 Codex 会话，旁路保存带服务器观察时间的 JSONL。记录不调用模型或发送消息。
- `latency.py`：离线计算逐条与首条回复延迟。每次报告创建独立 UTC 时间戳加随机后缀目录。
- `patches/message-schema.patch`：针对 Tulpa `d91c980677197ca4322e083d83937c2883cc943a` 的补丁；文字、图片、表情回应使用互斥 JSON Schema 分支。
- `tests/`：MCP 参数边界与计时计算测试。
- `verify.py`：离线测试及在线工具清单、无发送的无效参数校验、实际模型/思考强度检查。
- `control_current.py`：当前会话状态、停止与生成报告。
- `rollback.py`：检查或回滚本轮工具补丁、模型配置、等待策略。默认只检查；`--apply` 才实际恢复，并停止当前聊天。

服务器运行文件在 `/home/ubuntu/tulpa-test/runtime/`，Tulpa 源码在 `/home/ubuntu/tulpa-test/source/`。当前证据路径由 `/home/ubuntu/tulpa-test/current-live-path.txt` 指向；旧证据保留。

## 延迟口径

| 字段 | 边界 |
|---|---|
| qq_to_receiver | QQ 事件时间 → Tulpa 接收事件 |
| receiver_to_host_delivery | 接收事件 → Codex 宿主观察到 wait/get 工具结果；包含收集、排队和传递 |
| host_delivery_to_plan | 工具结果 → 发起回复规划；包含宿主/模型往返及期间的看图等工具 |
| plan_tool | 规划工具开始 → 返回 |
| plan_to_send | 规划返回 → 发起发送；包含宿主/模型往返 |
| send_to_receipt | 发起发送 → QQ 成功回执；含服务端校验、队列及网络 |
| receipt_to_host | QQ 回执 → 宿主观察到发送工具返回 |
| server_e2e_s | QQ 事件时间 → 成功回执 |
| receiver_to_receipt_s | Tulpa 收到事件 → 成功回执 |

`host_delivery_to_plan` 和 `plan_to_send` 不是纯模型推理耗时。QQ 时间戳只有秒级精度，也可能与服务器时钟有差异；负时间差记为未知。客户端实际显示时刻目前没有采集，`client_display_s` 保持空值，不能把发送回执冒充客户端收件时间。

摘要统计每个回应目标的第一条回复，避免分气泡发送重复计数；被拒绝的调用单列，沉默消息不算成功回复样本。样本数量随报告输出。文本和图片混合样本不能当作同条件性能对比。

低延迟策略：收集静默间隔 0.5 秒、收集上限 1 秒、回复冷却 0.5 秒；wait 明确传 `quiet_seconds=0.5`。相比更长收集窗口，这可能增加连发消息时重新规划的次数，需根据真实平均延迟和拒绝率观察。

## 本机 PowerShell 命令

查看状态：

```powershell
ssh -n -i E:\qq-bot\key\key_gpt.pem -o BatchMode=yes ubuntu@192.0.2.11 'python3 /home/ubuntu/tulpa-test/runtime/control_current.py status'
```

生成当前延迟报告（不触发 QQ 或模型）：

```powershell
ssh -n -i E:\qq-bot\key\key_gpt.pem -o BatchMode=yes ubuntu@192.0.2.11 'python3 /home/ubuntu/tulpa-test/runtime/control_current.py report'
```

停止当前聊天：

```powershell
ssh -n -i E:\qq-bot\key\key_gpt.pem -o BatchMode=yes ubuntu@192.0.2.11 'python3 /home/ubuntu/tulpa-test/runtime/control_current.py stop'
```

回滚前置检查已通过；实际回滚未执行。执行以下命令会停止当前聊天，撤销本轮补丁与配置，重启 Tulpa，但不会自动恢复旧聊天或补发旧消息：

```powershell
ssh -n -i E:\qq-bot\key\key_gpt.pem -o BatchMode=yes ubuntu@192.0.2.11 'python3 /home/ubuntu/tulpa-test/runtime/rollback.py --deployment /home/ubuntu/tulpa-test/evidence/whale-low-latency-20261011T171726.989383Z --apply'
```
