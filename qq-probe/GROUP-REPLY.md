# 指定群的一次固定回复

## 运行

```powershell
node E:\qq-bot\qq-probe\group-reply-run.mjs
```

读取本机保存的配置：

- 凭据：`E:\qq-bot\.local\qq-auth\config.json`
- 测试群绑定：`E:\qq-bot\.local\qq-group-receive\test-group.json` 的 `group_openid`

每次运行生成新的唯一文本。主控确认现有接收进程与连接边界后启动探针，等待 `READY`，再组织群成员在绑定群发送显示的文本，不加 @ 或引用。

探针新建一个独立、最多等待十分钟的接收连接；接收完成后关闭该连接，再向原群尝试发送一次 `QQ 群固定回复验证成功。`。发送等待上限十五秒。它不启动 dot、不改动私聊服务或持续接收配置。`Ctrl+C` 取消本次探针；已经发出的请求保留为待核验，不自动重发。

## 结果

记录保存在 `E:\qq-bot\.local\qq-group-reply\run-<UUID>.json`，包括运行版本、命令、时间、绑定群、唯一文本、实际收到的事件、发送结果和退出状态。

- `GROUP_FIXED_REPLY_API_CONFIRMED`、退出 `0`：平台返回了回复消息 ID。群内是否只收到一次仍需成员确认，记录中的 `qq_client_receipt` 保持 `PENDING_USER_CONFIRMATION`。
- `NOT_VERIFIED`、退出 `2`：查看顶层发送阶段或 `receive.records` 中的接收失败阶段与错误码。
- `EVIDENCE_WRITE_OR_RUNTIME_FAILED`、退出 `2`：运行或记录写入失败，检查记录目录及运行环境。

`attempt-<SHA256>.json` 是发送前创建的持久化占位。相同机器人、群和原消息 ID 再次到达时，保留占位并阻止再次发送；失败或未知结果也不释放占位。运行记录保存实际发送结果，占位文件不代表送达。

## 离线验证

```powershell
node --test E:\qq-bot\qq-probe\group-reply.test.mjs
node E:\qq-bot\scripts\verify.mjs
```

离线测试替换外部 HTTP 和 WebSocket，使用真实接收、发送实现和临时文件目录，不连接真实 QQ。完整回归同时检查既有私聊、只接收探针、桥接和合成事件。

## 回滚

停止本次探针后，撤销本工单实现提交即可恢复代码；具体提交及已核验命令见工单实施记录。保留 `.local` 中的凭据、群绑定、占位和原始证据，避免回滚清除去重记录。
