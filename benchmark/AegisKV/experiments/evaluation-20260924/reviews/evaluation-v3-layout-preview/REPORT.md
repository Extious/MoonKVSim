# 版面预检：旧 v2 primary 数字仍在，不能作为新版结果引用

**仅版面预览，不是 v3 数据核验或投稿定稿。Primary 数字、表 1、图 8 及相关归因仍保留旧 v2，并含 TODO。PDF 每页加有 `LAYOUT PREVIEW: primary results remain v2 (TODO)` 标识。**

结果：`latexmk` 构建成功，**共 14 页，技术内容占到第 13 页**。正文文字在第 12 页结束，但新增 native Figure 11 和图注位于第 13 页上半部；References 从同页中部开始。因此不能把此快照称为 12 技术页。

## 检查对象与构建

预览绑定 `evaluation-v3-draft.snapshot.tex`，SHA-256 为 `e0a917c81a810b1dae5e96d3961215560b98aa6725cabdea188937fcb536de3a`。其 Methodology 已包含 compact 版本。此后 live draft 的压缩不进入这份预检。

原 `benchmark/AegisKV/paper/` 的 28 个文件先复制到本目录 `paper/`；源哈希完整保存在 `SOURCE_SNAPSHOT.json`。仅副本进行以下处理：

1. 用所记录的 draft 快照替换 `evaluation.tex`。
2. 按 root 指示，将 40,960-token 的表述改为 `keeping workflows whose replayed request contexts all fit 40,960 tokens`。这是每个重放 request 的 prompt 加 gold output 上下文上限，不是整个 workflow 的累计 token 上限。
3. 给 `main.tex` 添加页眉预览标识，正文尺寸、行距和字号保持原值。
4. 将已封存 `native-transfer-figure-v1/native-transfer-differences.pdf` 逐字节复制为 `figures/eval-native-component.pdf`。复制前复核该图包全部 18 个文件的 seal。

在本目录 `paper/` 下执行：

```sh
latexmk -pdf -interaction=nonstopmode -halt-on-error -outdir=../build main.tex
```

交付 PDF 是 `LAYOUT_PREVIEW_NOT_V3_RESULTS.pdf`；构建日志为 `latexmk.log` 和 `build/main.log`。`renders/` 保留逐页 96 dpi PNG 与提取文本，以及 native 所在第 13 页的 96/144 dpi 彩色、灰度渲染。

## 实际版面结果

| 项目 | 结果 |
|---|---|
| PDF 页面 | 14 页，612 × 792 pt |
| Evaluation 起点 | 第 7 页末；Methodology 主要在第 8 页 |
| 末尾技术内容 | 第 13 页的 Figure 11 及图注 |
| References 起点 | 第 13 页，标题顶部约 367 pt |
| Overfull hbox/vbox | 0 |
| Underfull hbox/vbox | 23，均未导致构建失败 |
| 未定义引用/引文 | 最终日志中没有 |
| 其他警告 | 原文件的图像 Description 和 vspace 使用提示；不是本次 native 图溢出 |
| 新增 native 图 | 源宽 178 mm，实际正文宽 177.8 mm；10.3 pt 源图文字嵌入后约 10.289 pt |

已实际查看第 8–13 页的阅读尺寸渲染，并查看第 13 页的 96 dpi 彩色/灰度和 144 dpi 彩色图。新增图没有可见裁切、标签碰撞或图例遮挡。四个 compute setting 明确为分类轴，三个模型共用带正负的纵轴，空心三角/方形/菱形在灰度下仍可辨。Current 不利的 Recency/Oracle 结果保留。MiniCPM 零 compute 的约 −2.389 μs 差值接近零线，其精确值保留在图源数据和正文；不能以图上接近零代替数值结论。

本轮只审实际版面和新增图的可读性，不重新认证旧 primary 数值、结构实验、所有前文图或全篇科学结论。副本的旧 primary 归因在 v3 替换后仍须重新审查。Native 图仅为 raw-KV/per-object transfer component；图注继续保留 prepared residency/auxiliary state、假设 compute、三文档先平均两 checkpoint、非 latency-optimal oracle、非 native-kernel/WCT 等边界。

## 不缩字号的压缩建议

第 8–12 页的正文区域已比较充实；第 13 页新增图及图注约占 0.4 个技术页。建议先在 Evaluation 减少约 **350–450 英文词**，再重新编译；这是版面估计，不保证最终 v3 数字替换后恰好 12 页。仅前移 float 声明不能假定会凭空释放其占用面积。

- **Methodology：约 100–120 词。** 将完整形状网格枚举、逐项 metadata 字节和 483 条历史矩阵的细分计数留在 artifact；正文保留 profile 来源与未校准、独立统计单位、40-feature walltime label、12 WF/6 training runs/570 labels、grouped crossfit priors/guard、版本切换和五类策略差异。合并反复出现的“artifact retains”清单。
- **Operating Range：约 100–140 词。** 减少已由图 10 明确表达的逐点数值重复和不改变结论的参数枚举；保留 DRAM 容量不足、32-run Slack/WCT null、post-hoc 竞争机制、TTL/倍率非 crossing、DMA 健康成本及不可行 cohort break-even、checkpoint/compute 耦合负例。详细数列可由明确的 artifact 指针承载。
- **Native：约 80–100 词。** 合并 coverage 段中的两套长百分比列表，正文保留 K=16 不能支持 few misses、K=64 MiniCPM 仍输和新组件的关键正负差值；完整分母/逐模型数列留在已封存表。避免正文重复图注的聚合、compute、oracle 边界，但至少各保留一处，并保留 per-object 与 core LoadBatch 的区别。
- **Primary/结构：约 50–90 词，须待 v3 归因重审后。** 避免表格均值在正文再次逐项重复；压缩记录文件列表。保留 target/cohort 相反、Static/Aegis null、queue 主导、routing 放大反例，以及 shared-host/history 的不利结果。不能靠删掉反例让版面达标。

这些建议不要求修改 Background/Motivation/System Design，也不要求缩小正文或图中文字、改变负值范围，或删掉版本边界。此预览没有应用上述正文压缩。

## 保全与交付边界

原 paper 的 28 个文件在检查结束时与复制时哈希一致；原图包保持封存。没有修改 live draft、原 paper、原图、冻结实验数据，也没有运行 DES。之后 root 对 live draft 的进一步压缩不改变本次 snapshot 的来源。`LAYOUT_REVIEW.json`、`SOURCE_SNAPSHOT.json`、`BUILD_INSPECTION.json` 与 `SEAL.json` 记录检查范围及文件哈希。
