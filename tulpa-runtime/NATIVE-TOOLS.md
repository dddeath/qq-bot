# 原生搜索与明确命令生图

运行入口 `runner.py` 显式设置 `web_search="live"` 和 `features.image_generation=true`，沿用 ChatGPT 登录、gpt-6.1-sol / low / Fast。搜索不要求另装 Skill；不配置 API Key 付费回退。

调用规则集中在 `qq_tools.md`：时效问题按需搜索；生图仅响应明确的画图、生成或编辑请求，默认一张，不因普通聊天、换头像或找表情自动生成。这是模型执行规则，当前不是程序层命令解析器。

`patches/generated-gallery.patch` 为 Tulpa 社区图库增加可选 `generated_directory`。部署值为 `/home/ubuntu/.local/qq-bot-runtime/codex-home/generated_images`；现有账号群白名单仍有效。读取该专用目录下一层会话目录中的 PNG，通过现有图库列表、看图、发送工具使用，无需给聊天模型 shell 权限，也不修改旧图。

验证脚本 `verify-native-tools.py` 每次创建独立时间戳目录，保存实际命令、输出、退出码、补丁和归档。`tests/test_community_media.py` 覆盖生成图片发现、实际读取和群隔离，另运行资料、戳通知、消息参数回归。

部署证据：`/home/ubuntu/tulpa-test/evidence/native-tools-build-20261012T031551.192553Z`。

回退：服务器运行 `python3 /home/ubuntu/tulpa-test/runtime/rollback-native-tools.py /home/ubuntu/tulpa-test/evidence/native-tools-build-20261012T031551.192553Z` 只检查；加 `--apply` 恢复本轮图库模块、运行入口、规则、图库配置，重启 Tulpa 并保持聊天暂停。生成图片和历史证据保留。

本轮学习保持关闭。真实群内的搜索问答、明确生图请求与普通聊天不生图，需要结合后续群消息验收。

## 本轮实际验证

原生实时搜索已返回 Python pathlib 官方文档。原生生图已产出 PNG，模型通过图库实际读取 1,561,965 字节图片；向测试群发送一次后返回 UNKNOWN，等待客户端确认，未重发。生成图片与群发送成功分别记录。
