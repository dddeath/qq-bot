# QQ Bot

基于 Tulpa 的多机器人群聊系统。Codex 与 Antigravity 使用统一会话管理，机器人可共享工具配置和领域知识库，并保留各自的人格、账号、群绑定和原生线程。

## 目录

- `src/sessions/`：统一配置、会话、执行记录、执行器与 Tulpa 接入。
- `src/runtime/`：持续聊天、话题新鲜度、知识与图库、每日学习、资料探索和轨迹记录。
- `src/runtime/bilibili/`：B站文字资料工具与上游适配。
- `src/runtime/video/`：视频准备、概览采样、图片读取与指定时刻抽帧。
- `config/`：公开参数、输出结构与创作者关注名单。
- `personas/`、`prompts/`、`skills/`：角色设定、执行指令与后台任务流程。
- `assets/`：图库素材；`knowledge/`：领域知识与空白群友画像目录。
- `patches/`：接入 Tulpa 所需补丁；`docs/`：架构与运行说明。

## 入口

| 入口 | 用途 |
|---|---|
| `src/sessions/mcp_server.py --config CONFIG.json` | 主控会话与配置管理 MCP |
| `src/sessions/tulpa_service.py --config CONFIG.json` | 启动机器人绑定的 Tulpa 服务 |
| `src/sessions/tulpa_onebot.py --config CONFIG.json` | 限定账号与群的 OneBot 传输 |
| `src/runtime/runner.py RUN_DIRECTORY --thread THREAD_ID` | 续接 Codex 持续聊天 |
| `src/runtime/daily_learning_worker.py` | 每日学习命令入口，参数见 `--help` |
| `src/runtime/bilibili/server.mjs` | B站只读 MCP |
| `src/runtime/video/server.mjs` | 视频四工具 MCP |

## 环境

需要 Node.js 24+、Python、已登录的模型 CLI，以及独立的 [Tulpa](https://github.com/fumingyang2004/Tulpa) 与 QQ 接入环境。Python 运行时将 `src/runtime`、`src/sessions` 和 Tulpa 源码目录加入 `PYTHONPATH`；`mcp_self_qq.py` 等 Tulpa 扩展依照补丁安装到对应上游包。

```powershell
npm --prefix src/runtime/bilibili ci
npm --prefix src/runtime/video ci
```

B站依赖修正、凭据与视频环境见 [配置说明](docs/configuration.md)。项目不携带外部程序、登录态或运行数据库。部署时按自己的环境配置路径、账号和群。

## 阅读顺序

1. [架构与消息链路](docs/architecture.md)
2. [配置与资源路径](docs/configuration.md)
3. [资料与视频工具](docs/tools.md)
4. [每日学习与原生轨迹](docs/learning.md)
5. [知识库存储布局](docs/knowledge/storage-layout.md)

`knowledge/group-memory/` 保留空白文件结构。其他领域知识库正文包含在仓库；固定 UP 名单仅包含公开领域账号。图片与引用内容来源见各自目录说明，第三方组件遵循各自许可。
