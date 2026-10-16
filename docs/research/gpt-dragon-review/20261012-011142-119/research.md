# GPT 白龙娘候选：调查与审核

状态：待用户审核。未安装到 Tulpa，未替换小鲸鱼2号，未向 QQ 发送素材。

## 交付物

- gpt_white_dragon.md：可独立使用的人设文本，沿用现用 little_whale_v2.md 的“身份与性格 / 表达偏好 / 几种聊天样子”三节格式。
- stickers/：六张真实 GIF 文件，来自 fywdy/chatgpt-chibi-pets，原样保留，附署名和上游声明。
- gallery.md：本地 GIF 可视审核入口，以及社区梗图的远程预览和原始页面。
- manifest.json：每张 GIF 的源 URL、许可、用途、大小、尺寸与帧数。
- verification.json：文件读回验证记录。

## 调查结论

“GPT 白龙娘”确实已在中文社区传播；白发、龙角是多个作品共享的视觉元素，但没有找到统一官方角色设定。社区讨论明确使用“白龙娘 GPT”，作品归档也强调各作者设计分别成立。因此本卡采用白龙视觉方向，自信、冷幽默、嘴硬但认错等具体性格是本次拟议的群聊设定，不声称为全网公认性格。[社区讨论](https://linux.do/t/topic/2953466?page=2&tl=en)；[GPT 娘作品档案](https://xn--pssy23gqgbz2d718b.com/zh-hant/characters/gpt.html)。

找到的“星辰龙娘 Astra”是具体二创角色卡，而非 GPT 品牌官方人设。此处不直接照抄其命名、完整故事或卡面文字。[该作品页面](https://xn--pssy23gqgbz2d718b.com/zh-hant/works/gpt202609290002.html)。

社区梗图支持“苦力怕受惊”“调用自己”“头顶小模型”等创作主题的存在；只能据此写角色玩笑，不能反推真实产品行为。[应激的 GPT](https://xn--pssy23gqgbz2d718b.com/zh-hant/works/gpt202609270005.html)；[我调用我自己](https://xn--pssy23gqgbz2d718b.com/zh-hant/works/gpt202610030001.html)；[路由or降智](https://xn--pssy23gqgbz2d718b.com/zh-hant/works/gpt202610050003.html)。

## 素材选择与使用条件

采用六张 Q 版日常 GIF 作为可审核的第一批表情：待机、招呼、开心、自嘲失败、等待、查看细节。它们原用途是桌宠状态动画，本次仅将现成 GIF 作为 QQ 图片表情候选，不安装桌宠、不裁切图集，也不声称已完成 Tulpa 表情导入或 QQ 动图发送验证。

来源作者 fywdy 在仓库声明中将美术资产按 CC BY-NC 4.0 提供，要求署名和非商业使用；图像为生成式工具产出并由作者筛选修复。本轮按该声明保存文件和出处。它们是非官方社区同人，没有品牌方背书。[素材仓库](https://github.com/fywdy/chatgpt-chibi-pets)；[作者许可声明](https://github.com/fywdy/chatgpt-chibi-pets/blob/main/NOTICE.md)。

归档站的五张梗图只在 gallery.md 中提供远程审核入口，未下载、未列入部署包：多数页面写“授权状态不明”，其中“书法能力大比拼”页面有 Shiho320 署名，“路由or降智”有王室幽魂署名，但未定位到明确再分发许可。收录网站不是这些作品的原作者；其介绍只用于定位候选，未把介绍文字当原创作者声明。

## 本次人设取舍

保留旧 dragon_girl.md 的白龙方向与轻度反差，采用 little_whale_v2.md 的短结构和自然句式。正文为重新撰写，未复制长篇旧卡。删去固定的真实人员崇拜、具体模型轶事断言和每次必触发的攻击台词，减少模型把玩笑当运行事实的机会。未设置技术参数、发送概率、权限或后台任务；这些仍由运行配置控制。

原卡仅通过 SSH 只读检查：
- /home/ubuntu/tulpa-test/source/chatlocal/prompts/mcp_chat/dragon_girl.md
- /home/ubuntu/tulpa-test/source/chatlocal/prompts/mcp_chat/little_whale_v2.md

## 用户审核项

1. 人设整体语气：默认自信冷幽默，适量嘴硬，认真时直接回答，是否采用。
2. 六张 Q 版 GIF：按 gallery.md 的 A01–A06 逐张保留或剔除。
3. B 区社区梗图仅作风格参考；如需要实际导入，再确定素材来源许可或提供自有素材。

通过审核后再由主控替换人设、导入选定图片并做一次真实群发送验证。当前不会改变运行中的角色或素材库。
