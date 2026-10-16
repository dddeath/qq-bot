# QQ Bot

面向 QQ 群聊的多机器人项目，包含官方机器人桥接、Tulpa 聊天接入、Codex / Antigravity 会话管理、本地知识库、每日学习与视频阅读工具。

## 项目组成

| 目录 | 内容 |
|---|---|
| `src/`、`qq-bridge/` | 官方 QQ 机器人与 MCP 事件桥接 |
| `qq-probe/`、`qq-reply-probe/` | 收信、固定回复与群接入探针 |
| `session-runtime/` | Bot、LearningJob、Session、Run 管理与工具配置继承 |
| `tulpa-runtime/` | 持续聊天、话题新鲜度、图库、异步任务、学习和时延轨迹 |
| `tulpa-runtime/bilibili/` | B站检索、简介、字幕、评论、楼中楼与弹幕读取 |
| `tulpa-runtime/video/` | 视频准备、全片/片段概览、已有图片读取与指定时刻抽帧 |
| `tulpa-runtime/personas/` | 机器人角色设定 |
| `tulpa-runtime/skills/` | 后台检索与其他 Agent 工作流程 |
| `knowledge/` | 游戏、社区、创作者与 AI 拟人知识库 |
| `config/` | 公开创作者关注名单等配置 |
| `gemini-bridge/` | 早期浏览器桥接实现 |
| `docs/adr/` | 架构决策 |

## 运行条件

- Node.js 24 或更新版本；Python 运行时及各模块所需依赖。
- 官方机器人入口需要自行创建 QQ 官方机器人并配置凭据。
- Tulpa 入口需要独立安装 [Tulpa](https://github.com/fumingyang2004/Tulpa) 及 QQ 接入环境。
- Codex / Antigravity 需要使用者自行配置对应 CLI、登录态与模型访问。
- 视频模块通过 Yueying 的 FFmpeg 封装读取视频；具体环境及配置见模块文档。

本仓库保留按阶段演进的组件与部署脚本。部署路径、账号、群、工具配置与外部依赖需要按自己的环境设置；不要直接运行历史部署或回滚脚本。

## 安装与离线测试

```powershell
New-Item -ItemType Directory -Force .local
npm --prefix tulpa-runtime/bilibili ci
npm --prefix tulpa-runtime/video ci
node --test test/*.test.mjs
node --test qq-probe/*.test.mjs qq-reply-probe/*.test.mjs
node --test tulpa-runtime/video/test/*.test.mjs tulpa-runtime/bilibili/test/*.test.mjs
```

隧道传输测试额外需要 `.tools/tunnel-client/tunnel-client.exe`，由使用者自行安装。

Python 各模块测试位于 `tulpa-runtime/tests/`、`session-runtime/tests/`，按对应模块依赖安装后运行。涉及 `chatlocal` 的测试依赖独立 Tulpa 源码；统一会话测试需要同时将 `session-runtime` 与 `tulpa-runtime` 加入 `PYTHONPATH`。运行真实 QQ、模型和学习任务前，先完成凭据与群绑定配置。

## 部署文档

- [统一会话管理](session-runtime/README.md)
- [B站只读工具](tulpa-runtime/bilibili/README.md)
- [视频四工具](tulpa-runtime/video/README.md)
- [知识文件布局](docs/knowledge/storage-layout.md)
- [每日学习](tulpa-runtime/DAILY-LEARNING.md)
- [原生检索轨迹](tulpa-runtime/NATIVE-READING-TRACES.md)
- [官方 QQ / dot 初期桥接配置](docs/legacy-dot-setup.md)

## 公开版数据边界

非群友画像的知识库正文包含在仓库中。`knowledge/group-memory/` 保留目录结构和空文件，成员画像、身份映射及互动内容不公开；固定创作者名单只保留公开领域账号。

密钥、OAuth 登录态、Cookie、运行数据库、聊天记录、学习原始材料、验证证据与本地临时文件不包含在仓库中。示例中的账号和服务器地址经过替换，使用前请自行配置。公开 Git 历史从此清理快照开始。

图片素材及引用内容的原始来源见对应目录说明；第三方组件遵循各自许可。
