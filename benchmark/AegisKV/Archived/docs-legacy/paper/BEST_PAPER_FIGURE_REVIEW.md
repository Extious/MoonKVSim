# 获奖系统论文的图页对照与本次改法

[当前论文图](../../experiments/Paper_Draft.md) · [逐图记录](../../experiments/PAPER_FIGURE_REVIEW.md)

**算法修订后的应用。** 当前 Agent 子租约 / Guarded AIMD 版保留下面的视觉原则，重新执行并重绘了对应证据：51 张独立图中，38 张列为正文候选、13 张列为补充，正文有 8 组互补单栏图并排。联合 WCT 实例、Agent 信用余额、单物理前缀与独立 AIMD 替换旧 Slack ticket / 删除闭包示意；原生 L40S 组件图与未标定 DES 分开。batch 1/4 的 forward 减速图使用相同纵轴，密集 Workflow 曲线仍为通栏。以下 33 图、6 组布局记录对应[上一版 PrefixAdmission 图](../../experiments/Paper_Figures_PrefixAdmission_20260908.md)，不是当前算法实验。

本次实际下载并查看了下列四篇论文的图页，覆盖 2023–2025 年。四篇的 USENIX 官方页面均明确标注 Best Paper；不将普通录用、artifact 或其他奖项当作 Best Paper。PDF 来源与 SHA-256 见 [参考文件清单](../related_works/figure-references-20260908/manifest.json)。以下绘图特点是本次对图页的观察，不是会议统一规定，也不把绘图方式视为获奖原因。

| 论文及获奖来源 | 实际查看的图与 PDF 页码 | 借鉴的表达方式 | AegisKV 中的落实 |
|---|---|---|---|
| [Ensō，OSDI 2023](https://www.usenix.org/conference/osdi23/presentation/sadok) | [PDF](../related_works/figure-references-20260908/enso-osdi23.pdf)：Figs. 1–3，pp. 4–5；Figs. 10–12，p. 12 | 直接画缓冲区、指针和到达数据，用连续状态说明接口；代价分解和最终时延相互解释 | 用实际 KV 单元和 tier 边界替代摘要框；将 CPU/传输组成并排，再接前台 GET 减速 |
| [Anvil，OSDI 2024](https://www.usenix.org/conference/osdi24/presentation/sun-xudong) | [PDF](../related_works/figure-references-20260908/anvil-osdi24.pdf)：Fig. 5，p. 5 | 通过不同执行轨迹表现性质是否成立，图中的事件与正文定义对应 | 画出 quota 已撤销但物理内存仍计账的状态，明确 free ACK 这一边界 |
| [Mooncake，FAST 2025](https://www.usenix.org/conference/fast25/presentation/qin) | [PDF](../related_works/figure-references-20260908/mooncake-fast25.pdf)：Fig. 2，p. 3；Figs. 9–11，p. 12；Figs. 12–14，p. 13 | 架构中同时表达资源位置和职责；缓存率、计算代价、传输及阶段分解围绕同一机制组织 | 架构画出 primary/backup/DRAM 对象；将总体 WCT 与缓存组成、TTFT 与 TPOT、带宽与并发分别成组 |
| [CausalSim，NSDI 2023](https://www.usenix.org/conference/nsdi23/presentation/alomar) | [PDF](../related_works/figure-references-20260908/causalsim-nsdi23.pdf)：Fig. 2，p. 5；Figs. 6–7，p. 12 | 对照分布用同一图例；总体结果旁边给出解释误差或适用条件的视图 | 保持三系统编码、配对对象和分母一致，将结果与解释放在相邻位置；保留不利结果和模拟范围 |

## 这次改变的是图中能读到的内容

- **架构图**：工作流依赖 → 控制状态；下方对应 Source、Peer、Store 的资源边界和 KV 单元。箭头有明确的数据/控制语义。
- **Slack 图**：A/B 分支的 3/8 s 示例、8 s 汇合点、5 s 结构余量与 4 s 保守 ticket 在同一幅图中相互对应。示意数值有独立记录，不作为实验结果。
- **共享前缀图**：六次逻辑引用映射到四个物理 chunk，删除闭包释放 3b，两个 consumer 分别失去 2b 的前缀；显示容量和损失为何不能使用同一个计数。
- **显存控制图**：按比例画 Before / Revoke / After ACK 三个包络，配额收缩与物理计账分开。用具体状态解释安全条件，避免只有“检查→通过/拒绝”的流程。
- **提交恢复图**：三个原来过于零碎的小图合成一个生命周期，同一 C1 的异步提交、故障时各 tier 的前缀、primary 装入和 suffix 重算使用同一对象身份。
- **实验图**：单栏图按单栏尺寸重新排版，保留完整分布和尾部；三系统使用固定顺序、颜色和线型，分解图用位置标识系统、颜色和纹理标识组成。

没有为了增加信息量加入无来源曲线、任意装饰、重复统计或更多小字。原公式曲线的关系写入正文和 DAG 示例；原提交/恢复三图的信息保留在合并后的完整例子中。

## 布局与文件

上一版为 **33 张独立图，6 组并排**。并排依据是共同问题与互补信息：动机的价值/成本、输入长度/工作流规模、WCT 分布/缓存组成、TTFT/TPOT、CPU/传输组成、带宽/并发敏感性。160 个对象的密集 Workflow 曲线保持通栏，避免通过缩小字体强行并排。

PDF、SVG 和 PNG 分开保留；设计图保留原生 Draw.io 与 [示意数值](../../../../output/pdf/aegiskv-paper-story-20260908/design-examples.json)，统计图保留 CSV。Markdown 并排使用表格和独立图链接，LaTeX 用两个 minipage 组合，未将实验图拼成一张位图。上一版 36 图完整保留在 [改版前目录](../../../../output/pdf/aegiskv-paper-story-20260908/before-best-paper-review/FIGURES.md)。

字体统一为 DejaVu Sans，曲线最小正文字体 10 pt，设计图按 7 inch 导出后的默认字体约 10.9 pt。原生 Draw.io 初次将未安装的字体回退为 DejaVu Sans Mono，已补齐与 Matplotlib 相同的字体文件，并在实际导出的 PDF 中检查字体名称。使用原生导出与最终尺寸视觉检查，不以 XML 合法或文字在页内代替实际审查。
