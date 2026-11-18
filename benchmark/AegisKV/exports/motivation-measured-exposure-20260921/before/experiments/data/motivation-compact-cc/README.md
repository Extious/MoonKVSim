# 四分支、约 100 s gap 的 Motivation 实例

当前实例为 `631738ac31321409f3a8de750fd5cd0ea334` 第 20 组，4 个分支，持续时间 60.370 / 151.612 / 132.409 / 129.429 s，gap 91.242 s。该组通过与 Figure 1(a) 相同的时序 fan-in 筛选，但不是所属工作流的最大组（该工作流最大 gap 为 314.383 s），因此不能说它就是 (a) 中某个样本的展开。

`select_motivation_compact_example.py` 检查所有保留组，候选条件为 4–5 个分支、gap 在 100±15 s、最长分支不超过 250 s。每组均选取最接近公共分支执行区间中点的全活跃 LLM 区间，若有前缀超出 128K 则不使用该例。在剩余候选中优先关键分支前缀较长者，以展示恢复暴露；这不是随机故障样本。完整候选比较和固定 trace/逐行 SHA 见 `SELECTION.json`。

故障绝对时刻 75973.1 s，相对 fork 29.452 s，位于全活跃区间 [75972.456,75973.786] s。A2 决定相对 151.618 s 的汇合，Main 在 157.354 s 继续；依赖仅根据时序推断。CSV 和摘录保存全部分支身份、原始活跃请求与 hash IDs。

成本口径保持 Qwen3-14B、AIConfigurator HYBRID、A100-SXM、BF16、batch 1、TP1；查询精确前缀 M 加假设的 64-token 尾部。`recovery-costs.json` 独立于 Figure 2 的已冻结估计矩阵。A1–A4 重算为 35.207 / 32.180 / 36.706 / 38.922 s，Slack 为 91.248 / 0 / 19.096 / 21.915 s，WCT loss 为 0 / 32.180 / 17.610 / 17.007 s。四行是四个独立反事实，不应相加为一次故障损失。

```sh
.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/select_motivation_compact_example.py --trace /home/comp/zhanzhao/sglsim/AegisKV/doc/Archived/2026-08-06-pre-kvcache-centric/presentations/presentation/experiments/sglsim_large/traces/cc-traces-weka-062126/traces.materialized.jsonl
MPLCONFIGDIR=/tmp/aegiskv-motivation-mpl HF_HUB_OFFLINE=1 /home/comp/zhanzhao/aiconfigurator/.venv/bin/python benchmark/AegisKV/experiments/data/motivation-compact-cc/estimate_costs.py
.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/render_motivation_row.py --only figure1
.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/build_motivation_workflow.py
```

本目录固定引用旧 `reuse-aiconfigurator-a100` 的估计器和数据哈希。当前 Figure 2 已改用独立的 `reuse-aiconfigurator-architecture-h100` 覆盖大规模、MoE、DSA，并统一采用 H100；本实例仍为 A100，文稿已分别标明，不能声称两图配置相同。只有变更本目录实际引用的源文件后，才需重跑 `estimate_costs.py`。旧十支、精确中位数和最短实例数据均保留。
