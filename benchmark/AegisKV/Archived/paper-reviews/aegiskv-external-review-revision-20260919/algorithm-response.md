# 算法与系统设计修订回执

**状态：本轮范围已完成，停止编辑。** 已吸收三家合并清单、ChatGPT 18 项原评审、Claude/Grok 留档及勘误，并完成协调任务最后两项终检修正。等待状态已结束，动机任务完成后已统一构建共享主 PDF。

## 最终交付与验证

- 共享稿：`/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/main.pdf`。
- 固定交付：`/home/comp/zhanzhao/MoonKVSim/output/pdf/aegiskv-external-review-revision-20260919/main.pdf`。
- SHA-256：`b07242efc2f1b5bb7d6cacbfe49f166eff6bad67ccd3cee0bcbb75331abe986d`；12 页，662,804 bytes。两个副本逐字节一致。
- 27 个引用全部解析，无重复 BibTeX key、未定义引用或 Overfull；保留 9 项 Underfull 排版提示，未观察到对应裁切。完整日志和机器核对在 FINAL_HANDOFF.md、REVISION_VALIDATION.json。
- 最终 Figure 3/4/5 普通标签最小 10.05080 / 10.43981 / 10.03201 PDF pt；对应页 5/6/9。检查实际页面和彩色/灰度图，原生图像与数字未变。Figure 4 使用本轮明确允许的等比双栏插入；Figure 3(b) 改为 Selected sparse releases。其他绘图约束保持原任务版本。
- 9 项深度评分算术检查及 12 项边界/小 DAG 构造检查通过。它们是 CPU 构造验证，不是实测、校准、实现正确性或性能证明。
- main.tex 未改；references.bib 未改；动机任务在其 bib 中新增的条目已整合，无重复键。冻结送审 PDF SHA 仍为 `32aa352a81387c4cb982603742e679b7fcb9f83a22383eaa72f9c78299a89a52`。
- 没有启动 GPU/大实验、训练新预测器、修改冻结目录或提交 Git。

## 逐项处置

“接纳”表示完成本轮文字/契约/低成本核对；不表示未来实验已完成。编号采用 review-summary.md 的 A/R 对照。

| 项目 | 处置 | 已完成修改 | 仍缺的实证 |
|---|---|---|---|
| A01/R01；C07/19、G01 | 接纳 | 删除摘要显著 WCT 收益/可忽略开销承诺；摘要与 Scope 使用“measured forward latency and assumed transfer bandwidth”，不声称整个流水线已校准 | 端到端 WCT 与正常开销 |
| A02/R02；C07、G06 | 接纳合同 | source epoch/fencing、持久日志先于 ACK、token 去重；对象版本与依赖闭包 manifest；跨层/TP shard/selector 的公共合法 frontier；独立 Peer/DRAM 提交不能直接推进全局 frontier | 各提交点故障、日志/目录竞态 |
| A03/R03；C07/08、G06 | 接纳边界 | 批量 replay 需原生 selector 与状态演进等价；否则逐 token；原生 prefill gate 和未解决数值诊断均不当作正确性证据 | 每个后端、窗口/压缩/indexer 状态与数值容差对照 |
| A04/R04；C13/14、G05 | 接纳 | 请求引用阻止其他请求抢占；owner 可更新热集；Adapter 可降级受保护副本。DRAM commit → 目录重定向并关闭旧 generation 新 lease → drain → free 后归还容量 | 长 decode、共享对象、并发缩容与 I/O 竞态 |
| A05/R05；C03/12、G05/06 | 接纳合同 | 有限 DRAM 账本、reserve/commit、共享引用、LRU 与 lease-safe 回收；无完整 backing 用旧 frontier 或 R，Peer 失败不保证 D 成功；最终算法 2 第 4 行显式仅 D/P 请求新 DRAM 备份 | DRAM 满、长期积压、部分提交与生命周期压力 |
| A06/R06；C06/15、G09 | 部分接纳 | 保留局部 heuristic，明确不等于 WCT；同源共同事件采样；正文保留两关键分支反例，CPU 有限小 DAG oracle 显示 6 秒构造 regret | 真实 DAG、同源故障/队列/批处理共同作用下的 regret |
| A07/R07；C09、G15 | 动机主责已整合 | 不在本任务重复改写 §2；整合动机的近邻定位和引用 | 同后端同资源消融 |
| A08/R08；C10/17、G02 | 接纳合同 | 明确 orchestrator 的完整 DAG 声明及失效条件；未知结构/映射回退零 Slack；workflow/时间隔离，秒误差、false-safe、路径排序、fallback 比例与 regret 指标 | GBDT 校准、漂移和目标 workload 覆盖 |
| A09/R09；C11、G04/10 | 接纳 | 预绑定不预留计算/工作集；目标空间、前台、队列、链路/故障域进入 profile；不可行时排队或重新核对路由，远端 Peer 不视为本地 | 目标拥塞、其他 DP 空闲及同时重试 |
| A10/R10；C04、G04 | 接纳合同 | WAIT_SPACE/WAIT_DATA/READY/RUNNING；先预留激活/传输空间；TP 各 rank 同 batch/layer/collective 顺序；合法边界拆批，否则整批等待计费；正资源份额及锁顺序 | 后端集成、batch interference、非抢占 DMA、死锁/饥饿 |
| A11/R11；C05/06、G03/09 | 接纳有效部分 | 不假设 R_D<R_R；相等优先 R，Peer 失败用便宜可行路；公式单位、前台 cohort/H、条件样本、区间切换、未知 profile 与零风险行为明确。概率改为 pi_r，避免与目标 DP p_r 重名 | 真实 A/R profile、风险先验、切换与零风险场景 |
| A12/R12；C01/02、G01 | 动机主责已整合 | 依赖代理、过滤和总体意义见 motivation-response.md | 真依赖和故障时刻分布 |
| A13/R13；C03/04、G07 | 动机主责已整合 | 采用优化 DRAM 对照，分开 R→D 与 D→P；算法侧纳入资源共享和成本 | 净收益/前台税/真实风险 break-even |
| A14/R14；C08/16、G08/11 | 接纳边界 | K 是每请求每层已提交 Peer 集合大小；fixed/fraction quota 单独声明；短于 512 步用已有观测，零观测 mandatory+recency；mandatory 超额显式增配或拒绝该层，不能静默截断 | 工具返回漂移、真实 Agent trace、近 dense union 负例 |
| A15/R15；C08/18、G13 | 接纳 | 前 L 层是受限候选族；Figure 5 解释 whole-forward median/32、A100 PCIe、假设 6.25 GB/s、h 和 147.4921875 MiB 载荷；明确 38.685464 ms 冷搬运债务与 tail-ready 终点 | 非前缀层放置对照、后续 TPOT、辅助状态实际字节 |
| A16/R16；C12/13/14/16、G03/05 | 接纳合同 | Z 保持系统配置；队列字节/操作数有界、合并未启动旧计划、保留在途依赖、无法预留则跳过并报告 lag；20% 仅流量 cap；注入频率不作为风险先验 | 常态开销、三个时钟耦合、积压与控制稳定性 |
| A17/R17；C18、G13/14 | 本范围接纳 | Figure 4 从约 4.97 pt 改为等比双栏 10.44 pt；最终 Figure 3/4/5 标签和彩灰版已核对；Figure 1/2 由动机处理 | 不据此宣称整篇完成投稿合规 |
| A18/R18；C19、G12/16 | 接纳必要修正 | 算法 2 Output 包含 H；对象/owner/lifecycle 表进入支持契约；正文区分请求引用与 I/O lease；3(b) 子标题改 selected releases，未扩张全文章节 | 后续实现/评估章节仍不在本轮范围 |

