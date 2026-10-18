# Luna 消息筛选

Bot 配置使用 config/examples/chat-screening-policy.json 的四个字段，创建新版本后显式应用。激活分数10、其他机器人0.25；活跃态普通消息满10条或30秒交给筛选器。实际@与引用直接交付。后台结果和控制事件继续沿用等待入口。

筛选会话 purpose=screening，按Bot账号和群隔离，使用gpt-6-luna/high/Fast，每批独立原生执行。输入为消息原文、有界近期对话和当前群相关成员画像。模型输出只存入执行记录；主线程收到原始消息，不附带筛选理由、类别或摘要。

QQ_BOT_ACTIVATION_CONFIG 导出文件的 bots.<账号> 下包含 activation 字段内容及 batching、screening。文件根需增加 screening_runtime：sessions_database（统一会话数据库）、state_root（筛选水位目录）、evidence_root（模型轨迹目录）、profile_files（按账号:group:群号，再按QQ号映射当前群画像文件路径）。这些是实例私有路径，不提交公开仓库。profile_files 只配置群员画像。

筛选水位与主线程cursor分别维护。沉默消息保留到原有TTL，后续唤醒可随原始上下文交付。筛选异步执行；主线程等待期间可继续响应后台结果。每批失败或中断记录失败并放行该批原文，不自动重试模型调用。

runner.py --policy <Bot策略JSON> 读取 main_context：默认256000上下文、关闭Fast；常规容量压缩阈值为窗口90%，避免沿用旧1M阈值。休眠自动压缩未实施。已有原生线程的实际上下文切换需上线前独立核验。

部署顺序：验证Codex参数与订阅调用；导出并补齐实例私有路径；保留原配置后应用Bot新版本；短暂重载Tulpa及同一聊天线程；最后验收群内实际收发。本地通过不代表线上已生效。
