# 黑流树海节点候选工具

`predict_blackforest_nodes(image_path)` 读取宿主已有截图，返回地图模板、节点识别、未知节点候选及耗时。工具先从截图估计网格规模，再匹配对应楼层的模板，调用者只传图片绝对路径。规模没有对应楼层或该层模板不可靠时，复用已检测节点回退至1–5层匹配；跨楼层可靠候选得分差小于0.02时返回未确定，不要求模型猜层数。结果是可行候选集合，没有概率和路线推荐。

## 外部引擎

引擎为 https://github.com/ega0123/hlsh-helper ，本项目不打包其源码与素材。已验证提交为 `b81965ba78918d8d6effb0e5006dc3c9b2e617c9`。其复用许可尚未明确，复制或分发前需核清。

单独检出该提交，并创建 Python 环境。无界面识别所需依赖为 `opencv-python-headless==4.12.0.88`、`numpy>=2.0,<2.3`、`networkx==3.5`、`Pillow==12.2.0`。本地验证使用 Python 3.12；Linux 运行需另行验收。

## 配置

复制 `config/examples/blackforest-nodes.json` 至实例私有配置目录，填入外部仓库和 Python 的绝对路径。默认超时30秒，允许配置为大于0且不超过180秒；超时终止本次识别并返回错误，不自动重试。

MCP 启动：

```text
python /absolute/release/src/runtime/blackforest_nodes.py --config /absolute/private/blackforest-nodes.json
```

工具配置示例见 `config/examples/blackforest-tool-profile.json`。现有机器人新增能力时，将该服务合入现有配置档，保留其他服务，再按 [配置应用流程](bot-configuration.md) 发布。截图需先由现有图片链路保存到此 MCP 宿主可访问的位置；远程图片URL、附件ID不能直接作为文件路径。

## 结果

成功返回 `success`、`template`、`node_types`、`unknown_mystery_nodes`、`predictions`、`elapsed_seconds`、`prediction_kind=candidate_set`；另返回 `detected_grid`、`matched_floors`、`floor_source`、`floor_candidates` 与 `fixed_nodes`。固定节点分别记录 `resolved_type`、`basis=fixed_template`、`visible_type`，隐藏后的未知图标不覆盖模板固定类型。模型使用候选解释可能性，不把识别置信度当成节点生成概率。识别失败、参数错误、引擎失败与超时返回 MCP `isError`；下次调用可继续。

本工具只读取截图并执行外部识别程序，不操作游戏、不发送群消息。

网格规模按列×行映射：1层5×3，2层5×4，3层7×5，4层8×5，5层10×5（部分模板仅占9列）。截图规模检测依赖近似等间距的横纵节点；裁切、遮挡及界面圆形元素可能使规模估计不完整。适配层复用已匹配结果，依赖上述固定引擎版本的内部接口。

## 图片输出

成功识别同时返回 MCP PNG 图片块与结构化 JSON。原截图标注节点编号，右侧逐项列出候选；固定节点绿色实线、多候选黄色虚线、唯一候选蓝色实线、未确定灰色虚线。候选并列展示，不附加概率。`image_path` 为宿主生成文件，`node_positions` 使用原截图像素坐标，`annotation_nodes` 保留图片标注语义。

每次生成独立时间戳及随机后缀 PNG，不覆盖旧图。配置 `output_directory` 指定输出目录，默认系统临时目录下的 blackforest-results；可配置 `font_path` 指向中文字体。自动查找 Windows 微软雅黑或 Linux Noto Sans CJK，未找到时返回字体错误。部署 Linux 前需安装中文字体或指定已有字体路径。
