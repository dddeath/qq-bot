# 主控专用群文件工具

仅 QQ `1000000004` 可在群 `2000000001` 请求列出、下载或上传群文件，单文件最多 **16 MiB（16,777,216 字节）**。工具从 Tulpa 已交付事件读取原始发送者、群、会话和时间；模型传入的昵称、引用和自称不作为身份凭据。请求有效期 30 分钟，上传和下载分别要求原消息包含“上传”和“下载”。

## 可用工具

- `list_group_files(session_id, event_id, folder_id="")`：列出群根目录或子目录。
- `download_group_file(session_id, event_id, file_id, folder_id="")`：下载本群已列出的文件，返回 `artifact_id`。
- `list_group_upload_assets(session_id, event_id)`：列出本群下载文件、专用 outbox 和当前聊天线程生成图片。
- `upload_group_file(session_id, event_id, artifact_id)`：上传已登记文件；重复请求返回原回执，未知结果不自动重试。

上传前读取最多上限加一字节并冻结交给 QQ 的内容；下载同时检查元数据、响应长度及实际读取字节数，超限中止并清除临时文件。下载内容不自动执行。上传仅接受登记编号，未开放任意服务器路径。

## 服务器路径

- 服务：`/home/ubuntu/tulpa-test/runtime/group_files_mcp.py`
- 权限配置：`/home/ubuntu/tulpa-test/runtime/group-files.json`
- 下载及上传回执：`/home/ubuntu/tulpa-test/group-files/1000000011_group_2000000001/`
- 主控放置待上传文件：`/home/ubuntu/tulpa-test/group-file-outbox/2000000001/`

服务作为 Codex stdio MCP 运行，独立于 Tulpa 进程。原生操作使用 [NapCat 群文件接口](https://napneko.github.io/onebot/api)。当前提供文件传输，不附带通用文档解析或任意文件生成工具。

## 验证

运行 `python tulpa-runtime/verify-group-files.py`；每次在 `.local/group-files/verify-<UTC时间>-<随机后缀>/` 保存命令、输出和退出状态。

7 项离线测试覆盖：主控身份与群范围；引用冒充、未交付和过期消息；明确上传请求；下载实际超限；上传 16 MiB 边界及路径拒绝；未知上传幂等；受限 outbox 导入。QQ API 与下载流使用外部边界替身，真实群文件传输需另行验收。

部署证据：`/home/ubuntu/tulpa-test/evidence/group-files-deploy-20261012T124255.685149Z/`。MCP 握手已发现四个工具，未授权请求已实际拒绝。服务器两轮独立测试通过，前轮证据保持不变。

## 回滚

服务器执行 `python3 /home/ubuntu/tulpa-test/evidence/group-files-deploy-20261012T124255.685149Z/rollback.py` 检查；加 `--apply` 暂停当前聊天并恢复旧工具配置与聊天规则。已下载文件、QQ 已发生的上传和历史证据保留。恢复聊天由主控执行。
