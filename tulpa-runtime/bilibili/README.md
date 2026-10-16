# B 站只读研究工具

`server.mjs` 在固定的 `@xzxzzx/bilibili-mcp@1.14.2` 上增加工具范围、字幕参数和结果封装。独立 stdio MCP，不新增监听端口。

## 安装与登录

在本目录运行 `npm ci --ignore-scripts --no-audit --no-fund`。Node.js 至少 20。

安装后执行 `patch-upstream.mjs`，环境变量 `QQ_BILIBILI_PATCH_EVIDENCE` 指向备份目录。脚本限定上游 1.14.2，先保存原文件，再修正 WBI 密钥长度、wts、参数编码与普通 API 的登录 Cookie。每次重新 npm ci 后重新执行；已应用时不重复改写。Cookie 仅传给原有 B 站 API 请求，不添加到字幕 CDN 请求。

服务器以运行聊天的同一系统用户执行：

```sh
node node_modules/@xzxzzx/bilibili-mcp/dist/cli.js setup
```

按交互提示使用 B 站 App 扫码确认。上游凭据存储在用户目录 `.bilibili-mcp/config.json`，不加入项目或验证归档。登录后重建 MCP 进程，再用 `check_bilibili_credentials` 检查状态。

登录向导询问 ASR 时选 N。已有登录有效时无需重跑向导。

## 接入

Codex 的 MCP 配置使用服务器 Node 的绝对路径与本目录 `server.mjs` 的绝对路径。`QQ_BILIBILI_EVIDENCE` 指定每进程独立 JSONL 耗时记录目录。工具工具列表更新需要重新加载宿主；部署验收后由主控执行并恢复原聊天线程。

后台研究规则位于 `tulpa-runtime/skills/qq-background-work/SKILL.md`。每次结果返回 `call_id`、`started_at`、`finished_at`、`elapsed_ms`、`source`、`completeness`、`error` 和原始 `data`。资料时间、标题和字幕片段保留在上游 `data`。搜索结果来源逐条保留在 `data` 中。

搜索限第一页，评论是有限样本；`scope.complete=false` 不宣称获取全站或全部内容。字幕返回原有时间戳与分 P，BV 不一致返回错误。上游通过 BV 检查仍不保证字幕对白正确，真实样本需核对原句。ASR 和简介回退关闭。

工具耗时覆盖网络调用及上游解析，不含模型整理和 QQ 发送；后两段使用原生任务与 QQ 轨迹，缺失时不填估算值。并行调用的耗时可能重叠，不能简单相加视作端到端等待。

## 验证与恢复

### 视频材料汇总

`get_video_context` 在同一次调用中读取简介、平台字幕、热门评论和当前弹幕池。默认评论 10 条、弹幕 80 条，上限分别为 50/200，可指定分 P 和字幕/弹幕时间区间。评论与简介属于整条视频；字幕、弹幕绑定选定分 P。每项保留独立状态、来源、获取时间和耗时；失败来源列入 `missing`，其余资料继续返回。画面仍由 `video_frames` 实际读取。

`get_video_danmaku` 返回 `{at_seconds,text}`，以选定分 P 的 CID 请求当前 XML 弹幕池。样本超限时按时间顺序等距选取，返回 `truncated`、池大小及区间内数量；当前池不代表完整历史弹幕。网络复用现有登录与限流；XML 使用 fast-xml-parser，原始压缩体上限 2 MiB、展开上限 8 MiB。HTTP 412、业务码 -403、空池和解析失败分别返回状态，未经重试循环。

协议参考：[B站读取工具的 XML 弹幕与分 P 说明](https://github.com/daymade/claude-code-skills/blob/main/bilibili-source/references/bilibili_api.md)。后台组合流程见 `qq-background-work` 的“视频概览”。本轮新增工具需通过真实平台验收并重载后才进入线上聊天。

`python verify.py` 运行离线公开接口测试，每次写入仓库 `.local/bilibili-verify-<UTC>-<随机后缀>/`，含命令、输出、退出码、源码归档和补丁。

部署时使用独立目录，保留原配置和后台研究技能。启用后回退只恢复本轮 MCP 配置与技能备份，再恢复原聊天线程；保留登录文件、研究结果及旧证据。首次真实平台验收前不启用聊天入口。

`node rollback-upstream.mjs <本轮补丁备份目录>` 检查备份；加 `--apply` 恢复该次补丁前的依赖文件。重建 MCP 进程后生效。补丁、回滚不修改登录凭据。
