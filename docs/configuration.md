# 配置与资源路径

机器人实例的工具白名单、配置版本与资源发布流程见 [机器人配置](bot-configuration.md)。

## 资源

| 路径 | 用途 |
|---|---|
| `config/creator-watchlist.json` | 固定公开创作者与增量读取限制 |
| `config/video-reading-policy.json` | 资料读取与探索预算 |
| `config/daily-learning-schema.json` | 学习输出结构 |
| `config/coupon-catalog-overrides.json` | 图库标注修正 |
| `prompts/daily-learning.md` | 每日学习指令 |
| `prompts/qq-tools.md` | 群聊工具规则 |
| `prompts/tulpa-chat.md` | Tulpa 持续聊天指令 |
| `prompts/qq-research.md` | 后台资料任务指令 |
| `personas/` | 机器人角色卡 |
| `skills/qq-background-work/SKILL.md` | 后台任务技能 |

配置管理通过引用关联资源。已有外部配置引用旧路径时，部署时改为这里的路径；保留原生线程、账号、群及运行数据库。

## B站

```sh
cd src/runtime/bilibili
npm ci --ignore-scripts --no-audit --no-fund
QQ_BILIBILI_PATCH_EVIDENCE=/absolute/private/patch-backup node patch-upstream.mjs
node node_modules/@xzxzzx/bilibili-mcp/dist/cli.js setup
```

上游版本固定为 `1.14.2`。重新安装依赖后执行配套补丁；备份保留在外部目录。登录态由上游保存在用户目录，不放入仓库。`QQ_BILIBILI_EVIDENCE` 指定工具调用记录目录；`QQ_VIDEO_EXPLORATION_CONFIG` 可覆盖默认读取预算文件。

## 视频

| 环境变量 | 用途 |
|---|---|
| `QQ_VIDEO_PYTHON` | 可导入 Yueying 与 FFmpeg 封装的 Python |
| `QQ_VIDEO_BILIBILI` | 已安装并修正依赖的 B站模块绝对目录 |
| `QQ_VIDEO_EVIDENCE` | 图片采样、调用与证据保存目录 |
| `YUEYING_OUT_DIR` | 视频缓存根目录 |
| `QQ_VIDEO_MAX_SAMPLE_FRAMES` | 单次概览采样上限，默认 18 |
| `QQ_VIDEO_SAMPLE_TIMEOUT_SECONDS` | 单次采样超时，默认 90 秒 |

在宿主 MCP 配置中指向 `src/runtime/video/server.mjs`，启用 `watch_video`、`sample_video_frames`、`get_frames`、`get_frame_at`。

## 私有状态

密钥、OAuth、Cookie、QQ 群绑定、运行数据库、学习材料与聊天证据放在仓库外或忽略的 `.local/`。群友画像目录只提供空白结构。

## 外部 MCP 与启动入口

以下 `RELEASE` 为发布版本的绝对路径。配置中须展开为实际路径；MCP 的 `args` 不会自动展开这个变量。

| 外部引用 | 新入口 |
|---|---|
| Codex 知识工具 | `RELEASE/src/runtime/local_knowledge.py` |
| Codex 群文件工具 | `RELEASE/src/runtime/group_files_mcp.py` |
| Codex 学习工具与每日进程 | `RELEASE/src/runtime/daily_learning_mcp.py`、`daily_learning_worker.py` |
| B站 MCP / 批处理入口 | `RELEASE/src/runtime/bilibili/server.mjs`、`call.mjs` |
| 视频 MCP | `RELEASE/src/runtime/video/server.mjs` |
| Antigravity 工具代理 | `RELEASE/src/sessions/tool_proxy.py` |
| 独立账号事件与 Tulpa 服务 | `RELEASE/src/sessions/tulpa_onebot.py`、`tulpa_service.py` |
| 会话控制 MCP | `RELEASE/src/sessions/control_mcp.py` |
| 原生读取轨迹转换 | `RELEASE/src/runtime/native_reading_traces.py` |

Tulpa 服务的 `PYTHONPATH` 包含 `RELEASE/src/runtime` 和 `RELEASE/src/sessions`。`QQ_VIDEO_BILIBILI` 指向 `RELEASE/src/runtime/bilibili`。视频宿主与代理白名单同时包含四个视频工具，确保 `sample_video_frames` 可发现和调用。

`QQ_KNOWLEDGE_ROOT`、图库根目录、账号授权、每日学习配置、原生线程、数据库和证据目录继续引用独立的私有目录。角色卡和工具规则沿用实例当前配置；公共示例不覆盖实例文件。版本迁移保留旧代码和外部配置备份，恢复旧配置与入口即可回退。
