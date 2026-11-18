# AegisKV：三联 Motivation 与全篇图像修订

> 当前算法 2/3 已修订为 revision 3。本文原有测试、构建/交付与实验数据是旧版记录；最新范围见 [修订说明](ALGORITHM_REVISION_V3.md) 和 [发布状态](REVISION_STATUS.json)。旧 PASS 不覆盖当前 PDF 或新算法的运行性能。

2026-09-06 修订版。论文为 **13 页（12 页正文 + 1 页参考文献）**，
包含 **10 幅彩色矢量图、3 个完整算法、17 项参考文献**。
Motivation 恢复为历史三联图，原始 393 条会话中的 124 个合格 workflow 已独立重建核对。
System Overview、提交/恢复机制、实现对齐、完整实验与实机小试验均已纳入。
这是现有证据下的完整修订稿；不能把格式/图像检查通过解释为研究已具备高录用概率。

- [完整论文 PDF](../../paper/main.pdf)
- [恢复的三联 Motivation](../../paper/figures/motivation-real-cc.pdf)、[逐图修订说明](FIGURE_REVISION.md)
- [投稿准备度与尚缺的研究证据](SUBMISSION_READINESS.md)
- [Draw.io 机制图目录](../drawio/paper-figures)
- [LaTeX 与绘图源码包](../../experiments/results/paper/delivery/aegiskv-aligned-paper-source.zip)
- [可编辑图件包：Draw.io / SVG / PDF / PNG](../../experiments/results/paper/delivery/aegiskv-aligned-editable-figures.zip)
- [冻结模拟代码、工作负载与参考源码包](../../experiments/results/paper/delivery/aegiskv-aligned-simulation-source.tar.gz)
- [实现对齐说明](MOONCAKE_ALIGNMENT.md)、[相关论文图像组织对照](RELATED_FIGURE_REVIEW.md)
- [完成报告](COMPLETION_REPORT.md)、[复现步骤](REPRODUCE.md)
- [交付检查](../../experiments/results/paper/data/delivery-checks.json)、[源码包独立构建检查](../../experiments/results/paper/delivery/source-build-check.json)

本轮复用已验收的 170 次完整执行，每次 160 个 workflow、1,304 个请求，
五个 admission seeds 配对。本轮没有新运行实验；原始执行和统计值不变。
所有执行均经过原始事件重新加载与独立审计。旧 200 次实验和第一版对齐尝试未混入。


结果没有证明稳定的整体优势：full 相对 DRAM-only 的整体平均故障罚时差为
**+0.031571 s，95% CI [-0.159076, +0.222218] s**；健康期保护流量增加约
**91.8%**。消融及七点敏感性的整体/重点 workflow 区间均包含零。
[统计与来源绑定](../../experiments/results/paper/data/aligned-statistics.json)保留了全部种子值及重点 workflow 时间线。

模型是 `mooncake_prompt_v1` 的 prompt 保护投影，仍采用理想时长 CPM 和未校准的
A100 服务参数；不声称完整 vLLM 仿真或实机时延一致。实机 4090 小试验单独呈现，
full 的 batch 时间约慢 0.46%，不作为性能提升证据。128K 桶为空。

约 25.70 GiB 的压缩原始事件保留在
`output/paper-simulation-8b/20260906-alignment/campaign-v2/runs/`，未放入小型下载包；
`ACCEPTANCE.json` 记录每个原始文件的哈希。旧稿完整保存在 [archive/legacy-paper/](archive/legacy-paper/)。
本目录保留的旧 `*_AUDIT.md` 与 `FIGURE_METHODS.md` 已明确标记为历史记录。
