---
status: accepted
date: 2026-10-19
---

# Bot 的 QQ 能力由固定版本工具配置解析

## 决策

- 延续 ToolProfile → Bot → Session 的固定版本引用，不新增独立 Bot 管理体系。
- ToolProfile 的 `qq_tools` 保存共享能力组、常驻规则和操作说明正文。Bot 的 `qq_tools` 仅覆盖启用状态与已声明参数。
- 运行器使用会话工具快照生成工具清单和能力摘要。详细说明由 `read_qq_tool_guide` 按需读取，不在启动时全部注入。
- 参数通过现有工具服务配置传入。账号、群与真实发起者的操作校验仍由实际工具执行，提示词不授予权限。
- `qq_context` 和 `qq_guide_notes` 属于 Bot 专属资料，继承工具配置时不复制这些内容、人格或图库。
- 文档正文进入 ToolProfile 版本及会话快照，修改仓库 Markdown 不会让已运行会话隐式读取新版本。

## 迁移

没有 `qq_tools` 的旧 ToolProfile 保留原行为。新配置显式编译、登记版本并导出到新目录；加载时保留原生线程及原群绑定。回退使用原配置版本和快照，不回滚聊天记录。
