# AegisKV 紧凑正文图稿规格

本轮用户要求：Motivation 三张，以旧图为依据突出 Observation；System Design 只有一张 System Overview；Evaluation 重新设计。正文为中文，保留三个英文部分标题。Algorithm 2 实现同步仍由用户暂缓。

## Retriever：已查看的依据

- 原论文 `paper/figures/motivation-real-cc.png` 及其五分支、124 Workflow 两份 CSV：借鉴“观测分支差异 → 恢复暴露不同”的因果问题，不把旧 235B 模型推演混入新 8B 评估。
- Mooncake FAST 2025，第 3 页实际架构图：按物理资源组织独立的数据与控制路径。
- CausalSim NSDI 2023，第 12 页定量图：统一比较坐标、直接说明相对指标，证据服务于相邻论点。
- 当前 51 图及其来源：先保留明确配对的工作流和已核对样本，再压缩重复编码。

## Planner：12 张图的论点与去向

| 图号 | 图像 | 一句话问题 / Observation | 编码与不变量 |
|---|---|---|---|
| 1 | motivation-branch-gap | O1：并行分支具有显著的持续时间差 | 124 个观测 Workflow 的 ECDF；对数秒；不是因果 Slack 分布 |
| 2 | motivation-recovery-exposure | O2：重算代价排序不等于 WCT 损失排序 | 旧五分支同一示例的吸收/暴露堆叠条；五次独立反事实干预；保持 235B 配置标签 |
| 3 | motivation-kv-capacity | O3：长上下文 KV 使保护容量受限 | 8B BF16 解析字节；权重后参考线不冒充可借配额 |
| 4 | system-overview | 哪些资源、对象与控制关系构成完整系统 | 一张 7 inch 可编辑架构；Source、Peer、DRAM、Recovery；同名 C0/C1 独立复制，装入新 primary；AIMD 独立反馈 |
| 5 | f0-revisit-wct | 默认正常执行有无完整 Workflow 收益 | 三系统、同配置、同 160 ID；保留完整曲线与均值表 |
| 6 | f1-q50-workflow-penalty | 故障增量是否降低 | 同对象 F1−自身 F0；完整正负零值；另外两位置及恢复终点用表格 |
| 7 | f0-revisit-dram-hit | DRAM 准入是否损害正常复用 | 实际复用 token / 全 prompt token；保持图 5 ID 顺序 |
| 8 | f0-revisit-hbm-wait | 前台 HBM 等待是否增加 | 每 Workflow 内请求均值；调度排队与 TTFT 另表汇总 |
| 9 | evaluation-resource-cost | 计算与共享路径成本来自哪里 | 五个指标分别相对同指标 Mooncake 归一化；对数轴、逐项实测/模拟标记；绝对单位在表和 CSV |
| 10 | evaluation-native-interference | 容量足够时复制是否仍干扰 forward | batch 1/4 共用一个坐标，条件间不连线；8 GiB 子集全部 120 观测；五块配对倍率的中位数和全范围 |
| 11 | aimd-quota-and-occupancy | 撤销授权和物理释放是否一致 | 50 ms、八 GPU 总量、硬上限/授权/占用三条线；动态/静态及 DAG/Lazy 消融以表格或计数说明 |
| 12 | evaluation-configuration-effects | 排名是否依赖资源条件 | 八个不同配置、每行匹配基线；单因素变化；不把异质条件画成时间曲线或重复误差线 |

原 38 张主图中的 30 张移至补充；6 张定量/解析图保留原导出，1 张故障图仅缩短纵轴标题以保留版面余量，System Overview 重画，再新增 4 张不同的信息组织方式，形成 12 张正文图。移出的图包括工作负载 CDF、重复 WCT/CDF、请求尾部、CPU/流量细项、其余故障位置、详细机制图、原生单条件图及逐个敏感性小图。负面或零结果不是移出的标准；默认 WCT 变差、命中下降、CPU 增加、焦点恢复 Peer token 为零均留在正文。

## Stylist 与 Visualizer

独立文件采用 3.33 或 7 inch，统计文字至少 10 pt，单一绘图区；图 1/2 可并排，但各有独立 PDF 和图注。沿用 Mooncake 灰圆、DRAM-only AegisKV 橙方、AegisKV 蓝三角，密集曲线另用线型。微基准的颜色表示复制模式，局部图例明确其语义。图中不嵌入来源目录、审查状态或统计说明段落。

新增统计图通过 `render_compact_paper.py` 从已核对 CSV 或冻结执行汇总重算；图 10 不把中位数之比当作配对倍率的中位数。架构使用原生 Draw.io 导出，保留 XML。旧 49 个 CSV 逐字节不变，新视图保留输入哈希与逐点表。原 51 图的精简前版本在 `before-compact-paper` 中留存索引，重画前 Overview 有独立备份。

## Critic：本轮检查重点

检查三部分图数为 3/1/8、总计 12，正文只有连续图号与短图注。逐张查看实际 PNG 与最终尺寸 PDF，另外查看 Markdown 同行图、公式与图注，确保图例不挡数据、尾部和误差线完整、长标签不越界。

架构专项：所有恢复箭头进入恢复 Worker 的新 primary，不能将 C0/C1 指向无关的 P0/P1；独立 DRAM 路径不能画成依赖 Peer 的级联写入；观察与授权方向相反，标签不能遮住反馈线。反事实图专项：A3 吸收全部 46.635156 s，A4 暴露全部 35.903174 s；不暗示五分支同时故障。

最终审查状态与哈希记录在既有 `VISUAL_REVIEW.json`、`MARKDOWN_LAYOUT.json` 和 `DELIVERY_AUDIT.json`，未查看或未通过时不在规格中预先宣称通过。

本轮实际自检发现：图 6 原纵轴标题几乎占满画幅高度。改为 F1 − F0 WCT (s)，保留完整 160 对象、原 CSV 字节及三个故障位置的共同范围；不缩小字号或裁剪长尾。
