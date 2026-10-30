# 知识应用与概率裁决

## 配置

Bot 的 `knowledge_application` 随固定版本导出到 Session 工具快照。默认关闭；`baseline` 保留按表达需求或信息缺口读取的现行策略，`gain` 启用宿主概率裁决。首阶段适配 Codex 宿主等待运行器。

```json
{"knowledge_application":{"enabled":true,"strategy":"gain","gain_inclination":0.5,"gain_adjustment_limit":0.15}}
```

两个数值都接受 0～1 的有限数值。`gain_inclination` 是基础倾向 b，`gain_adjustment_limit` 是最大修正幅度 a。保存新版本不改变原 Session 绑定；没有新增环境变量。启用 gain 的有效快照须含一个配置了 reading_trace 的只读 stdio 提供方，导出及启动时校验入口。模型提示与工具说明不包含这两个参数及其实际值。

## 模型判断与宿主裁决

模型按两步判断，只新增一个 `subjective_inclination` 数值 s：

1. 先检查是否有充分、具体的证据确定直接作答或确定检索。直接作答需要已有材料覆盖当前需求，并有具体依据确认补读没有增益；确定检索需要能指出影响回答的信息缺口或具体收益。只有现成答案、熟悉感或笼统的检索意愿时，保留中间态。`objective`、`expected_gain` 保存目标与简短依据。
2. 第一阶段确定直接作答时输出 0，确定检索时输出 1；中间态输出 0 与 1 之间的主观检索倾向。资料正确性、检索成功率和判断置信度另行判断。

- s=0：直接作答。
- s=1：直接检索。
- 0<s<1：δ=a(2s−1)，p=clip(b+δ,0,1)。宿主生成 u∈[0,1)，u<p 时检索。

次数、时间、工具范围和披露预算独立生效。配置参数与抽样值仅存于审核轨迹；模型接收执行方向和关联 ID。

`knowledge_sampling.evaluate` 是计算与反事实回放入口；`sample` 生成真实抽样。固定 s 和 u 时，提高 b 不会降低本次裁决。真实模型对收益的判断质量需要另行回放评估。

## MCP 入口

gain 模式准备检索时调用 `begin_reading_task`；准备直接回复时须在 `plan_chat_reply` 中提交判断或沿用决定，避免直接回复额外增加独立决策工具往返。

```json
{"goal":"核对收藏品条件","_knowledge":{"action":"research","trigger":"answer_improvement","target_event_ids":["request-1"],"objective":"核对收藏品条件","expected_gain":"补充可能影响建议的适用条件","subjective_inclination":0.8}}
```

回复规划的 action 使用 `reply`。后续调用使用 `_knowledge.decision_ids`，不重新生成倾向。

| 返回 next_action | 调用方后续动作 |
| --- | --- |
| direct_reply | 使用已有材料规划回复；未创建检索任务 |
| begin_reading_task | 使用返回的 decision_ids 创建检索任务；当前未创建回复计划 |
| read | 使用 task_id 和 execution_prompt 执行任务 |
| continue_reading | 当前任务尚未完成；继续或用真实停止原因结束任务 |

所有新读取由 `begin_reading_task` 创建任务，资料工具只使用 `_reading`，任务内不再次采样。首次判断仅由 `begin_reading_task` 和 `plan_chat_reply` 接收；`read_research_report` 的 `_knowledge` 只接收原研究的 `decision_ids`。自行和后台执行沿用同一任务。任务创建后需要先告知正在检索时，回复规划使用 `_knowledge.phase=acknowledgement`；最终回复默认 phase=final，等待任务的 completion.json 完成回执。已有回复工具、发送回执及权限检查保留。

直接调用资料工具绕过任务入口、遗漏首次倾向或覆盖宿主参数时返回参数错误。未启用或 baseline 策略继续使用原工具接口。

## 决定、任务与恢复

`Application` 复用 Run 的应用记录数据库。当前 Run 与配置版本内，相同原消息集合共用首次裁决，目标文字不参与决定身份；数据库事务保证只采样一次。重复声明保持原值；试图替换已采样倾向时返回原决定 ID 及复用指引。

已登记决定跨进程恢复继续使用原抽样。兼容旧记录中含目标文字的 ID，同一消息集合采用最早已登记决定，不重写其标识、抽样或历史任务。原任务参数与任务位置固定，重试或跨轮用 decision_ids 续接；任务、证据和剩余预算不重新创建。新消息可形成新决定；首次声明限于当前已交付消息。跨轮只续接原研究决定及其任务，回复目标须属于对应原消息集合；旧直接回复决定不用于新轮次。

任务预留、文件创建与实际调用回执各自记录。任务文件创建中断后按原标识恢复；缺少完成记录保持未完成。最终结果未知时不推断为成功。

## 轨迹与评审

审核导出保存：原请求、实际 Bot/Session/Run 标识、模型声明、s/b/a/δ/p/u、裁决分支、工具实际参数与结果、预算、耗时、任务停止原因、发送回执及明确关联评价。确定性分支的 δ/u 为 null。

基础倾向与修正幅度位于宿主记录。主会话协议 `knowledge-application-v2` 与抽样协议 `knowledge-sampling-v1` 分别记录。gain 使用新版命名空间；baseline 沿用 v1 路径与已登记记录。

`knowledge_application_replay.review_bundle` 沿用原消息、报告与反馈关联，包括采样后未检索的回应。发送未知、缺少评价及缺少模型计量各自保留缺失状态。参数建议由后续学习评审提出，当前不自动修改配置。

成功读取返回 `knowledge_application.read_id` 字符串，回复规划将实际采用的字符串原样填入 `used_read_ids`。该标识复用已有应用调用 ID；旧调用方使用 `knowledge_application.call_id` 继续有效。任务内数字 `read_id` 保留在执行器报告中，用于定位该任务的一次读取。

应用调用回执记录字符串标识与任务 ID、任务内读取序号及证据文件的映射；执行器的交付记录包含相同的模型可见回执。评审输出的 `used_materials` 根据成功发送回复引用的标识展开工具和证据位置。不同任务的相同数字序号保持独立，失败读取与控制回执不产生可引用读取标识。

## 验证与后续边界

基础验证覆盖配置快照、模型可见内容、三分支、公式和固定抽样单调性、真实 MCP、重试与恢复、失败记录、回复和反馈关联。QQ 发送在隔离传输夹具验证，实际模型表现与群内运行单独验收。

执行者交接登记、跨轮研究线索、共享累计预算与学习自动调参仍是后续机制。独立学习任务本轮不继承聊天概率裁决。
