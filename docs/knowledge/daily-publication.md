# 每日学习增量发布

每日学习校验后的内容先写入学习数据库，再发布到配置的 Tag 存储。发布复用知识维护 MCP 底层的 EntryStore 创建和修订接口；机器人与检索子代理保持只读。

## 配置

在宿主管理的 daily-learning.json 中设置 session_id 为已登记的学习 Session ID，并增加 knowledge_publication 对象：

- entry_store：机器人实际读取的条目快照绝对路径。
- policy：已审核的 Tag 规则文件绝对路径。
- mappings：首次导入的来源映射绝对路径。快照包含 import_mappings 后以快照为准。
- annotations：可选，已审核的特殊标签映射绝对路径。

非空快照缺失来源映射时停止发布。未配置 knowledge_publication 时只发布学习数据库，不更新 Tag 存储。旧配置未提供 session_id 时仍为空，部署时须填入已有学习 Session 标识。

## 增量行为

只导入当前账号、当前群的已发布学习；不导入审核材料或未校验候选。相同来源保留条目 ID，未变内容保持修订；更新通过 EntryStore.update 写入。Tag 沿用现有规则与审核映射，未匹配条目保留无 Tag 状态，可用正文检索。

人工修改、撤回或合并引发映射冲突时，本批不覆盖目标快照。旧来源缺失不自动删除。正式知识与其他群内容保持原样。候选通过基线哈希检查后原子发布，常驻知识工具每次读取相同存储路径，无须重载工具列表。

## 状态与重试

批次目录的 tag-publication.json 记录发布状态；tag-publication/时间戳目录保留基线、候选、变更和回执。学习生成成功、知识发布失败时，学习批次仍为 completed。

普通调度不反复重试已完成批次。修正配置或冲突后，以原配置运行 daily_learning_worker.py --once；当日学习已完成时仅重试发布，不请求学习模型。历史日期批次可由维护代码调用 publish_pending(learning, config, run)。成功发布后重复调用返回原回执。

session_id 从宿主配置依次传入 worker、Learning、recorded；native_session_id 仍从真实原生执行日志回填。

## 回滚

运行 knowledge_tag_publish.py rollback --candidate <发布候选目录>，恢复该次发布前快照。当前快照已有后续写入时，哈希检查会停止回滚，保留后续数据。
