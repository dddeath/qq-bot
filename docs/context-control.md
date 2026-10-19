# 主线程主动压缩运行器

`runner.py --context-control` 使用 Codex App Server 接管已有原生线程的等待和轮次调度。该模式需显式启用；未指定时，原有 CLI 运行器行为保持不变。

## 消息与压缩顺序

1. 程序调用原 Tulpa `wait_chat_messages`，原激活、合批与 Luna 筛选仍在 Tulpa 侧执行。
2. 空等待继续留在程序内；新消息、后台子代理结果和控制事件交给同一原生线程。原始消息字段及图片块保留。
3. 主线程沿用现有规划、发送、知识库及检索工具，处理本批后结束轮次。等待工具从模型工具列表隐藏。
4. 轮次成功后推进确认水位。失败时保留 `pending-event.json`，不自动重发或确认。
5. 安全边界处执行待处理的压缩，再等待下一批消息。不会中断正在进行的回复或工具调用。

当前指令通过 `developerInstructions` 配置，不作为每次恢复时的新用户消息追加。已有历史中的重复启动消息仍保留；本模式不会清空历史。

## 触发参数

配置文件使用 `main_context`：

```json
{
  "main_context": {
    "target_window": 256000,
    "fast": false,
    "proactive_compaction": {
      "long_tool_seconds": 30,
      "usage_ratio": 0.75,
      "operation_timeout_seconds": 600
    }
  }
}
```

- 实际激活状态从活跃变为休眠时，排队一次压缩；持续休眠不会重复压缩。
- 观察到工具开始和完成且耗时达到阈值后，在当前轮次结束时检查最近上下文 token。严格超过窗口占比才压缩；缺失用量或开始时间时不推测。
- 消息等待不计入长工具。原生自动压缩阈值仍为配置窗口的 90%。本模式尚不能在原生轮次的两个工具步骤之间插入压缩。
- 后台结果由既有原生子代理完成记录读取。匹配到 `task_started` 与完成记录时，按实际时间计算后台耗时，并可在交回主线程前压缩；缺少开始记录时不推测耗时。主线程内的同步工具在当前轮次结束后检查。

## 启用所需绑定

Tulpa 进程需设置 `QQ_BOT_ACTIVATION_STATE=/absolute/runtime/activation-state.json`。激活器按会话写入实际 `active` 状态和观察时间，不写群消息正文。运行器读取同一路径及对应 `ACCOUNT:group:GROUP` 项。

在新运行目录放入当前 `prompt.txt`，沿用原 `CODEX_HOME` 和原生线程、Tulpa 会话：

```sh
python src/runtime/runner.py /absolute/new-run \
  --thread ORIGINAL_NATIVE_THREAD_ID \
  --context-control \
  --tulpa-session EXISTING_TULPA_SESSION_ID \
  --conversation ACCOUNT:group:GROUP \
  --activation-state /absolute/runtime/activation-state.json \
  --policy /absolute/context-policy.json
```

该参数与 `--event-wait` 互斥。切换时先退出旧运行器，同一线程只交给一个运行器；Tulpa 服务和 QQ 登录保持原绑定。已有未确认的 `pending-event.json` 需先核对发送结果。

## 记录与回退

`app-server.jsonl` 保存原生事件；`context-events.jsonl` 保存消息交付、压缩原因、耗时和前后用量；`timed.jsonl` 与 `run.jsonl` 保留供现有时延读取器使用的工具事件格式。token 消耗以原生用量记录为准，压缩后的上下文估算与累计计费用量分别保留。

回退时关闭此运行器，使用原线程启动原 `--event-wait` 模式；不修改人设、学习资料或 Tulpa 会话。实际在线切换须在独立验证通过后执行。