## 不采纳的推断和改法

- C05 的“bytes 加 seconds”指控不成立：A 明确为前台请求延迟变化，和风险加权延迟同单位；接纳接口细化，不接受错误量纲诊断。
- 不将 stable ID 等同 FCFS，不为了外部评审偏好改成 Slack 串行恢复；独立 retry 也不等于各 TP rank 任意乱序执行。
- 不把独立 Peer/DRAM commit 写成强制先后复制；安全退出某个 Peer 位置时才要求先有有效 DRAM backing。
- 不将非 Peer 块统一判为需要重算；已提交 DRAM 可以按需取，只有覆盖/依赖缺失才进入相应重算路径。
- 工具交接结束的 LLM 请求会释放自己的引用；“工具等待一直 pin 住该请求”不是当前语义。有效压力案例为活跃长 decode、共享引用和在途 I/O。
- 不要求未来随机 token 跨执行调度位级相同；已知 token 日志、声明数值契约和原生 selector 状态等价性仍必须验证。
- 不预设收益 ≥10%、曲线必须交叉、某基线必须失败；保留零/负收益。也不根据章节预览断言整个仓库没有实现或原生测量。
- 不匆忙重写全局优化器或增加全论文缺失章节。局部启发式的可检查反例和 oracle 合同已加入。

## 主要修改文件

论文根目录：`/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper`。

- sections/abstract.tex、system_overview.tex、workflow_protection.tex、design_insights.tex。
- sections/parallel_recovery.tex、kv_placement.tex、kv_runtime.tex、capacity_allocation.tex、design_discussion.tex。
- draft/abstract.md、draft/system_design.md、draft/supporting/depth-policy-contract-20260919.md。
- sections/README.md、figures/system-overview-v11.md 为相关说明。Figure 3/4/5 原生图像和数值文件保持冻结版本字节一致。
- 算术参考：`/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/scripts/paper/check_depth_policy_contract.py`、`check_policy_boundary_cases.py`。
- 初始副本在 before/；范围 diff 和哈希在 ALGORITHM_SOURCE_DIFF.patch、ALGORITHM_SOURCE_FILES.json。

## 验证性质与剩余工作

这次完成的是论文契约、伪代码、可复算规则和最终排版。评分参考不执行 admission，CPU DAG 反例不模拟 GPU/网络；未实现/验证并发 lease 协议、native sparse recovery 等价性、预测校准或端到端 WCT。可复现实证清单见 supporting/depth-policy-contract-20260919.md 和三家 review-summary.md。已经停止扩展实验和算法。

科研绘图经验已按用户持续授权新增一条、未改旧记忆：`20260919T052243129083Z-ffb5edf893`。记录以本轮首个最终预览的图 4 尺寸为证据；最后仅补算法 D/P guard，图形字节和测得字号均未变化。
