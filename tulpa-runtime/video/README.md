# 视频概览

`video_frames` 提供四个工具：`watch_video` 准备视频源；`sample_video_frames` 为全片或片段生成概览；`get_frames` 查看已有采样；`get_frame_at` 获取指定时刻画面。图片以 MCP 图像内容返回，字幕沿用 `bilibili_readonly`。模型阅读画面和字幕后，将概要交回主聊天。

## 工具接口

1. `watch_video(video)`：准备 B 站或本地视频，返回源路径与时长，未完成时继续用原参数查询。
2. `sample_video_frames(video, start_seconds?, end_seconds?, frame_count?)`：未指定范围时覆盖全片；指定范围时按原视频绝对秒数采样。默认 18 帧，每 9 帧一张拼图，返回独立 `sample_id`、实际时间和缺失状态。
3. `get_frames(sample_id, kind="grids", start=1, count=2)`：按从 1 开始的图片序号读取，`kind="frames"` 读取该采样的单帧。每次最多 3 张，不生成新帧。
4. `get_frame_at(video, time)`：按秒数、`mm:ss` 或 `h:mm:ss` 从源视频取图，返回请求时间与抽帧 seek 时间；失败返回错误，不换成近邻缓存帧。

片段可继续细分，每次生成独立采样，不覆盖全片或前次片段。采样记录与图片保存在 `QQ_VIDEO_EVIDENCE/frame-store/`；重新启动工具后仍可按 `sample_id` 读取。总读取预算仍由现有阅读任务负责，片段细分不重置预算。

## 运行组件

- yueying 0.2.1，固定提交 `e8fb72eabf9a2193b8d8cf5ce4e5c17de4edbcfe`，MIT：https://github.com/vsh5dvsch7-png/yueying/tree/e8fb72eabf9a2193b8d8cf5ce4e5c17de4edbcfe
- Node MCP 适配器：本目录 `server.mjs`，依赖由 `package-lock.json` 固定。
- B 站视频获取：复用现有 B 站依赖的 API 访问层，读取 BV、分 P 对应的播放信息，仅获取 AVC 视频轨。使用 480p 优先的可用轨道，最高 720p；字幕与音频轨不混入下载。
- 复用 yueying 的 FFmpeg 运行组件，不启动上游自动抽帧任务或 ASR。视频下载未完成时返回 RUNNING；准备完成只探测时长，抽帧由生成工具明确触发。

## 环境变量

| 名称 | 内容 |
|---|---|
| `QQ_VIDEO_PYTHON` | 独立 yueying 虚拟环境的 Python |
| `QQ_VIDEO_BILIBILI` | 当前 B 站适配器目录，包含已修正的依赖与短链接解析器 |
| `QQ_VIDEO_EVIDENCE` | 工具分段耗时 JSONL 目录，每进程独立时间戳文件 |
| `YUEYING_OUT_DIR` | 视频轨缓存目录 |
| `QQ_VIDEO_MAX_SAMPLE_FRAMES` | 每次概览最大采样帧数，默认 18 |
| `QQ_VIDEO_SAMPLE_TIMEOUT_SECONDS` | 每次生成或时间点抽帧时限，默认 90 秒 |
| `QQ_VIDEO_MAX_BYTES` | 单个视频轨下载上限，默认 512 MiB |

视频轨保存在缓存的 `sources` 子目录，供后续指定时间取帧；当前没有自动缓存清理任务。下载和缓存写入由工具完成，群聊天模型仍沿用原权限。

## 验证

本地执行 `node --test test/*.test.mjs`；从仓库根执行 `python tulpa-runtime/video/verify.py` 会创建独立 `.local/video-verify-时间戳-随机号/`，保存命令、输出、退出状态、源码归档与补丁。

服务环境中执行 `node probe.mjs VIDEO`，经真实 MCP 提交视频、查询状态、读取拼图和指定时间图像；输出独立 `probe-时间戳-随机号/`。该探针验证获取与图片传输，语义理解另由 Codex 后台子代理验收。

工具日志记录播放信息读取、下载、各次任务查询和图片读取耗时。查询时间可能重叠后台抽帧执行，不能直接相加当作端到端耗时；模型阅读与整理以 Codex 原生任务时间线为准。

## 部署与回退

服务器组件目录为 `/home/ubuntu/tulpa-test/runtime/video-e8fb72ea`；yueying 使用其中独立 `venv`，不升级 Tulpa 环境。`deploy.py` 仅新增 Codex 的 `video_frames` MCP 配置并更新 `qq-background-work` 技能；不重启服务。

每次首次部署保留独立备份与 `deployment.json`，并在隔离副本执行回退、核对原文件逐字节恢复。回退检查：

```bash
python3 /home/ubuntu/tulpa-test/runtime/video-e8fb72ea/deploy.py --rollback DEPLOY_EVIDENCE
```

同一命令加 `--apply` 恢复部署前配置与技能；目标文件若已被后续修改会停止，避免覆盖新改动。运行中的聊天需另行在主控批准后重载，才能应用工具列表变化。视频缓存、验证证据与聊天历史保留。

## 视频下载恢复

主地址首次失败后，依次等待 2、4、8 秒在主地址重试；三次重试仍失败，才按列表尝试备用地址。主地址单次上限 60 秒，备用地址单次上限 15 秒；下载总预算 180 秒，包含退让等待，最多 6 次请求。只有一个备用地址时最多请求 5 次。大小限制和地址、字节范围校验失败直接结束。

每个获取任务写入独立临时文件；中断后按实际已落盘字节请求 Range，验证 Content-Range 起点、长度和总大小后续传。地址忽略 Range 返回 HTTP 200 时从头重写；完成后才发布缓存。下载失败后清除失败缓存，后续明确请求可重新获取。

`createVideoSource` 参数：

| 参数 | 默认值 | 含义 |
|---|---|---|
| primaryRetryDelaysMs | [2000, 4000, 8000] | 主地址各次重试前的等待毫秒数；空数组直接尝试备用地址 |
| attemptTimeoutMs | 60000 | 主地址单次请求及响应体下载时限 |
| backupAttemptTimeoutMs | 15000 | 备用地址单次请求及响应体下载时限 |
| totalTimeoutMs | 180000 | 下载及退让总预算 |
| maxAttempts | 6 | 全部地址请求次数上限 |

日志记录各次地址角色、退让时间、实际等待时间、单次时限、CDN 主机、阶段、HTTP 状态、接收/预期字节数及脱敏错误。签名 URL 和凭据不进入日志。
