# AegisKV 本轮外部评审基线

本轮仅检查、重编译和固定当前版本，没有改动论文正文、算法或图源。后续 ChatGPT、Grok、Claude 评审应上传这里的只读副本，避免共享 main.pdf 随其他任务变化。

## 文件身份

- 当前 main.pdf：/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/main.pdf
- 固定评审副本：/home/comp/zhanzhao/MoonKVSim/output/pdf/aegiskv-external-review-baseline-20260919T041842Z/AegisKV-review-baseline.pdf
- 两者 SHA-256：32aa352a81387c4cb982603742e679b7fcb9f83a22383eaa72f9c78299a89a52
- 页数：9；大小：662743 bytes。
- 分支：aegiskv；Git HEAD：b10886754ed4890285d1320cbb5fe679a9979166。
- paper 目录当前 246 个非忽略文件均未纳入 Git 跟踪，故 HEAD 不能唯一标识本稿；source/paper 和 SOURCE_FILES.json 保存了全部这批文件及哈希。
- 全仓库原有大量修改/重命名/未跟踪资产；状态与 staged/unstaged diff 已保存，没有清理、提交或改动它们。

## 编译与检查

项目标准命令（从仓库根目录执行）：

    sh benchmark/AegisKV/paper/build.sh

标准脚本首次返回 up-to-date，随后在 paper 目录强制重编译：

    latexmk -g -pdf -interaction=nonstopmode -halt-on-error -outdir=build main.tex

随后将 build/main.pdf 复制到 main.pdf 和固定评审副本。BUILD.log、BUILD_FORCED.log、main.log、main.aux、main.bbl、main.blg、main.fls 已保存。强制构建返回 0，最终日志无 undefined reference/citation、无 multiply defined label、无 overfull box；24 个引用键均解析，有 8 条 underfull hbox 提示。源码在快照、构建与最终确认之间哈希一致。

已渲染并逐页查看全部 9 页（144 dpi），查看页码、图表、算法、正文和参考文献。没有观察到缺图、正文裁切、重叠、乱码方块或意外空白页。Figure 4 在第 5 页的普通标签约 4.972 pt，仍过小；数学上下标单独对待，不把其最小字号当成全部正文或图中文字。逐页 PNG、文本及 CONTACT_SHEET.png 均已保留。

EuroSys 2027 当前官方格式要求包括图内文字至少 10 pt、无需放大即可辨读：[官方 CFP](https://2027.eurosys.org/cfp.html)。本稿适合开展缺陷评审，不能宣称已通过投稿格式检查。按协调任务的冻结要求保留小字缺陷，未重画图。

## 文稿范围

当前 main.tex 明确是 integrated preview：摘要、第 2 节背景与动机、第 3 节系统设计和参考文献。PDF 第 1 页起为摘要与第 2 节，第 3 页开始第 3 节，第 8 页开始参考文献，第 9 页为参考文献续页。Introduction、Implementation、Evaluation、Related Work、Conclusion 未纳入本主文件，不能向外部评审器介绍成一篇已经齐备的完整投稿。

## 当前 PDF 中的三节职责

| 节 | 当前职责 | 位置 |
|---|---|---|
| §3.4 Recovery Manager | 请求到达时固定 retry 目标与 Peer DP rank；故障后隔离失效源、读取提交前沿并提交并行 retry；本身不预留 HBM | 第 4–6 页 |
| §3.5 KV Master | 在固定 Z checkpoint、prefill 完成和策略事件选择 Recompute/DRAM/Peer，按 Slack 准入，为各请求选择 L_r 与热块 | 第 6–7 页；Algorithm 2 第 7 页 |
| §3.6 Adapter | 按时间窗口发布 Peer 总预算 B_p，扣除前台需求与余量并限制在 KV 池的一半以内；处理实际容量/引用状态 | 第 7–8 页；Algorithm 3 第 8 页 |

Algorithm 1 是 §3.3 Tracker 的 GBDT–CPM Slack 估计，位于第 5 页；Recovery Manager 不应被误称为 Algorithm 1。Z 是系统配置，L_r 属于 KV Master，B_p 属于 Adapter。

## 已知未完成项与讨论/正文差异

1. **稿件尚不完整。** 主文件未包含完整引言、实现、评估、相关工作和结论；当前 9 页不能当作 9 页完整系统论文。
2. **摘要实验结论仍是未经当前设计验证的暂定写法。** abstract.tex 第 14–17 行注释承认未验证；第 18–20 行 PDF 却声称实验显著降低 WCT 且正常开销可忽略。设计末尾还明确列出端到端验证缺口。本轮保留原句供评审发现，不把该句当成已有实验事实。
3. **引用锁与降级的最新用户澄清尚未进入 PDF。** 用户已明确：其他请求不能抢占活跃请求的 Peer 副本；Adapter 缩容在无安全无引用对象可回收时可以将带引用副本降级到 DRAM；所属请求可以因热集变化替换自己的块。当前 capacity_allocation.tex 第 13–23 行仍写旧副本保持引用至请求结束，缩容及降低 L_r 不撤销引用；Algorithm 3 也仅回收无引用对象。需要在收到评审后统一更新正文与算法。
4. **K 的含义尚需同步澄清。** 用户定义 K 为每请求、每层存于 Peer HBM 的 Block 数；当前 PDF 仍将 K_r=ceil(h*n_r) 用作候选数量，并允许旧引用块额外占用。用户没有在最新澄清中单独确认一个固定 K 数值，不能擅自把所有模型 K 改成常数。
5. **Figure 4 小字。** 最小普通标签约 4.972 pt，已目视确认，不满足上述图内字号要求。本轮不改变送审基线。
6. **当前设计的完整实证仍未完成。** 逐请求 M/N 画像与 L 选择、Z 敏感性、预测误差、并发 retry、前台干扰、容量收缩及活跃迁移开销尚需验证；Figure 5 是带校准参数的分析流水线，不能替代这些端到端结果。
7. **稀疏检索/预取相关工作调查尚未整合到正文。** 本任务新整理的 30 项调查在 docs/related_works/kv-prefetch-survey-20260919/，不在本 PDF 的完整 Related Work 中。

最新 K/锁规则已在本任务调研报告第 5 节记录，但本轮明确不将其补写进送审 PDF，以保持当前文件基线。外部评审意见应区分 PDF 实际内容与这些尚未合入的决定。

## 后续协作边界

本任务本轮不启动实质改进或实测。外部评审回来后，再由协调任务分派系统设计/算法与 Motivation 的修改范围。重新送审时应建立新的基线目录，不能覆盖本目录的 PDF。
