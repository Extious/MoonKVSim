# 保留原图型，替换新 workflow 与本轮物理数据

用户最新约束（2026-10-05）：论文 Motivation 的图像类型、绘制方式和风格不变，只改变 workflow 并绘制真实的新实验；Background 同样。视觉基准为 `../workflow-paper-revision-20261005/before/`。其旧数值、旧应用 trace 和旧结果没有进入本轮取数。这个基准只确定图型、布局和视觉样式。

随后用户要求不再将独立的两应用 DAG 图插入论文，并整理 serving 图中的 Workflow runtime。独立图源及导出仍保留，正文引用已改为 Background 小节；runtime 节点重新对齐，八条依赖改为无交叉的直角连线。原 Figure 2 随 LaTeX 自动编号为 Figure 1。修改前快照和最终排版核对见 `../serving-runtime-routing-20261005/`。

最新 Figure 1 修正：去掉调用序号 A4/C4/B2 和重复的 dispatch 标签，只以 A/C/B 标记 KV 所属 Agent；B 的两条依赖都从右侧出发。runtime→Router、Router→worker 和返回路径的箭头前保留充分的直线段，虚线返回路径用连续的实线短段连接箭头。原生 SVG 核对全部 14 个箭头均与线段连续且方向一致。最终导出、主文编译和项目内纠正记录见 `../serving-agent-arrows-20261005/`。

最新澄清：“workflow 的图像不变，变的只是标识”。现已恢复三个 PDF 批注时原图的 runtime 框、节点坐标、端口和八条箭头路径，只通过图内字母别名按列显示 A/B/C、D/E、F、G。原字母到显示字母的映射是 A→B、B→C、C→A、D→E、E→D、F→F、G→G，下面 KV 所属 Agent 的文字使用同一映射；实验中的 Agent ID 和其他图不重命名。保留单行 tokens/Reused KV/New KV 页脚，当前图为 84.68×82.19 mm，最小字号 10.24 pt。`../serving-compact-order-20261005/` 中的节点重排和 78.34 mm 图高属于已被纠正的中间版本；最新精确几何比对、原生箭头核验和正文彩色/灰度查看见 `../serving-label-only-20261005/`。

最新两处高度批注：保持上述节点坐标、字母和八条依赖，仅去掉显示 C→F（内部 `b-f`）的下绕段，并收紧 runtime、Router 和 worker 的纵向间隔。其余七条 DAG 箭头原样保留；worker/rank/KV 只整体上移，尺寸和字号不缩小。runtime 到 worker 的跨度由 68 降至 48 源单位；最终图高从 82.19 mm 降至 77.42 mm，最小字号仍为 10.24 pt。该局部修正覆盖上段对旧框高和 C→F 路径的精确保留要求，核验见 `../serving-tight-spacing-20261005/`。

最新正文第 2 页批注要求 Worker 0 的两行改为上 A、下 B。两个 TP rank 均已交换完整 Agent 行（含 K/V 标签、条形、斜线），各自长度和稳定 ID 保留；对应生成列表为内部 C/A/B，显示 A/B/C。上方 DAG、其他几何、图高和字号不变。核验与本地正文编译见 `../serving-kv-row-order-20261005/`。

| 主文原图 | 保留的形式 | 本轮新内容、来源 |
| --- | --- | --- |
| `serving_model.pdf` | Workflow runtime → Router → worker；TP rank 各自 K/V；绿色复用、琥珀斜线新 KV | 上方换成实际执行的研究报告 A--G 依赖；下方仍为通用 TP=2、八头 MHA 示意，不能称为本轮 HF 实测配置 |
| 独立应用 DAG（不再插入主文） | 左到右；简单浅绿角色节点、细箭头；内部请求省略 | 保留上次未加徽标的 DAG 图稿作为参考；依赖与实际两个应用一致 |
| `agent_value_a.pdf` | 按时间比例的 Agent 区间；红色路径、蓝色其他任务、虚线 Slack | 新研究输入的第一个预先指定健康 GPU replay。ready→finish 为实测，含服务排队；虚线为同一显式 DAG 上按已观测时长推导的容忍量，非独立实测或预测结果。七节点增加图高，字号不缩小 |
| `agent_value_b.pdf` | 四行水平堆叠条形、绿色斜线／红色实心、range、右侧 ΔW | A/B/C/G 四个事先选定 Agent，分别在首轮结束丢失该 Agent KV；三组成对真实 GPU replay。条形为健康首次 forward + 丢失后额外 prefill，两者和为丢失后的首次 forward；右侧是独立实测、带符号的 WCT 差。不能标成 absorbed/exposed，因为数据不足以测出该分解 |
| `kv_value.pdf` | 原三模型累计曲线；圆／方／三角、线型、range 带、Uniform 参考 | NOSA/NSA/MiniCPM4.1 对新 review A 三个完整逐轮历史的实际 native prefill。每 query 对跨 head 重复历史 64-token block 去重，层内归一后均值；末尾 512 query。样本是同一输入的连续状态，不是三个独立应用 |

