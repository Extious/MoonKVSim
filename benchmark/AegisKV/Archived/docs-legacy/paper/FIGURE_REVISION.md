# 论文图像修订说明（2026-09-06）

本轮重新设计了正文全部 10 幅图，并恢复用户此前的三联 Motivation。
每幅图明确它回答的问题、数据单位、统计单位与证据边界。论文使用矢量 PDF；
机制图保留原生 Draw.io，定量图保留 Python、SVG、原始绘图输入与来源哈希。
这完成的是当前证据下的图像和稿件修订；研究结论的投稿准备程度见
[SUBMISSION_READINESS.md](SUBMISSION_READINESS.md)。

## 找回的三联 Motivation

旧完整图在 Mooncake：

`/home/comp/zhanzhao/Mooncake/benchmarks/aegiskv/paper/figures/motivation-real-cc-three-panel-submission.pdf`

其 CSV 在同项目 `benchmarks/aegiskv/figures/data/`。原始 trace 则在 sglsim 的归档目录：

`/home/comp/zhanzhao/sglsim/AegisKV/doc/Archived/2026-08-06-pre-kvcache-centric/presentations/presentation/experiments/sglsim_large/traces/cc-traces-weka-062126/traces.jsonl`

该路径是指向 `/tmp/sglsim-cc-traces-weka-062126/traces.jsonl` 的符号链接。
本轮重新解析了目标文件，未修改这些原始资料。
复制来源和逐文件 SHA-256 在 [IMPORT.json](../../experiments/results/paper/data/motivation-real-cc/IMPORT.json)。

新版保持原来的三个论证环节：

1. **观测分布**：每个符合严格共同重叠条件的 workflow 取一个最大并行分支时长差，
   单位为秒，横轴为对数轴；不是 longest/shortest 比值。
2. **具体工作流**：按实际起止时间绘制五个分支，显示到推断 join 的剩余 Slack，
   同一竖线标记 349.5 s。没有用等宽方框替代真实时间尺度。
3. **恢复后果**：历史 AIConfigurator 反事实的重算时间分成“被 Slack 吸收”和
   “暴露为延迟”两部分。A3 吸收约 46.6 s，A4 暴露约 35.9 s。

独立重建结果：393 条会话中 124 个合格 workflow 与旧 CSV 逐项一致；
最大数值差约 `1.82e-12 s`。中位 gap 为 140.611 s，P90 为 1,570.290 s。
五个示例分支的起止、时长、嵌套调用输入块数、Slack 和暴露延迟算术也通过核对。
[RAW_RECONSTRUCTION.json](../../experiments/results/paper/data/motivation-real-cc/RAW_RECONSTRUCTION.json)
记录检查器、原始文件哈希与逐分支结果。

