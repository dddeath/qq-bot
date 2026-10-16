# 视频概览组件比较

## 结论

优先评估 **yueying**：复用已有 Bilibili 元数据、字幕工具和后台子代理，只增加关键帧提取及图片读取。已有字幕时用 `watch_video(mode="frames")` 跳过语音识别，再用 `get_frames` 读取带时间戳的拼图；字幕缺失时再评估本地 ASR（语音转文字）。视频内容的理解仍交给现有 Codex，新增组件无需付费模型 API。此为基于源码的选型建议，尚未安装或接入 QQ/Tulpa 实测。

## 核验范围

2026-10-14 读取项目 README、依赖声明和源码。固定快照：

- [yueying e8fb72ea](https://github.com/vsh5dvsch7-png/yueying/tree/e8fb72eabf9a2193b8d8cf5ce4e5c17de4edbcfe)，包版本 0.2.1。
- [video-vision-mcp 128b7d76](https://github.com/KitDevUA/video-vision-mcp/tree/128b7d763282be2080328b3f2f173fa6939b498d)，包版本 0.4.0。

以下“已确认”限于源码或项目文档，未验证下载成功率、中文识别质量、运行时间和现有客户端的图片传递。

## yueying 已确认能力

- 六个 MCP 工具：`watch_video`、`get_transcript`、`search_transcript`、`get_frames`、`get_frame_at`、`list_videos`。`watch_video` 返回概览文字，图片由后两个图像工具按需返回，采用 SDK `Image(data=..., format="jpeg")`，不是只提供文件路径。`get_frames` 默认两张、上限三张，可取 3×3 拼图或单帧。[MCP 实现](https://github.com/vsh5dvsch7-png/yueying/blob/e8fb72eabf9a2193b8d8cf5ce4e5c17de4edbcfe/src/yueying/mcp_server.py)
- 子进程执行下载、字幕和抽帧；工具默认等待 45 秒后返回 `RUNNING`，再次以相同视频调用会附着原任务。默认同时运行一个任务，其余排队；运行中状态保存在服务进程内，服务关闭会终止任务，不应视为可跨重启续跑的任务系统。`mode="frames"` 传入 `--no-asr`，平台字幕仍可使用。[任务与模式实现](https://github.com/vsh5dvsch7-png/yueying/blob/e8fb72eabf9a2193b8d8cf5ce4e5c17de4edbcfe/src/yueying/mcp_server.py)
- URL 下载走 yt-dlp，并读取平台人工/自动字幕；浏览器登录通过 `cookies_from_browser` 传入 yt-dlp。Bilibili 分 P 和合集见项目说明；MCP 一次按单视频处理，批量入口在 CLI `--all`。下载格式优先 ≤720p，但源码保留更高分辨率兜底，故并非严格硬上限。[下载实现](https://github.com/vsh5dvsch7-png/yueying/blob/e8fb72eabf9a2193b8d8cf5ce4e5c17de4edbcfe/src/yueying/download.py)、[使用说明](https://github.com/vsh5dvsch7-png/yueying/blob/e8fb72eabf9a2193b8d8cf5ce4e5c17de4edbcfe/README.md)
- Python ≥3.10，依赖 faster-whisper、yt-dlp、imageio-ffmpeg、Pillow、MCP 2.x；CUDA 依赖可选。项目声明字幕优先，缺字幕时 GPU 默认 large-v3-turbo、CPU 默认 small；首次使用需要下载权重。源码采用 MIT 许可。[依赖及许可声明](https://github.com/vsh5dvsch7-png/yueying/blob/e8fb72eabf9a2193b8d8cf5ce4e5c17de4edbcfe/pyproject.toml)
- 项目说明默认删除已下载源视频、保留分析产物；这时指定时刻取图可能回退至最近缓存关键帧。它适合大致观看，快速动作、短暂画面和小字仍需补读单帧。登录 cookie 在服务运行机器读取，不能假定用户桌面的浏览器登录能直接用于远端服务。[输出及取帧说明](https://github.com/vsh5dvsch7-png/yueying/blob/e8fb72eabf9a2193b8d8cf5ce4e5c17de4edbcfe/README.md)

## video-vision-mcp 已确认能力

- 四个工具：`analyze_video`、`get_video_transcript_only`、`extract_frames_at`、`list_recent_analyses`。本地后端直接返回文字与 MCP `ImageContent`；分析默认最多 60 帧、最大边 1024 像素。未见 yueying 式提交/轮询接口，工具直接等待 pipeline 返回。`get_video_transcript_only` 仍调用完整分析 pipeline，本地后端会抽帧，只是不把图片返回给调用者。[工具](https://github.com/KitDevUA/video-vision-mcp/blob/128b7d763282be2080328b3f2f173fa6939b498d/src/video_vision_mcp/server.py)、[图像内容](https://github.com/KitDevUA/video-vision-mcp/blob/128b7d763282be2080328b3f2f173fa6939b498d/src/video_vision_mcp/backends/base.py)、[本地流程](https://github.com/KitDevUA/video-vision-mcp/blob/128b7d763282be2080328b3f2f173fa6939b498d/src/video_vision_mcp/backends/tier1_local.py)
- Bilibili 页面 URL 不是现成入口：yt-dlp 分流域名清单包含 YouTube、Vimeo 等，未包含 bilibili.com 或 b23.tv，其他 URL 按普通 HTTP 文件下载；未见 cookie 参数。现成接入宜先获得本地视频文件，再传 `file_path`。[URL 下载实现](https://github.com/KitDevUA/video-vision-mcp/blob/128b7d763282be2080328b3f2f173fa6939b498d/src/video_vision_mcp/sources/url_loader.py)
- 本地后端使用 ffmpeg + whisper.cpp，默认 base 模型；Python ≥3.10，依赖包含 pywhispercpp、static-ffmpeg，以及三个云服务 SDK；MIT 许可。没有密钥时使用本地后端，但启动时会读取环境和 `.env`，并按 Gemini > OpenAI > Groq > local 自动选择；只关闭 Gemini 仍可能走云端 ASR。因此“无需 API 密钥”成立，“任何现有启动环境都只在本地运行”不成立。[配置](https://github.com/KitDevUA/video-vision-mcp/blob/128b7d763282be2080328b3f2f173fa6939b498d/src/video_vision_mcp/config.py)、[依赖声明](https://github.com/KitDevUA/video-vision-mcp/blob/128b7d763282be2080328b3f2f173fa6939b498d/pyproject.toml)

## 对现有机器人的最小接入建议

1. 沿用现有字幕与元数据入口；对需要了解画面的请求，将抽帧和读取任务交给已有后台子代理。
2. 首轮只评估 yueying 的 `frames` 模式：读取少量拼图，结合现有字幕生成带时间戳的概览；遇到文字、界面或图表细节再取单帧。
3. 子代理返回概要和关键时间点，主对话按需追问细节；无需把整批帧重复灌入主对话。
4. 缺字幕的视频再决定是否启用本地 ASR。当前选型不要求新增付费 API，也不要求替换现有 Bilibili 工具。

接入前需核验三个实际链路：Bilibili 视频在服务机器能否取得；MCP 图像块是否完整进入 Codex 子代理视觉输入；后台任务结束后是否正确回传当前 QQ 会话。尤其要测“确实看见帧内独有信息”，而不只核对图片路径或转录摘要。以上建议尚未实施。
