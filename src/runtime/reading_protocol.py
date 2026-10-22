"""Task-specific execution instructions generated at the MCP task boundary."""
import json
import math

VERSION = 'reading-v2'

def generate(task_id, context):
    budget = context['budget']
    policy = dict(overview_limit=3, max_read_units=budget['max_read_units'],
                  exploration_limit=math.ceil(budget['max_read_units']*budget['exploration_budget_ratio']),
                  exploration_budget_ratio=budget['exploration_budget_ratio'], timeout_seconds=budget['timeout_seconds'])
    from learning_research import OVERVIEW
    policy['overview_tools'] = sorted(OVERVIEW)
    policy['counting_rule'] = '概览类工具最先的3次读取使用概览额度，其余每次调用使用1次补读额度；探索调用另受探索总额度限制。失败调用计数。视频准备、采样、读图分别计数。'
    task = {'task_id':task_id,'task_mode':context['task_mode'],'goal':context['goal'],
            'context':context.get('task_context',{}),'video':context['video'],'budget_policy':policy}
    role = ('直接回答用户原请求，返回结论、依据和仍缺材料。' if context['task_mode']=='reading' else
            '依据目标和用户评价原文核对材料，返回新信息、评审意见和仍缺材料。')
    protocol = '''直接调用已开放的只读检索工具完成本任务，不派生子代理。任务数据如下：
'''+json.dumps(task,ensure_ascii=False)+'''\n先读取廉价基础概览，再依据缺口选择补读。
所有MCP资料读取统一填写 _reading：task_id、purpose(targeted/explore)、reason(本次要查什么)、relation(与目标的关系)，可附 prior_observation。
定向须与本任务目标高度相关；探索可以旁支，探索转定向时记录与目标的关联依据。
原生网页读取先调用 declare_native_read，填写 task_id、native_tool="exec"、native_input(完整网页工具调用代码)、purpose、reason、relation。
将返回的 native_input 交给 exec 执行，保留 reading 标识，每个标识对应一次调用；读取或等待后续结果同样先声明。执行器按真实call_id保存结果，不以总结替代原始返回。
按工具返回的 budget_remaining 判断剩余额度。overview_units 与 read_units 分开计数，exploration_units 是探索调用的额外上限，不是新增读取额度。视频准备、抽帧、读图各计一次。时间预算覆盖整个任务。
每次追加检索前，结合 budget_remaining.seconds 和刚才调用耗时，判断剩余时间是否足够完成下一次读取、记录轨迹和整理结论。时间不足时立即停止追加检索，提前调用 finish_reading_task，输出已有依据支持的结论和仍缺材料，不等待硬超时。尚有余额但因时间不足提前收尾时，stop_reason 使用 cancelled，reason 明确写明时间不足提前收尾；不要声明预算已耗尽。
信息足够时可少量探索；无需耗尽预算。停止前调用 finish_reading_task，填写 task_id、stop_reason(sufficient/budget_exhausted/no_readable_material/cancelled)、reason、conclusion。预算耗尽须与账本一致；收到校验错误后根据实际余额修正停止声明。
图片实际返回像素后才算看过；缺失结果保留缺失状态。最终报告引用本轮read_id，保留来源供主会话核对。
'''+role
    return dict(protocol_version=VERSION,execution_prompt=protocol,budget_policy=policy)