这里有三项不能混写：父子/依赖边由 trace 顺序和时间推断；输入长度来自
64-token hash block 计数，并非重新分词的精确长度；历史重算估计使用
Qwen3-235B-A22B、A100-80GB、TP8/PP4/EP8，**本轮未重跑该延迟模型，也没有
实机校准该反事实**。它不是后文 Qwen3-8B 的实验，更不是原 trace 上真实注入故障。
论文图注和正文均写明这些边界。数据格式说明来自
[公开数据集](https://huggingface.co/datasets/semianalysisai/cc-traces-weka-062126)。

## 全部图像的设计与证据

| 图 | 回答的问题 | 本轮的实质修改 | 证据与限制 |
|---|---|---|---|
| 1 Motivation | 为什么相近恢复工作量可能带来不同 workflow 延迟？ | 恢复历史三联图；ECDF、按时间绘制的分支、吸收/暴露分解共同论证 | 观测 trace + 推断 join + 冻结反事实，三者分开标注 |
| 2 资源代价 | 保护占多少 HBM、搬运成本多大？ | 一/双份 KV 解析曲线与预留后容量线；显示每个实机传输样本及聚合率 | 解析容量不是测量；传输来自 RTX4090 host-staged pilot；单个 load 样本不画虚假置信区间 |
| 3 System Overview | 谁拥有策略、主 KV、备份和复制操作？ | 原生 Store Master 内嵌 Controller；Application、Router、source、standby、DRAM 的所有权边界；独立双路径与单独主 KV | 以当前 Mooncake 源码为准；无 Peer→DRAM destage；caption 区分实机 GBDT 和模拟 ideal CPM |
| 4 Commit / Recovery | 两个 tier 在故障瞬间能恢复哪些 KV？ | chunk 状态时间线、每层 committed prefix、backup→primary 复制三个面板 | 事件先后示意，不是测量时间；明确 PENDING 不可恢复、DRAM abort 与独立主 KV |
| 5 Workload | 实验实际覆盖哪些任务和上下文？ | prompt/workflow ECDF 与带计数的 context bins | 160 workflows / 1,304 calls；最大 86,214 tokens；128K 计数为 0 |
| 6 Healthy cost | 保护的时延和流量开销是多少？ | 配对 WCT 差异和完整 workload 的 TiB；保留全部五个 seed 点与均值/区间 | 区间单位是 admission order，不能把 800 个 workflow 当独立重复 |
| 7 Failure outcomes | 完整工作流是否受益？ | 原始 WCT ECDF、整体/重点 workflow 的 F1−F0 配对对比 | 零基准与不利方向可见；区间跨零，不制造“显著收益” |
| 8 Recovery mechanism | 多恢复 KV 是否必然缩短 workflow？ | 按 token 来源分解、配对 prefix-ready 时间、prefix-ready saving 对 WCT penalty 散点 | 五个预先选定 focus 请求；显示 seed 4 更早恢复却更晚结束的反例，无拟合线 |
| 9 Ablations | Slack、AIMD、LRU 分别改变了什么？ | 整体/重点罚时与健康流量三面板；五个 seed、统一方向 | 流量变化有观测；当前未确定 WCT 收益，不能以流量变化代替时延改进 |
| 10 Sensitivity | 结论是否依赖并发、带宽、批次服务和故障次数？ | 七设置 forest plot；全部种子、均值、95% t 区间、行底色、零线 | 探索性比较，无多重比较校正；两面板分别注明尺度 |

## 从 related works 借鉴了什么

再次查看了本地 Mooncake 第 3 页 Figure 2、GhostServe 第 5 页 Figure 3、
KVFlow 第 2 页 Figure 1 的实际渲染页面：分别借鉴“组件与数据路径”、“内存结构
结合执行时间线”、“具体反例支撑动机”的组织方式。没有复制它们的图形或数值。
更完整的图像组织对照在 [RELATED_FIGURE_REVIEW.md](RELATED_FIGURE_REVIEW.md)。
图的复杂度取决于它需要证明的机制；框和箭头本身不构成实验依据。

## 图文一致性修正

- Algorithm 1 加回实机的校准 margin，并准确表达：任一必要预测缺失时，所有
  active sibling tickets 都失效并置零。原稿只写 CPM 原始 float，遗漏了这一步。
- Algorithm 2 的 ACK、状态和释放都以 `(chunk, tier)` 为单位，避免暗示两层共同提交。
- Store Master 中的 recovery queue 不再误归入 Algorithm 3；AIMD 只更新 HBM 配额。
- 实机 pilot 的 AIMD 周期为 5 s，冻结模拟为 1 s，正文、表格和对齐说明已更正。
- 原生 HBM load 有局部锁和可见性 lease，但 Controller 压力淘汰没有全程读取该 lease；
  模拟 pin 直到 materialization 完成是更强假设。这一未验证竞争窗口已经写入正文。
- 统计输入和 170 次执行未改动；本轮不把重新绘图算作新实验。

## 复现与归档

[render_submission_figures.py](../../experiments/scripts/paper/render_submission_figures.py) 生成定量图；
[build_submission_diagrams.py](../../experiments/scripts/paper/build_submission_diagrams.py) 生成原生 XML、调用
官方 Draw.io exporter，并按 7 inch 合成矢量图；
[verify_motivation_trace.py](../../experiments/scripts/paper/verify_motivation_trace.py) 独立核对旧 Motivation。
所有嵌入图的最小字号至少 10 pt，并有线型、纹理或直接标注支持灰度阅读。

可编辑机制图也复制到 [docs/drawio/paper-figures](../drawio/paper-figures)。
旧版源文件、PDF、review 和下载包保存在
`output/paper-simulation-8b/20260906-figure-revision/pre-revision/`。
