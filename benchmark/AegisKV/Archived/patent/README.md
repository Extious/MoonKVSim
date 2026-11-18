# AegisKV 专利材料与审计

专利原件、条款转录、实现证据映射、来源记录和专用审计工具统一放在本目录。

**本次专利定稿入口（2026-09-09）：** [AegisKV 专利交底书 final-version](AegisKV专利交底书-final-version.docx)。
按本次截止安排，以这份交底书为基准收尾，采用其中的 SlackLandlord 租值管理、
Peer-HBM / DRAM 独立准入和 HBMQuotaAIMD。定稿范围限于必要的文字、符号和图文一致性修正；
新讨论的统一分层转存和恢复收益模型留作后续研究。

**实例一、二的最新批注审阅入口（2026-09-10）：**
[实例一二批注版 Word](AegisKV专利交底书-实例一二批注版.docx)。
共 20 条原生 Word 批注（实例一 9 条、实例二 11 条），提供对应段落、公式、伪代码及附图的更新建议；
批注作者统一为 `zhaozhan`。**附图 2、附图 3 及其图注已更新到批注版中**；
其余正文建议保留为批注，原始 `final-version` 文件不变。
[新流程图与可编辑源](figures/instances-1-2/README.md) 保存在本专利目录下。
2026-09-10 按算法三源图精简：附图 2 仅计算 Slack 到 G/P 的映射，附图 3 集中处理租值键决策；
批注采用直接修改指令，不带“建议更新”“已更新”等状态前缀。
租金规则按同日后续讨论调整为所有备份持续收租：候选 x 以试算起点 L′ 建键，已有块保留原 H；
Q 只控制淘汰资格，成为尾块或解除保护不重建 H。更新位于批注和配套附图，原件及实现契约仍保留其原版本。
本轮使用用户手工编辑的五步附图 3 原样导出，实例二批注和伪代码按①—⑤同步；
传输完成与失败处理等细节保留在批注中。
[核对记录](reviews/instances-1-2-20260909/AUDIT.json)、
[批注文本](reviews/instances-1-2-20260909/COMMENTS_EXTRACT.txt) 和生成材料保存在同一审阅目录。

**其他技术方案参考：** [Revision 3 技术交底](ALGORITHMS_2_3_REVISION.md) 与
[可编辑 Word 补充交底](AegisKV-算法2-3修订技术交底-v3.docx) 是另一套算法设计，
取消逐块 credit 和 AIMD，加入共享前缀组准入、额度内 staging、释放 ACK 账本和前台约束控制。
它们不作为本次定稿的替换稿或默认合并附件。
[验证记录](../../experiments/results/algorithm-revision-v3/VALIDATION.json) 区分参考实现、旧契约回归及实机证据。
下面的原件/27 条契约表描述上述 final-version 交底书，不能作为 revision 3 的实现映射。

| 文件 | 用途 |
|---|---|
| [专利交底书](AegisKV专利交底书-final-version.docx) | 本次定稿基准；原始设计输入，保留导入时的文件内容与 SHA-256 |
| [patent-contract.yaml](patent-contract.yaml) | 专利条款、原文位置、代码 owner 与测试 ID 的机器转录 |
| [runtime-clause-evidence.json](runtime-clause-evidence.json) | 条款对应的实现文件、测试与证据范围 |
| [SOURCE_MANIFEST.json](SOURCE_MANIFEST.json) | 原件的来源项目、版本、导入路径与哈希 |
| [SHA256SUMS](SHA256SUMS) | 专利原件、条款转录、来源清单和转录审计脚本的校验值 |
| [audit_patent_contract.py](audit_patent_contract.py) | 检查条款完整性、DOCX 结构、来源与哈希 |
| [audit_aegiskv_runtime_contract.py](audit_aegiskv_runtime_contract.py) | 检查 27 条条款的实现/测试映射及证据范围 |

从项目根目录执行：

```bash
uv run python benchmark/AegisKV/docs/patent/audit_patent_contract.py --json
PYTHONPATH=python uv run python benchmark/AegisKV/docs/patent/audit_aegiskv_runtime_contract.py
sha256sum --strict -c benchmark/AegisKV/docs/patent/SHA256SUMS
```

对应回归测试沿用项目测试目录：

```bash
PYTHONPATH=python uv run python -m pytest -q \
  tests/unit/aegiskv/test_patent_contract.py \
  tests/aegiskv/test_runtime_clause_evidence.py
```

本目录保留专利输入的历史转录状态；`manual_review: pending` 和证据等级不能因
目录整理而升级。当前 Mooncake / MoonKVSim 实现差异见
[三方设计实现对比](../../../../docs/development/mooncake-aegiskv-three-way-design-implementation.md)，
论文使用的实现投影见[Mooncake 对齐说明](../paper/MOONCAKE_ALIGNMENT.md)。
