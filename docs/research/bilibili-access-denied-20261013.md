# B 站作者主页 -403：WBI 源码与社区核查

核查日期：2026-10-13。范围：公开源码和 GitHub issue；未登录、安装、调用 B 站业务接口或修改业务代码。本报告的源码结论独立于主控的真实请求验收。

## 结论

核查版本 `XZXZZX-Ai/bilibili-mcp` 固定提交 `1fc29ae7f3c1c672b963a9a96c96687c039b6f1d` 存在三处与可用社区实现不一致的签名逻辑：混合密钥未截取前 32 字符、时间戳字段写成 `timestamp`、签名前没有过滤及 URL 编码。**混排表本身正确，完整 64 项与 yt-dlp 一致。**

主控已另行报告同服务器、同 Cookie、同 mid 的 A/B 结果：64 字符 mix key 返回 -403，截为 32 字符后无论 `timestamp` 或 `wts` 都返回 code 0。这使本例直接原因收敛为 mix key 长度；字段及编码是需要按标准实现校正的其他问题，不能据此称为本例必要根因。真实证据由主控维护：`/home/ubuntu/tulpa-test/evidence/bilibili-wbi-diagnosis-2026-10-13T15-31-27.368Z-0a4f2b01/results.json`；本研究未独立读取该服务器文件。

## 固定源码对照

| 环节 | bilibili-mcp | 独立实现 | 判断 |
|---|---|---|---|
| 混排表 | 46,47,18,2 开头，64 项 | yt-dlp 同一顺序 | 正确，去空白后全表比较结果 `permutation_equal=True` |
| mix key | `map(...).join("")`，完整 64 字符 | 重排后 `[:32]` | 缺少截 32 |
| 时间戳 | Unix 秒写入 `timestamp` | Unix 秒写入 `wts` | 字段不一致 |
| 签名查询串 | 排序后直接拼 `key=value` | 排序、删除值中的 `!'()*`、URL 编码 | 中文、空格及保留符号等输入可能与请求实际编码不一致 |
| 摘要 | MD5(query + mixKey) | 同样结构 | 核心摘要结构正确，输入构造有差异 |

