# 当前采用：三模型 32K / 512-Query 对照

根据用户 2026-09-21 的选择，采用 NOSA-8B、NSA-8B、MiniCPM4.1-8B 原有结果，本次整理为只展示 512-Query 窗口的图像，未新增 GPU 运行。

| 模型 | Top 10% | Top 20% | Top 40% |
|---|---:|---:|---:|
| NOSA-8B | 51.75% | 87.64% | 99.31% |
| NSA-8B | 48.08% | 74.76% | 94.96% |
| MiniCPM4.1-8B | 34.55% | 56.54% | 83.01% |

![访问集中度](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/exports/kv-access-concentration-32k-512q-20260921/access-concentration.png)

“32K”沿用旧实验的称呼，准确比较长度为 **32704 tokens = 32192 历史 tokens + 512 Queries**。这是为满足固定 NOSA-8B 原生池化实现要求总长严格小于 32768；三个模型使用相同因果窗口，未使用本次 64K 外推的结果。每层历史为 503 个 64-token 块，Top 10%/20%/40% 向上取整为 51/101/202 块。

每层块包含全部 KV heads；同一 Query 对同一块的跨 head 访问合并，不同 Query 的重复访问保留。逐文档、逐层归一化后平均全部 32 层，再等权平均三个 PG19 文档（10146、10321、10356）；阴影为文档 min–max，不是置信区间。所有层采用相同 K、分别选块。数值为该窗口的事后频率覆盖，不是未来窗口预测命中率或恢复延迟。

![全部 32 层](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/exports/kv-access-concentration-32k-512q-20260921/concentration-by-layer.png)

本次只选择展示范围并重绘，原数据哈希与旧版一致。完整的采集来源、模型 revision、配对前向检查、NSA 压缩状态开销和数据限制见 [原始报告](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/exports/kv-access-concentration-8b-20260921/README.md)。64K 四模型测试及 Qwen 的不利结果继续保留在 [历史对照](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/exports/kv-access-concentration-64k-20260921/README.md)。

- [主图 PDF](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/exports/kv-access-concentration-32k-512q-20260921/access-concentration.pdf) / [SVG](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/exports/kv-access-concentration-32k-512q-20260921/access-concentration.svg)
- [逐层 PDF](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/exports/kv-access-concentration-32k-512q-20260921/concentration-by-layer.pdf)
- [原始逐层数据](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/data/kv-access-concentration-8b-20260921/layers.csv) / [原始计数](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/data/kv-access-concentration-8b-20260921/counts.npz)
- [绘图脚本](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/native-sparse/20260921-concentration-nosa8b/render_selected_512.py)
- [当前选择](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/exports/kv-access-concentration-32k-512q-20260921/SELECTION.json) / [审查记录](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/exports/kv-access-concentration-32k-512q-20260921/REVIEW.json)

用项目 `.venv/bin/python` 运行绘图脚本即可复现。本次产物位于 experiments/ 与 exports/；论文文件未在本次操作中修改。
