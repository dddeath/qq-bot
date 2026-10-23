# 检索报告与群回复关联

## 主会话输入与工具参数

宿主交付后台结果时，给包含 agent_id、turn_id 和最终报告文本的结果附加 report_ref：report_id 为原生代理与轮次标识，version 为报告文本 SHA-256。字段存储在运行目录的 research-links.sqlite3，账号及群以 conversation_id 隔离。

plan_chat_reply 增加可选 research_reports 数组，每项为 report_id、version。主会话选择本次使用的报告，普通聊天可省略。代理验证引用已经交付且版本匹配后，将该参数从 Tulpa 请求中移除；Tulpa 的参数契约保持不变。

获得 plan_id 后固定记录报告引用。send_chat_reply 返回附带 research_association，包含计划、群和所选报告；恢复同一账目后仍可读取计划关联。此元数据不改变发送次数或重试行为。

## 成功发送与反馈

评审读取器仅纳入 SUCCEEDED 且带 message_id 的气泡。同一回复可引用多份报告，多条成功气泡可属于同一计划。UNKNOWN、取消或失败结果不计入已发送回复。

引用消息 ID 或完整引用回复原文的后续消息保留为明确关联材料，原文不改写，评价含义交给评审判断。时间上相邻但未明确指向的消息保留为待核验材料。

新回执存在时，以显式引用为准；空引用、错误版本或范围不匹配不回退为同轮推断。旧日志仍保留 single_report_delivered_in_response_turn 的历史关联依据，不改写成显式选用。

## 核验入口

runtime_materials 读取实际报告与发送回执；link_feedback 关联原请求、成功回复与后续消息；attach_feedback 将审计材料附到检索评审输入，原始轨迹保持不变。

宿主等待 Codex 运行器通过 codex_overrides 为 Tulpa 代理传递研究关联账目与当前 conversation。其他运行器尚未接入本轮新增回执。