主文不使用本轮早期生成的 combined-history/recovery、foreground-memory 曲线或大徽标卡片，它们仅保留在导出目录作为已放弃的尝试。原成本曲线在参考主文中未启用，因此本轮完整 prefill 和 H2D 微基准写入成本段，没有增加另一种图形。O3 原来没有图，本轮也不添加图。

## 新输入与真实执行

原始材料、commit 和哈希：`../../experiments/workflow-motivation-20261005/inputs/SOURCE_MANIFEST.json`。

- DRB-66：Obsidian 多视图数据库插件比较；材料仅含三个 commit-pinned README，是有明确边界的材料子集，不代表完整市场调研。
- astropy__astropy-12907：原 issue 和 pre-fix source/docs/test；不读取官方 patch、test_patch 或 solution。本应用交付分析、方案和未执行的测试计划，不声称完成 SWE 修复评估。
- Capture 163125：实际自由生成，健康阶段 36 calls / 15 Agents / 2 inputs；每 Agent 2--4 calls，所有 21 follow-ups 有实际复用 prefix。完整消息、input/output token IDs、CUDA 计时、物理 KV 字节和输出保留。工具准备在计时阶段之前；计时阶段工具调用为零。
- 同分配六个自然 prefix 的三次 full-prefill/H2D 微基准：36 层完整 K/V 恢复逐 tensor 比特相同。H2D 计时不含 CPU checkpoint 建立、元数据发布、故障检测或下一轮推理，不能当作完整恢复延迟。
- Capture 163125 的 loss 阶段自由生成造成后续 token 差异，故该 F0/F1 WCT 对照无效。它的原始输出与 `pair-token-audit.json` 保留，未画成因果恢复收益。
- Replay 163126：冻结本轮新生成的 token，实际运行 GPU prefill/decode；两输入共同运行、三组 counterbalanced pairs + excluded warmup，共 252 calls。输入和输出一致。这是两 job 共队列的初步诊断，有大的正负差值，不作为算法优势图。
- Isolated replay 163136：一个新研究输入，四个预先声明单 Agent KV-loss，三组对照/Agent，加一个不计入统计的 warmup，共 25 workflow replays / 450 calls。父任务完成不会等其他 Agent 争抢的 cache-release 锁；每次完整运行后清理所有 cache。只有受选 Agent cache 删除，权重和 token 日志不变。这不是硬 worker/process failure，也没有执行完整 AegisKV policy。
- Native 163127：新请求文本的 NOSA 初步观测，保留但主文最终三模型图用 163137。
- Native 163137：三模型各三个完整请求历史，instrumented/uninstrumented logits 最大差值均为零，实际 selector 索引与 kernel 接收到的选择匹配。各模型保持已发布长度与注意力设置，无人为 padding、重复、64K 扩展。两 GPU 是按层放置，不是 TP。

## 可复现与证据边界

`build_serving_model.py`、`render_serving_model.py`、`plot_original_types.py` 和 `update_manuscript.py` 是本次最终图稿的生成入口。Draw.io 使用原生 CLI 导出；`sources/serving_model.drawio` 和带嵌入源的 `native/*` 保留。图形数据 CSV 在 `data/`，原输入哈希和计算口径在 `ORIGINAL_TYPE_MEASUREMENTS.json`，独立原始数据核验在 `review/MEASUREMENT_AUDIT.json`。GPU 运行脚本/Slurm 声明及源快照位于本轮实验目录，原始过程日志和每请求记录不删除。

科研图核对包括最终尺寸的彩色和灰度实际导出、嵌入字号、文本界限、native PNG 的 Draw.io 嵌入源、以及完整 canonical `paper/main.pdf` 的最终页面。编译沿用 `experiments/scripts/paper/build_paper.sh`，不打开新 tab、不编译替代文档。

当前只覆盖两个公开输入及小规模测量。该数据不能证明此自建 DAG 的生产流行度、全部应用质量、完整算法收益、Peer-HBM 增益或 Adapter 在饱和负载下有效。native 曲线是未来窗口的回溯计数，非在线预测准确率、实际 HBM hit 或恢复收益。所有 WCT 正负值和波动保留；没有用公式算出的 ΔW 替代实测，也没有把随机波动宣称为收益。

完整 E0--E11 campaign 尚未通过。采样范围、工具协议、负载、故障域、DRAM/HBM 预算、预先声明的场景和质量评价必须另行扩展；这些不通过改变 Motivation 图型来掩盖。