问题源码：[mix key](https://github.com/XZXZZX-Ai/bilibili-mcp/blob/1fc29ae7f3c1c672b963a9a96c96687c039b6f1d/src/bilibili/wbi.ts#L42-L52)、[查询串和 MD5](https://github.com/XZXZZX-Ai/bilibili-mcp/blob/1fc29ae7f3c1c672b963a9a96c96687c039b6f1d/src/bilibili/wbi.ts#L291-L315)、[timestamp 和发送 URL](https://github.com/XZXZZX-Ai/bilibili-mcp/blob/1fc29ae7f3c1c672b963a9a96c96687c039b6f1d/src/bilibili/http.ts#L260-L279)。

独立实现使用 yt-dlp 固定提交 `897341241f2bfb2439fe0367f4c7c9ccd29a3828`；其源码明确给出来自页面 vendor JavaScript 的重排表、前 32 字符截取、`wts`、过滤和 URL 编码。[yt-dlp WBI 实现](https://github.com/yt-dlp/yt-dlp/blob/897341241f2bfb2439fe0367f4c7c9ccd29a3828/yt_dlp/extractor/bilibili.py#L134-L167)

修正编码时应让签名与发送共享规范化参数，覆盖中文、空格、`&`、`+`、`%`、`!'()*` 的测试向量；不要只替换 MD5 前的字符串，却仍发送未规范化的参数。此为代码差异导出的实现建议。

## 社区同类案例

1. **DDBOT #231，2023-05-24。** 报告作者主页接口开始校验 `w_rid` 后，订阅用户出现错误；给出的修正包含 `wts`、同一混排表和前 32 字符截取，维护者随后提供 CI 构建。这个案例证明签名兼容性可以导致相同接口失败；不证明旧示例中的固定 key 或其他网络设置适合今天。本项目只借鉴签名结构，不采用示例里的关闭 TLS 检查。[issue 正文及维护者回应](https://github.com/Sora233/DDBOT/issues/231)

2. **bilibili-dynamic-mirai-plugin #104，2023-06-05。** 用户明确表示已登录、账号正常，但 `/x/space/wbi/acc/info` 返回业务码 -403；维护者要求更新，用户反馈恢复。讨论未提供完整修复 diff，因此只能作为“登录成功仍可能因客户端实现失败”的旁证。[issue 及成功反馈](https://github.com/Colter23/bilibili-dynamic-mirai-plugin/issues/104)

3. **bilibili-helper #106，2023-05-26。** 失败 URL 仅有 mid/jsonp/tid，返回业务 -403；维护者指向 #105，未在本 issue 给出独立修复验收。可证明错误表象一致，证据强度低于前两项。[issue](https://github.com/cssxsh/bilibili-helper/issues/106)

上述均为历史社区报告，不作为 2026 年平台行为保证。当前实际因果以本项目同条件 A/B 为准。

## Cookie 要求与本例影响

社区接口文档要求 `SESSDATA` 和 WBI；关于附加 Cookie 曾有不同经验：旧描述为部分 IP 需要 buvid3，后续 PR #1336 改成包含 SESSDATA 的 Cookie 总项数至少 3。此项属于社区实测归纳，非 B 站正式稳定合同。[认证方式修订 PR](https://github.com/SocialSisterYi/bilibili-API-collect/pull/1336)、[归档文档固定快照](https://github.com/pskdje/bilibili-API-collect/blob/271b123a083698bf576101c21f534b3418768a43/docs/user/info.md#L5-L35)

bilibili-mcp 的 `getAuthHeaders` 已发送 SESSDATA、bili_jct、DedeUserID 三项，因而“只有 SESSDATA”不符合该代码路径。主控保持 Cookie 不变、截 32 后已经成功，也不支持把缺少 Cookie 或账号权限当作本轮首因。应保留现有真实登录态；仅在修正后仍失败时再检查 Cookie 是否实际传递、会话有效性和风控响应。[实际 Cookie 构造](https://github.com/XZXZZX-Ai/bilibili-mcp/blob/1fc29ae7f3c1c672b963a9a96c96687c039b6f1d/src/utils/credentials.ts#L214-L225)

## 最小修正和验收建议

- 先以现有失败请求写回归测试，断言 mix key 长度 32、标准签名向量、`wts` 字段与规范化编码，再修正对应模块。
- 同条件请求验证作者主页，并覆盖其他 WBI 使用处；搜索成功本身不足以证明 WBI 正确，因为该项目视频搜索走另一请求路径。
- 保留 HTTP 状态与响应业务码两个字段；本次问题是响应体 `code=-403`，无需据此重做扫码或更换网络。
- 独立记录请求耗时、错误分类和结果关键字段，日志排除 Cookie；保留失败及成功证据。

本轮仅生成研究文档，无验证脚本，连续两次独立验证目录规则不适用；实际修复验证由主控按项目规则完成。

## 主控两轮真实请求验证

2026-10-13，同一服务器、现有登录 Cookie、目标 mid=4168597，保持 User-Agent/Referer 一致，仅改变时间戳字段和混合密钥长度。两轮独立请求结果完全一致：

| 条件 | 第1轮业务码 | 第2轮业务码 | 返回对象 |
|---|---:|---:|---|
| timestamp + 64字符（原实现） | -403 | -403 | 无 |
| wts + 64字符 | -403 | -403 | 无 |
| timestamp + 32字符 | 0 | 0 | mid=4168597，ZipZipPipe |
| wts + 32字符 | 0 | 0 | mid=4168597，ZipZipPipe |

所有请求 HTTP 状态均为200。成功请求耗时约120–145ms。现有 Cookie 共3项，内容未写入证据。该测试验证了作者资料接口的签名修正效果，未替换安装包，也未证明完整 MCP overview 工具中的后续视频计数请求已经通过。

本地证据：
- E:\qq-bot\.local\bilibili-wbi-diagnosis-20261013T233107438\first-results.json
- E:\qq-bot\.local\bilibili-wbi-diagnosis-20261013T233107438\second-results.json
- 同目录 probe.mjs 为只读对照探针，terminal.txt 与 repeat-terminal.txt 为运行输出。

服务器证据：
- /home/ubuntu/tulpa-test/evidence/bilibili-wbi-diagnosis-2026-10-13T15-31-27.368Z-0a4f2b01/results.json
- /home/ubuntu/tulpa-test/evidence/bilibili-wbi-diagnosis-2026-10-13T15-32-05.662Z-33e76c65/results.json

线上聊天、活动配置及依赖源码均未修改。视频读取 HTTP 412 仍需独立验证，不纳入本次已定位根因的结论。
