# 空等待入口

`src/runtime/runner.py --event-wait` 为已有 Codex 原生线程启用事件等待。未指定该参数时，沿用原入口。

- 直接暴露 `chat_wait.wait_chat_messages`，从原 Tulpa 工具列表中隐藏旧等待入口；其他工具保持原配置。
- 空 `idle` 在程序内续等。新消息、控制状态、连接异常及提示更新返回模型；完整消息和图片结果保持原样。
- 程序每次最多在 Tulpa 等待 10 秒，期间新消息可立即返回。间隔检查同一原生线程的子代理完成记录，后台结果的额外等待通常不超过这一轮等待时间。
- 一次直接工具调用最长 3600 秒，达到上限返回 `wait_deadline`，模型可继续下一次等待。MCP 超时为 3660 秒。
- 原生子代理完成记录从当前 `CODEX_HOME/sessions` 增量读取；只读当前主线程的直接子代理，不回放启动前的历史完成记录。

启用示例（在已有运行目录之外新建本轮运行目录并放入 `prompt.txt`）：

```sh
python src/runtime/runner.py /absolute/new-run-directory --thread ORIGINAL_NATIVE_THREAD_ID --event-wait
```

运行器用命令行覆盖启用本入口，不写入全局 Codex 配置。切回时使用同一原生线程启动运行器，去掉 `--event-wait`。部署前需确认当前 CLI 接受 `features.code_mode.direct_only_tool_namespaces`，并在独立会话验证等待工具确实作为直接工具调用。
