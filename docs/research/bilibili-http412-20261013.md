# B 站 HTTP 412：请求头兼容性核查

日期：2026-10-13。仅研究公开 GitHub issue 与固定源码；真实服务器请求和 A/B 验证由主控执行。本轮未登录、部署、修改业务代码或创建验证脚本。

## 结论

社区存在**同时补齐 User-Agent 和 Referer 后 HTTP 412 消失**的直接日志，并已进入项目修复。但也有清空 User-Agent 后恢复的反向案例。因此请求头值得优先做单因素比较，不能从社区经验直接断言完整浏览器 UA 或 Referer 末尾斜杠是本例根因。

主控描述的同服务器普通 curl view 成功而 Node 上游 view 失败，使请求头、请求库及最终发送参数成为具体排查入口；搜索成功只能证明搜索路径可用，不证明 view 路径相同。尚未从本轮研究独立读取主控的真实请求记录。

## 案例一：youwee #75 有前后日志及代码修复

2026-06-04，报告者给出同一 BV 的两个命令：默认 yt-dlp 在下载网页阶段得到 HTTP 412；同时指定完整 Chrome UA 和 `https://www.bilibili.com/` Referer 后继续取得信息并完成下载。维护者 6 月 8 日表示已在 v0.17.0 发布修复。[原始 issue](https://github.com/vanloctech/youwee/issues/75)、[发布确认](https://github.com/vanloctech/youwee/issues/75#issuecomment-4644791210)

固定修复提交 `0854cf99a78594ca16e946d653b1db47885aec06` 增加 `build_site_header_args`，仅对 B 站和 b23 域名传入完整浏览器 UA 与带斜杠 Referer，并接入视频信息、元数据、下载及频道读取。[实现提交](https://github.com/vanloctech/youwee/commit/0854cf99a78594ca16e946d653b1db47885aec06)、[请求头构造源码](https://github.com/vanloctech/youwee/blob/0854cf99a78594ca16e946d653b1db47885aec06/src-tauri/src/services/ytdlp.rs#L917-L950)

这个案例能支持“客户端请求头组合影响 412”。它没有单独控制 UA 与 Referer，且目标是视频网页，不是本项目 `/x/web-interface/view`，因此不能直接证明斜杠或 UA 中某个片段的必要性。

## 案例二：yt-dlp #17605 含不同错误层级

2026-09-02 的首帖标题为 view API `code -412`；日志显示调用方服务 HTTP 500，内部错误文本称上游业务码 -412，没有提供 B 站原始 HTTP 状态。维护者指出该段并非 yt-dlp 原始日志。[issue](https://github.com/yt-dlp/yt-dlp/issues/17605)、[维护者回应](https://github.com/yt-dlp/yt-dlp/issues/17605#issuecomment-5503672116)

同一讨论后续评论另提供 yt-dlp 原始日志：默认 UA 网页请求 HTTP 412，指定空 UA 后成功列出格式。评论者也描述 Cookie 对结果的影响，但没有可直接迁移到本项目的完整受控实验。[带原始日志的评论](https://github.com/yt-dlp/yt-dlp/issues/17605#issuecomment-5506480533)

因此记录应分别保存 `http_status` 与 `api_code`：HTTP 412、HTTP 200 内业务 -412、调用方封装 HTTP 500 是不同观测。只记录“412”会丢失决定排查路径的证据。本轮不采用讨论中的代理相关建议。

## 当前 bilibili-mcp 源码事实

基线 `1fc29ae7f3c1c672b963a9a96c96687c039b6f1d`：

- 默认 UA 为 `Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36`，缺少通常浏览器 UA 后续产品信息；默认 Referer 为 `https://www.bilibili.com`，没有末尾 `/`。这两项是可核实字符串差异，不是已经实证的错误根因。[配置](https://github.com/XZXZZX-Ai/bilibili-mcp/blob/1fc29ae7f3c1c672b963a9a96c96687c039b6f1d/src/config.ts#L41-L50)
- 普通请求将这两项写入 headers，`response.ok` 失败后抛出携带 HTTP 状态的 NetworkError。[普通请求](https://github.com/XZXZZX-Ai/bilibili-mcp/blob/1fc29ae7f3c1c672b963a9a96c96687c039b6f1d/src/bilibili/http.ts#L429-L478)
- `getVideoInfo` 的 view 调用没有显式传入登录 headers；搜索调用则传入登录 headers。故即便全局登录检查成功，两个请求的实际 Cookie 也可能不同，应看请求路径构造而非账号状态推断。[view 调用](https://github.com/XZXZZX-Ai/bilibili-mcp/blob/1fc29ae7f3c1c672b963a9a96c96687c039b6f1d/src/bilibili/video-api.ts#L249-L258)、[搜索请求](https://github.com/XZXZZX-Ai/bilibili-mcp/blob/1fc29ae7f3c1c672b963a9a96c96687c039b6f1d/src/bilibili/search.ts#L136-L163)
- 字幕 WBI 请求有 HTTP 412 时转 `/x/player/v2` 的专用回退；view 获取失败在这之前，不能靠该字幕回退修复。[字幕回退](https://github.com/XZXZZX-Ai/bilibili-mcp/blob/1fc29ae7f3c1c672b963a9a96c96687c039b6f1d/src/bilibili/video-api.ts#L260-L318)

## 本例最小验证矩阵

保留同服务器、同 BV、同请求库和 Cookie 条件，分别比较：默认头、仅补全 UA、仅补 Referer `/`、两者同时调整。另用成功 curl 的实际请求头作为对照，记录 HTTP 状态、响应业务码、耗时和少量结果身份字段。

若组合成功，仍需单因素及第二轮独立运行确定最小修正；若 curl 和 Node 在头一致时仍不同，再检查最终 URL 编码、自动附加头及请求库行为。无需因搜索正常而跳过 view 验证，也无需因某次 412 就重做账号登录。

本报告没有执行验证脚本，双独立时间戳目录规则本轮不适用；实现及主控真实验收继续沿用项目证据规则。

## 本项目修复与真实验收

主控在服务器对同一个详情地址做了单因素对照：原请求 HTTP412；完整浏览器 UA 仍412；仅补 Referer 末尾斜杠仍412；仅携带现有登录 Cookie 返回 HTTP200、业务码0及正确BV。直接问题是普通 API 请求未复用登录 Cookie。

补丁仅在普通 B站 API 请求头注入现有 getAuthHeaders，显式调用方请求头仍优先。不向字幕 CDN 添加登录凭据。未增加代理、切换账号或安装 ASR。

修复版本通过实际 stdio MCP 获取了两个视频的详情、带时间戳前90秒平台AI字幕及评论，完整作者主页（包括后续视频数量读取）也成功。评论 limit=5 为主评论上限，含回复后返回15条/13条，仍标记有界样本。

本轮源码与验证目录：E:\qq-bot\.local\bilibili-fix-20261013T233821842。
真实调用证据：/home/ubuntu/tulpa-test/evidence/bilibili-live-2026-10-13T15-42-45.686Z-93b73ed1。
线上聊天没有重启，活动 MCP 配置尚未切换；候选目录已经包含修复。
