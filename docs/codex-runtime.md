# Codex 分阶段工具目录运行要求

启用 `knowledge_application.decision_probe` 的聊天使用动态 MCP 工具目录：裁决前仅返回当前允许的工具，commit 后开放读取与收尾，finish 后移除读取。工具执行端仍核验任务阶段和预算。

## 固定运行时

`config/codex-runtime.json` 是此模式的 Codex 包版本来源。聊天启动命令使用对应版本目录中的 CLI，不使用 PATH 中的其他版本。现有 `env.sh` 继续提供 Node、CODEX_HOME 和原有连接配置；本改动不增加同义环境变量。

当前验证版本为 `0.167.0-alpha.4.1`。`0.162.1` 会忽略 `features.mcp_tool_list_changed`，在活跃轮次中保留过时工具目录；仅重载 MCP 配置未能恢复这一轮的目录切换。

部署时，在发布目录中读取固定版本并准备依赖：

```sh
version=$(python3 -c 'import json; print(json.load(open("config/codex-runtime.json"))["version"])')
prefix="$HOME/.local/qq-bot-runtime/codex/$version"
source "$HOME/.local/qq-bot-runtime/env.sh"
npm install --prefix "$prefix" --no-audit --no-fund "@openai/codex@$version"
"$prefix/node_modules/.bin/codex" --version
"$prefix/node_modules/.bin/codex" -c features.mcp_tool_list_changed=true features list
```

发布包必须同时包含 `config/codex-runtime.json`、`src/runtime/codex_runtime.py`、`codex_app_transport.py` 及调用它们的聊天运行器。依赖安装完成后再切换运行器；安装失败保留旧运行器和原线程。

## 启动验收

App Server 初始化后、首次 `thread/start` 或 `thread/resume` 前，宿主使用同一连接的 `experimentalFeature/list` 核对功能存在、启用且未被移除。分页结果完整读取；检查失败不进入线程启动或模型请求。不使用版本号大小推测能力。

运行证据记录 `host/runtimeCapabilities`：实际 `userAgent`、要求的功能、功能返回值和验证结果。检查每个 App Server 连接执行一次。没有要求动态目录的调用沿用原行为。

完整验收需使用原生 Codex 和真实 MCP，观察 commit 后读取／finish 可调用，以及 finish 后读取退出目录。直接用 MCP 客户端查询列表通过，只证明服务端目录正确，未证明模型宿主已经刷新。

## 轨迹核对

`ResearchTrace` 保存任务目标、查询、每次读取的原始结果与交付结果、预算和停止原因；`Application` 保存原事件、裁决、模型可见 read_id 与回复规划；发送工具的成功回执保存 plan_id 和 message_id。检查整条链时按这些 ID 关联，不把独立研究报告当作完整发送记录。未观察到群内后续评价时保留缺失状态。

## 回退

回退对应代码提交及原启动配置即可恢复旧启动方式；不修改知识库、任务数据库或聊天历史。仍启用动态工具目录时，旧 CLI 的目录刷新缺陷会随旧启动方式恢复。

协议参考：[Codex App Server：功能发现与 MCP 管理](https://learn.chatgpt.com/docs/app-server)。
