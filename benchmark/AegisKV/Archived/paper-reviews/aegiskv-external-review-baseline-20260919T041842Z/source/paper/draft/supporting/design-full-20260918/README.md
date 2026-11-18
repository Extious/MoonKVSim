# System Design 长稿与待迁移素材（2026-09-18）

这里保存压缩前的中文正文和完整 LaTeX 源，未被 `main.tex` 引入。它们是写作素材，不是新增实验或投稿附件。当前正文入口仍是 `../../system_design.md` 与 `../../../sections/system_design.tex`。

## 正文压缩分工

| 内容 | 当前去向 | 必须保留的含义 |
|---|---|---|
| 三项 Insight 与三联图 | 正文 §3.1，方法和结论各说一次 | 时间预测仍未验证；稀疏发布不是采用率；retry 覆盖是留出文本轨迹 |
| Overview 的模块介绍与时间尺度表 | 三层说明 + 各模块小节；时间尺度改为短句 | Planner 决策、Connector 执行；Peer 目标预先绑定 |
| 原 Figure 5：KV 预算敏感性 | 后续 Evaluation 的候选；原图保留 | 与图 3(c) 复用同一捕获，预算点不是独立样本 |
| 原 Figure 6：四种恢复流水线 | 正文新 Figure 5，图形未改 | 校准模型、同一终点、并非故障恢复实测 |
| 原 Figure 7：等待与 Peer 字节扫描 | 后续模型分析/消融候选；原图保留 | NOSA 曲线借 MiniCPM4 字节/计算参数，只隔离访问画像 |
| 16K/64K/128K 外推、带宽与尾长案例 | 本目录旧稿 | 明确外推和同质层近似，不升级为真实跨模型测量 |
| 计数器存储、每步操作数、复制流量算例 | 后续 Implementation/Evaluation 素材 | 静态计数不等于运行时开销测量 |
| 反复出现的局限说明 | 对应结论处标一次，末尾保留适用边界 | 不删除负面结果、不把设计不变式当实现验证 |

原图仍在 `../../../figures/design-insights/retry-kv-budget.pdf` 和 `../../../figures/design-wait-vs-bytes.pdf`，完整说明与生成器可从对应 MANIFEST/旧稿追溯。本目录 `.tex` 为压缩前原样快照，图路径按从 paper/ 编译解释；不单独编译，也不为节省正文把必要机制藏进这里。

12 页正文预算建议（写作规划，不是已完成内容）：Introduction 1 页，Background/Motivation 2 页，Design 3.5–4 页，Implementation 0.5 页，Evaluation 3–3.5 页，Related Work/Conclusion 0.75 页，留少量排版余量。当前 Motivation 由另一会话修改，本轮未重写。

Overview 继续遵循用户上轮要求，等比缩至单栏。约 5 pt 的最小图内文字不满足 EuroSys 2027 的 10 pt 规范；本轮未用进一步缩字、缩行距或改页边距来节省篇幅。正式投稿前仍需在相同外形比例下简化图内标注并提高字号。
