# 群消息激活

Bot 的 `activation` 控制休眠与活跃状态；状态按账号和群隔离。未配置时关闭，保持原等待行为。

```json
{
  "enabled": true,
  "threshold": 8,
  "weights": {"human": 1, "video_share": 5, "bot": 0.5},
  "active_idle_timeout_seconds": 900,
  "buffer_ttl_seconds": 3600,
  "bot_ids": ["OTHER_BOT_ACCOUNT"],
  "immediate": {"mention_self": true, "reply_to_self": true}
}
```

机器人身份取配置中的已确认账号，不能从显示昵称推断。视频分类优先于发言者类别，每条只计一次；支持视频段、B 站视频地址／短链／BV 号、YouTube 视频地址。本机器人回流不计分、不延长活跃时间。

休眠时，尚未交付消息累计达到阈值，或实际 @、引用机器人消息时激活。活跃时按现有 quiet/batch 规则交付；15 分钟无外部新消息返回休眠。缓冲过期按服务接收时间计算。过期只排除本次交付候选，不删除聊天历史。原消息 ID、原始内容、批次和发送授权沿用 Tulpa。

## 应用

1. 通过现有配置接口写入 `Bot.body.activation`，选择明确版本；`session_effective_configuration` 返回该参数。
2. 导出固定 Bot 版本：

```sh
python src/runtime/activation.py --database SESSION_DB --bot-id BOT_ID --version VERSION --output NEW_CONFIG_PATH
```

3. 将 `src/runtime/activation.py` 放入 Tulpa 服务的 Python 模块路径，在 Tulpa 源码目录应用 `patches/activation-gate.patch`。
4. Tulpa 服务设置 `QQ_BOT_ACTIVATION_CONFIG=NEW_CONFIG_PATH`。该变量属于 Tulpa 服务，不属于模型进程。服务启动时读取固定快照；各机器人实例分别导出。
5. Codex 主会话继续使用 `--event-wait`；空 idle 在宿主内续等，后台结果和控制事件沿用原链路。

服务启动初始休眠；进程内保留各群激活状态，原收件箱保存待交付消息。重启后重新按仍有效的待交付消息计算。外部服务配置与重载须单独执行。

## 回退

移除 Tulpa 的 `QQ_BOT_ACTIVATION_CONFIG` 并重载服务即可恢复原消息交付；反向应用补丁可移除入口。保留群聊历史和当前原生模型线程。
