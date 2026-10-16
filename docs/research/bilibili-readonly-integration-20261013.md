# B 站只读接入核查

核查日期：2026-10-13。源码基线：[`1fc29ae7f3c1c672b963a9a96c96687c039b6f1d`](https://github.com/XZXZZX-Ai/bilibili-mcp/commit/1fc29ae7f3c1c672b963a9a96c96687c039b6f1d)，包版本 `1.14.2`。本次仅阅读公开源码、文档；未安装、登录、调用 B 站接口或修改运行服务。

## 结论

适合以独立 stdio MCP 进程接入现有后台研究任务，优先复用完整上游进程，无需搬入整套源码。上游十二个工具覆盖读取和诊断，没有账号发帖、点赞、评论写入工具。服务直接公布完整工具表，没有在已核查入口中实现工具白名单；本项目应在客户端或薄适配层限制暴露范围。ASR 参数属于字幕工具自身参数，单靠工具名称白名单不能移除它们；首期不安装 ASR，适配层固定 `fallback_to_asr=false`、`force_asr=false`。[服务入口](https://github.com/XZXZZX-Ai/bilibili-mcp/blob/1fc29ae7f3c1c672b963a9a96c96687c039b6f1d/src/server.ts#L34-L51)、[工具调用分派](https://github.com/XZXZZX-Ai/bilibili-mcp/blob/1fc29ae7f3c1c672b963a9a96c96687c039b6f1d/src/server/tool-handlers.ts)

实施前的人工作业是用户选择 B 站账号并扫码确认登录。技术验证还需确认服务器网络、登录有效性、目标样本字幕和评论覆盖、客户端工具过滤及进程恢复。现有公开资料不足以断言这些已通过。

## 版本、许可与运行依赖

- 当前核查源码声明 Apache-2.0；`1.14.0` 起迁移许可，`1.13.1` 及更早发布版本保留旧 GPL-3.0。建议固定 `1.14.2`，保留其 LICENSE；不要从旧版复制代码却套用新版本许可。[package.json](https://github.com/XZXZZX-Ai/bilibili-mcp/blob/1fc29ae7f3c1c672b963a9a96c96687c039b6f1d/package.json#L51-L75)、[许可迁移记录](https://github.com/XZXZZX-Ai/bilibili-mcp/blob/1fc29ae7f3c1c672b963a9a96c96687c039b6f1d/CHANGELOG_EN.md#L23-L40)
- 运行要求 Node.js ≥20；生产依赖为 MCP SDK、commander、dotenv、qrcode-generator、quick-lru。首期字幕读取不需要 Python、浏览器、FFmpeg 或本地 ASR 模型。[运行依赖声明](https://github.com/XZXZZX-Ai/bilibili-mcp/blob/1fc29ae7f3c1c672b963a9a96c96687c039b6f1d/package.json#L61-L75)
- 推荐独立目录固定 npm 版本，stdio 启动。候选命令 `npx -y @xzxzzx/bilibili-mcp@1.14.2`，正式部署可预安装后使用确定的可执行路径，避免每次启动依赖包下载。源码默认导出 server，也可程序化复用；内部 `client.ts` 只是若干模块的兼容 re-export，未构成独立稳定客户端 SDK，直接移植会连带凭据、WBI、限流、缓存、字幕校验依赖。[入口](https://github.com/XZXZZX-Ai/bilibili-mcp/blob/1fc29ae7f3c1c672b963a9a96c96687c039b6f1d/src/index.ts#L1-L23)、[client.ts](https://github.com/XZXZZX-Ai/bilibili-mcp/blob/1fc29ae7f3c1c672b963a9a96c96687c039b6f1d/src/bilibili/client.ts)
- `v1.14.2` Git tag 解析到 `5b65c1a7ef1c967c124c944b02cfba97a9d5ee84`，与本次 master 核查 SHA 不同。部署时须检查实际 npm 包与所需修复，不能把 master SHA 写成 npm 包来源证明。[版本标签](https://github.com/XZXZZX-Ai/bilibili-mcp/tree/v1.14.2)

## 首期接口与完整性

| 接口 | 输入和可用结果 | 边界 |
|---|---|---|
| `search_bilibili_videos` | `query`、`limit`；BV、标题、作者、时间、时长、简介、URL | 默认 5、最大 10；平台综合排序；源码固定 `page=1`，无搜索翻页参数 |
| `get_video_metadata` | `bvid_or_url`；标题、作者、发布日期、简介、标签、统计、分 P/CID | 不读取字幕或评论 |
| `get_video_transcript` | BV/URL、语言、`page`、时间范围、`query`、时间戳；文本、命中上下文、时间点链接 | 关键词为大小写不敏感的字面匹配；最多 20 个命中、每侧最多 5 段；默认无字幕返回明确错误 |
| `get_video_comments` | BV/URL、`detail_level`、`limit`、`sort`、`include_replies` | 主评论 1–50；内部最多 3 页；子回复有界，非完整评论树 |
| `get_video_chapters` | BV/URL、可选 `page`；章节起止秒数 | 没有章节返回空数组 |
| `search_bilibili_creators` | `query`、`limit`；候选作者及稳定数字 `mid` | 默认 5、最大 10；同名保留候选，不自动选定 |
| `get_bilibili_creator_content` | `mid`、`section`、可选容器和 `cursor` | 主页概况、视频、合集、系列、动态；分页每页最多 20；图片只返回 URL，动态长文章全文未实现 |

运行诊断可保留 `check_bilibili_credentials`，配置说明由主控使用。`get_video_info` 与明确区分元数据/字幕的流程重叠，可先不暴露；当前账号收藏夹和更新检查不属于本次研究内容。

接口依据：[工具参考](https://github.com/XZXZZX-Ai/bilibili-mcp/blob/1fc29ae7f3c1c672b963a9a96c96687c039b6f1d/docs/tool-reference.en.md#L24-L139)、[输入 schema](https://github.com/XZXZZX-Ai/bilibili-mcp/blob/1fc29ae7f3c1c672b963a9a96c96687c039b6f1d/src/server/tool-schemas.ts#L387-L1011)、[搜索固定第一页](https://github.com/XZXZZX-Ai/bilibili-mcp/blob/1fc29ae7f3c1c672b963a9a96c96687c039b6f1d/src/bilibili/search.ts#L136-L208)。

评论实现的补充：`limit>20` 才顺序分页，固定页长 20，再本地裁剪；每个主评论最多读取响应内 3 条子回复。`detailed` 且 `include_replies=true` 会把这些回复追加到扁平结果，因此总结果条数可能超过主评论 limit。`summary.total_comments` 是返回条数，不是该视频完整评论数量。上游返回结果没有为评论提供继续翻页 cursor 或完整性证明，本项目应标记为有界样本。[分页及返回实现](https://github.com/XZXZZX-Ai/bilibili-mcp/blob/1fc29ae7f3c1c672b963a9a96c96687c039b6f1d/src/bilibili/comments.ts#L227-L319)

## 登录及凭据

搜索、作者检索与作者内容必须有配置且已登录的 Cookie。上游推荐 `setup` 在交互终端使用手机 B 站 App 扫码并确认；没有二维码 MCP 工具。二维码流程为官方 passport generate/poll，3 秒轮询，单次 180 秒；过期后需用户重新扫码。[英文安装说明](https://github.com/XZXZZX-Ai/bilibili-mcp/blob/1fc29ae7f3c1c672b963a9a96c96687c039b6f1d/README_EN.md)、[二维码源码](https://github.com/XZXZZX-Ai/bilibili-mcp/blob/1fc29ae7f3c1c672b963a9a96c96687c039b6f1d/src/bilibili/qr-login.ts#L131-L169)

凭据由 `SESSDATA`、`bili_jct`、`DedeUserID` 构成；默认保存 `~/.bilibili-mcp/config.json`，目录 0700、文件 0600，临时文件写入后 rename。环境变量优先于文件；进程缓存凭据，重配后应重连并调用 `check_bilibili_credentials`，核验 configured/logged_in。诊断不得输出 Cookie 值。[存储与读取](https://github.com/XZXZZX-Ai/bilibili-mcp/blob/1fc29ae7f3c1c672b963a9a96c96687c039b6f1d/src/utils/credentials.ts#L20-L22)、[写入及优先级](https://github.com/XZXZZX-Ai/bilibili-mcp/blob/1fc29ae7f3c1c672b963a9a96c96687c039b6f1d/src/utils/credentials.ts#L85-L142)

上游更新记录明确表示二维码流程有自动化覆盖，但真实手机确认及 Windows/macOS/Linux 原生终端扫码验收尚未验证。因而首期应实际走一轮服务器交互终端扫码，不把 README 的推荐方式当作实测通过。[二维码验收状态](https://github.com/XZXZZX-Ai/bilibili-mcp/blob/1fc29ae7f3c1c672b963a9a96c96687c039b6f1d/CHANGELOG_EN.md#L27-L33)

## 无字幕与错视频字幕

`get_video_transcript` 默认返回 `SUBTITLE_UNAVAILABLE`；显式简介回退才返回简介，且简介回退与关键词、时间范围、时间戳互斥。账号过期返回 `COOKIE_EXPIRED`，HTTP/风控/超时不当作无字幕。`get_video_info` 则默认回退简介，因此研究流程优先使用 transcript + metadata 两个明确接口。[错误合同](https://github.com/XZXZZX-Ai/bilibili-mcp/blob/1fc29ae7f3c1c672b963a9a96c96687c039b6f1d/docs/tool-reference.en.md#L47-L75)

平台 AI 字幕标记 `data_source=ai_subtitle`。选中 ai-* 后会双读核对稳定性；ai-zh 还做语言比例检查。1.14.2 增加可信分 P 时长检查：字幕末尾超过视频时长 5 秒则拒绝该正文。**同语言、稳定且处于时长内的错误内容仍可能通过**，源码明确承认该限制。验收必须核对 BV、分 P/CID、实际对白片段与时间点，而非只看请求成功。[校验源码](https://github.com/XZXZZX-Ai/bilibili-mcp/blob/1fc29ae7f3c1c672b963a9a96c96687c039b6f1d/src/bilibili/subtitle-integrity.ts#L13-L132)、[修复记录](https://github.com/XZXZZX-Ai/bilibili-mcp/blob/1fc29ae7f3c1c672b963a9a96c96687c039b6f1d/CHANGELOG_EN.md#L7-L11)

## 接入与验证入口

1. 固定包版本、建立独立 stdio 进程，设置读取工具集合及字幕参数边界；不改 QQ 发送接口。
2. 用户完成交互扫码后核验登录。读取少量已知 BV/作者和一个主题搜索样本。
3. 校验正常字幕、多 P 时间链接、无字幕、账号失效、无搜索结果、评论 limit 及截断；检索结果和动态图片 URL 不计为已看视频/图片。
4. 结果封装平台、BV/mid、标题、URL、发布时间、获取时间、正文来源、时间点、完整性和错误状态。原始数据保留，研究阶段补充游戏版本线索；不要从发布日期直接推断游戏版本。
5. 通过后接入现有后台研究 skill，由主会话带回结果；沿用现有 QQ 发送幂等规则。

每段单独记录搜索、详情、字幕、评论、模型整理和 QQ 发送耗时。上游默认请求间隔 500ms、单请求超时 10 秒，AI 字幕双读及评论分页会增加网络请求；这些不是端到端时延保证。[请求配置](https://github.com/XZXZZX-Ai/bilibili-mcp/blob/1fc29ae7f3c1c672b963a9a96c96687c039b6f1d/src/config.ts#L40-L49)

未实测：平台登录、412/风控下成功率、完整字幕归属、服务器网络与版本依赖、长期登录态、各段时延。ASR、自动抓取定时任务、收藏夹和账号写操作均未进入首期。

本报告未创建验证脚本；连续两次独立验证目录规则本轮不适用。实现及真实验收时按项目规则保留每轮独立时间戳证据。
