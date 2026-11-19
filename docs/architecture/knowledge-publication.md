# 知识条目与索引的同步发布

知识维护 MCP 在现有增删改查接口上发布条目、词法索引、正文向量和图谱关系。同一读取进程在下一次查询时加载新版本，无需重启。

## 配置入口

维护进程仍使用 `QQ_ENTRY_STORE` 和 `QQ_ENTRY_COLLECTIONS` 绑定条目库与写入范围。新增 `--retrieval-profile` 参数复用读取端的索引、编码器和检索参数；在该 JSON 中加入：

```json
{
  "publication": {
    "root": "generations",
    "reviewer": {
      "command": ["codex"],
      "model": "gpt-6-astra",
      "effort": "medium",
      "timeout_seconds": 300,
      "max_input_characters": 32000
    }
  }
}
```

`root` 相对 profile 文件解析。维护端需要可实际编码正文的 ONNX 编码器，冻结 Query 编码只用于回放。

调用入口为 `src/runtime/knowledge_entries_mcp.py --retrieval-profile PROFILE`。机器人读取端继续使用同一个条目库和原检索 profile。写权限仍由维护进程的 collection 配置限定；普通机器人仅获得读取工具。

维护端与机器人读取端都从既有 `QQ_KNOWLEDGE_ROOT/catalog.json` 加载正式文档用途。维护端应配置与读取端相同的知识库根目录；正式条目的 `catalog-snapshot:formal:<文档键>` 来源对应目录中的文档键。表达查询据此判断用途，信息查询仍可检索事实条目。缺少目录或对应的表达用途时，正式条目不会进入表达候选。此处复用现有配置，不另设目录环境变量。

## 发布与读取

1. EntryStore 在单写锁内校验条目版本和权限，生成待发布条目快照。
2. IndexPublisher 复用未变化的节点、切片和向量，对新增或修订内容生成词法、正文向量及正文锚点、含义、用法、情景、条件、风格字段节点。
3. 候选提名沿用索引记录的 K。审边会话读取候选两端完整正文，按现有包含／局部重叠定义返回方向、短理由和逐字证据；缺审、证据错误、超时或材料不足会阻止发布。
4. 重开索引检查形状和内容后，一次原子替换写入条目及 `retrieval_publication` 引用。维护回执返回 `publication.status=published`、generation、index_id 和变更条目 ID。
5. 读取端从同一条目快照选择对应索引。修订后的旧节点与入边、出边退出；撤回和合并后的失效来源不进入检索。

没有可证关系的条目仍可发布，审边结果明确记为 none 或 equivalent；不把缺审当作没有关系。新节点会进入表达图谱或作为事实桥接节点，最终表达候选继续遵循既有用途分类。正式知识的用途来自文档目录；学习条目沿用 kind／surface_form 规则。

## 回执和失败

每次准备使用独立 generation 目录，保存前一快照、待发布快照、候选提名、审边输入与结果、编码记录和索引。`receipt.json` 记录准备成功或失败；是否提交以条目库中的 generation 引用为准。已确认的准备失败不会替换有效条目或索引。客户端超时或丢失回执不证明准备失败。

已启用同步发布的条目库拒绝未配置发布器的旧写入入口，避免绕过索引生成。读取权限和群资料范围不因发布改变。

审边是独立模型调用，默认 Astra medium、正常速度，每次最长 300 秒，不自动重试。写锁在准备期间保留；其他读取继续，竞争写入返回 store_busy。旧 generation 保留用于核验和回滚，启用前应为保留策略与磁盘空间单独制定配置。

维护 MCP 的业务失败返回 `isError=true`，文本与结构化结果给出相同的错误、阶段和恢复方法。写入回执按以下方式使用：

| write_outcome | 如何核验或继续 |
|---|---|
| published | 按 publication 中的 generation 和 index_id 核对有效快照。 |
| saved | 条目已保存，此入口没有同步索引发布器。 |
| unchanged | 内容未变化，沿用原修订；没有重新准备索引。仅来源变化仍产生真实修订，沿用已有发布流程。 |
| not_committed | 明确在提交前拒绝。锁占用等现有写入结束；修订冲突看 current_revision 和 status；编码器或审边失败由宿主检查构建记录。 |
| unknown 或没有回执 | 创建不幂等，不自动重发。先按标题定位，再用维护历史读取核对完整正文、集合、来源及修订。无法唯一核对时由宿主查提交记录。 |

整次审边请求默认以 32,000 个 Unicode 码点为观察值，超过只记录，不截断、不拒绝；每个方向的输出理由最多 30 个码点（含空格、标点），超长只修理由，不删正文或逐字引文。语义检索 query 的 40 个码点是参数硬上限。当前正文按页读取：超过 2,400 自动缩至 2,400，可用 next_offset 续读；维护历史正文一次完整返回。

维护端可查本范围内已登记但尚未被活跃条目采用的 Tag；历史零引用 Tag 如无可核验的登记范围，由宿主核对，机器人读取端仍仅返回活跃条目所用 Tag。撤回及合并后的旧引用只返回恢复元数据，不返回正文。

## 学习发布接线

每日学习的 `knowledge_publication.retrieval_profile` 指向同一检索 profile。已有 `publish_pending → publish_learning → prepare_update → publish_candidate` 路径保持，最终提交改用 `EntryStore.replace_snapshot()`，与维护 MCP 共用写锁、索引生成器和原子发布。

`prepare_update` 在私有候选快照中复用原 CRUD，仅生成待审变更，不逐条发布索引。`publish_candidate` 校验批准的候选哈希及有效库基线，在写锁内为整批变更生成一次索引后发布。回执区分 `candidate_sha256`（获批候选）与 `after_sha256`（加入索引引用后的实际库），并返回 `publication` 代次。重复发布复用成功回执；基线已变化时要求重新准备候选。生成失败不改变有效库，回滚恢复原快照及其中的索引引用。
