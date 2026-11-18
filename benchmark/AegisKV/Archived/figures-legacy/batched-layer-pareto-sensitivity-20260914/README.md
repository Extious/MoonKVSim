# 帕累托图：翻转纵轴并增加带宽与重放长度子图

2026-09-14。用户明确确认纵轴使用“**低值在上、高值在下，翻转当前纵轴**”，并要求右侧增加 H2D 带宽对比、下方增加重放 token 数对比。已组合为左上基准、右上带宽、下方通栏重放长度三个子图。

![帕累托敏感性三子图](/home/comp/zhanzhao/MoonKVSim/output/pdf/batched-layer-pareto-sensitivity-20260914/pareto-sensitivity.png)

[PDF](/home/comp/zhanzhao/MoonKVSim/output/pdf/batched-layer-pareto-sensitivity-20260914/pareto-sensitivity.pdf) · [可编辑 SVG](/home/comp/zhanzhao/MoonKVSim/output/pdf/batched-layer-pareto-sensitivity-20260914/pareto-sensitivity.svg) · [完整分类数据](/home/comp/zhanzhao/MoonKVSim/output/pdf/batched-layer-pareto-sensitivity-20260914/sensitivity-classification.csv) · [绘图源](/home/comp/zhanzhao/MoonKVSim/output/pdf/batched-layer-pareto-sensitivity-20260914/build_sensitivity.py)

所有子图的横轴范围均为每批 1–36 层，同时也是初始驻留在 Peer HBM 的前层数。上横轴给出初始 HBM 容量；固定 32K 历史下每层为 128 MiB。纵轴均为线性的累计加载等待，单位 ms，翻转后越靠上等待越少；各子图按数值范围分别设置纵轴刻度，没有改变数据或性能目标方向。

- **左上 a：基准帕累托图。** 固定 H2D 25 GB/s，重放 512 token。原来的 36 个数据点和帕累托集合保持不变，只有纵轴翻转及版面调整。蓝色实心圆为非支配点，灰叉为被支配点。五层支配六层；二十层是零等待时初始容量最小的配置。
- **右上 b：H2D 带宽对比。** 重放固定为 512 token，对比 12.5、25、50 GB/s。用颜色与线型区分曲线，每条曲线单独标出非支配点。其零等待起点依次为 25、20、1 层。
- **下方 c：重放 token 数对比。** H2D 固定为 25 GB/s，对比 128、256、512、1024、2048 token。1024 和 2048 的累计等待在所有 36 个配置中都精确为零，因此以同一条曲线显示并在图例明确写出两种重放长度；CSV 分别保留两种条件。没有错开坐标、添加微小等待或删去条件来避免重合。

实心圆是**该条曲线内部**以初始 HBM 容量和累计等待都越小越好得到的帕累托点。叉号表示同一条件下存在占用和等待都不更差、且至少一项严格更好的配置。没有将不同带宽或不同重放工作量的条件混合做支配排名。更高带宽的获取成本未计入；更长重放即使等待为零，总计算时间也会更长，因此不能将其当成更好的总恢复性能。

| 对比类型 | 固定项 | 变化项 | 首次零等待的每批层数 |
|---|---|---|---:|
| 带宽 | 512 token | 12.5 GB/s | 25 |
| 带宽 | 512 token | 25 GB/s | 20 |
| 带宽 | 512 token | 50 GB/s | 1 |
| 重放长度 | 25 GB/s | 128 token | 30 |
| 重放长度 | 25 GB/s | 256 token | 25 |
| 重放长度 | 25 GB/s | 512 token | 20 |
| 重放长度 | 25 GB/s | 1024 token | 1 |
| 重放长度 | 25 GB/s | 2048 token | 1 |

这组图仍是 Qwen3-8B 结构下的解析估算，固定 36 层、历史 32768 token、假设有效算力 100 TFLOP/s。只预取下一批，整批历史 KV 就绪后切换；尾批使用实际剩余层数。已加载 KV 保留，初始驻留容量不是整个恢复期间的容量上限。不计启动开销、复制与计算争用、故障检测、接管排队、备份维护或前台容量竞争，没有运行 GPU 实验或硬件校准。

共有 7 个不同的带宽与重放条件、252 个唯一配置，全部逐点匹配此前的 `batch-size-sweep.csv`。基准条件在多个子图复用，不能重复计数。每个固定条件使用精确分数时间做完整支配比较，再以按容量递增的最小等待记录独立复核；同时核对基准帕累托集合未变，以及 1024/2048 两条等待曲线精确重合。

复现：

```bash
python3 output/pdf/batched-layer-pareto-sensitivity-20260914/build_sensitivity.py
```

导出宽度为 178 mm，保留 PNG、PDF、SVG、源代码与分类 CSV。`curve-summaries.json` 记录每个条件的帕累托集合、零等待起点和计算时间；`parameters.json` 记录用户确认的纵轴方向、各子图条件与重合曲线处理；`validation.json`、`MANIFEST.json`、`REVIEW.json` 分别保存计算验证、来源哈希和实际导出审查。没有重新验收论文整页排版。
