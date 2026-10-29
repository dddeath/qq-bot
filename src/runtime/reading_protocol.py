"""Task-specific execution instructions generated at the MCP task boundary."""
import json
import math

VERSION = 'reading-v8'

def generate(task_id, context):
    budget = context['budget']
    policy = dict(overview_limit=3, max_read_units=budget['max_read_units'],
                  exploration_limit=math.ceil(budget['max_read_units']*budget['exploration_budget_ratio']),
                  exploration_budget_ratio=budget['exploration_budget_ratio'], timeout_seconds=budget['timeout_seconds'])
    policy.update(context.get('execution_policy', {}))
    from learning_research import OVERVIEW
    policy['overview_tools'] = sorted(OVERVIEW)
    policy['counting_rule'] = '概览类工具最先的3次读取使用概览额度；其余资料读取使用总补读额度，并受定向或探索上限约束。watch_video 首次准备和后续查询按每视频单独计次计时，不占补读额度；采样、读图仍计补读。失败调用计数。'
    task = {'task_id':task_id,'task_mode':context['task_mode'],'goal':context['goal'],
            'context':context.get('task_context',{}),'needs':context.get('needs',[]),'video':context['video'],'budget_policy':policy,
            'knowledge_index':context.get('knowledge_index','')}
    role = ('直接回答用户原请求，返回结论、依据和仍缺材料。' if context['task_mode']=='reading' else
            '依据目标和用户评价原文核对材料，返回新信息、评审意见和仍缺材料。')
    if context.get('task_context', {}).get('entry') == 'daily_video_learning':
        role = '''你在每日学习中阅读当前视频，目标依据是视频主题。先看 context.overview 的已采集概览；缺失的基础信息通过工具取得。完整采集材料可用 list_review_materials/read_review_material 按需展开。
先取得章节目录、必要文字材料，并用 watch_video → sample_video_frames → get_frames 查看一次全片稀疏概览，结合字幕理解内容。初次概览最多18帧、两张拼图。短片按实际长度采样。
随后依据理解缺口自主选择读取：有章节时按章节定位；无章节时结合概览和时间戳推定分段并注明。sample_video_frames 可用 start_seconds/end_seconds 生成片段概览；get_frames(kind=frames,count=1) 查看已有单帧；get_frame_at 补看指定时刻和事件前后。所有补读共享当前预算，避免逐段重复扫完整片。
字幕按续读位置展开。评论、楼中楼和弹幕用于理解讨论及反例；需要原公告、动态配图或背景资料时可查 RSS、文章、外部图片与知识库。字幕缺失且画面不能说明口播内容时，如实保留缺口。
形成主要理解后从未读材料中做少量探索，观察是否改变判断。报告说明视频各主要部分讲了什么、关键条件与新信息，引用本轮 read_id 和时间位置，并列出实际未读的内容。稀疏帧分布到全片不等于理解了每个片段；按实际证据描述覆盖。
你的报告交给下游提炼知识；工具轨迹单独保存。保留有价值的信息，不以是否值得发布来删去视频内容。'''
    from knowledge_tools import guidance
    knowledge_guidance = guidance(context.get('knowledge_protocol', 'legacy'))
    protocol = '''直接调用已开放的只读检索工具完成本任务，不派生子代理。任务数据如下：
'''+json.dumps(task,ensure_ascii=False)+'''\n先读取廉价基础概览，再依据缺口选择补读。
'''+knowledge_guidance+''' 
所有MCP资料读取统一填写 _reading：task_id、purpose(targeted/explore)、reason(本次要查什么)、relation(与目标的关系)，可附 prior_observation。
定向须与本任务目标高度相关；探索可以旁支，探索转定向时记录与目标的关联依据。
原生网页读取先调用 declare_native_read，填写 task_id、native_tool="exec"、native_input(完整网页工具调用代码)、purpose、reason、relation。
将返回的 native_input 交给 exec 执行，保留 reading 标识，每个标识对应一次调用；读取或等待后续结果同样先声明。执行器按真实call_id保存结果，不以总结替代原始返回。
按工具返回的 budget_remaining 判断剩余额度。overview_units 与 read_units 分开计数；targeted_units 和 exploration_units 限制各自目的的调用，仍共享 read_units，不增加总额度。定向补读最多18次。
watch_video 的首次准备和后续查询，每个视频最多10次，从首次准备开始最多180秒，仍受任务总时间限制；保持同一视频参数，查看 video_polls 剩余次数和时间。准备未就绪且达到任一上限时停止轮询，标记未就绪，用已取得材料收尾。采样、读图各计一次补读。时间预算覆盖整个任务。
总时间包含读取和收尾。budget_policy.finalization_reserve_seconds 专用于提交停止原因和生成最终报告；300秒任务预留最后60秒，前240秒用于读取。budget_remaining.read_seconds 是可继续读取时间，seconds 是任务总剩余时间。每次追加检索前，结合 read_seconds 和刚才调用耗时判断下一次读取是否来得及；来不及或收到 finalization_required 时停止追加检索，立即调用 finish_reading_task，再输出已有依据支持的结论和仍缺材料。尚有总时间但进入收尾时，stop_reason 使用 cancelled，reason 写明预留时间收尾；不要声明总预算耗尽，也不要继续尝试资料工具。
核心结论形成后，评估尚未展开的评论、其他来源或未覆盖片段，选择少量 explore 检查判断并补充信息；不要把旁支读取标成 targeted。探索转定向时说明新发现与原目标的关联。若不探索，在停止原因中说明跳过探索的依据（例如时间不足、没有可读候选或预期增益低）；无需耗尽预算。
停止前调用 finish_reading_task，填写 task_id、stop_reason(sufficient/budget_exhausted/no_readable_material/cancelled)、reason、conclusion。预算耗尽须与账本一致；收到校验错误后根据实际余额修正停止声明。
图片实际返回像素后才算看过；缺失结果保留缺失状态。最终报告引用本轮read_id，保留来源供主会话核对。
'''+role
    return dict(protocol_version=VERSION,execution_prompt=protocol,budget_policy=policy)
