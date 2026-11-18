# KV Motivation 理论图，2026-09-13

完整结论、公式、因素分析和优先级建议见 [论文分析文档](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/docs/paper/KV_MOTIVATION_AND_PRIORITY_20260913.md)。本目录不含模型测量或新的模拟性能实验。

| 图 | 作用 | 证据 |
|---|---|---|
| fixed-retry-profile | 固定 M=32768、N=512 的放置、H2D、计算及逐层等待 | Qwen3-8B 结构与假设速率下的解析时间线 |
| layer-depth-motivation | M、N 和有效路径带宽如何改变最少前层驻留数 | 60 个参数状态的闭式推导 |
| sparse-window-counterexample | 同样的单 Query 稀疏率可以对应不同恢复需求并集 | 两组显式构造；不是原生模型轨迹 |
| native-window-structural-example | 固定窗口分支中少量历史块被反复需要的结构性情形 | 逐 Query 窗口掩码解析；不是整个 NSA 模型的工作集 |

每张图提供可预览 PNG、178 mm 宽 PDF、SVG 与 PDF 渲染预览。CSV 为绘图数据，MANIFEST.json 记录结构来源、算术核对和文件哈希，REVIEW.json 记录实际导出检查。

复算命令（项目根目录）：

```bash
TMPDIR=/tmp .venv/bin/python output/pdf/kv-motivation-20260913/build_motivation.py
```

分层图假设单一连续复制流、从 t=0 尽早预取、整层消费门、计算复制不争用和足够恢复空间。有效算力 100 TFLOP/s、传输 12.5/25/50 GB/s 均为假设。前层副本减少的是可暴露的历史装入等待；恢复后的历史 KV 占用仍可能增长至全量。

原生稀疏模型的内容相关热块尚无本项目访问轨迹支持。NSA Figure 8 来自 Full Attention 模型；不能将其当作 NSA 恢复热块分布。固定窗口图只说明窗口分支的历史访问，压缩、选择分支和控制状态须另外核算。
