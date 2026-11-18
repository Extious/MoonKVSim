# 压缩版版面预检：仍为旧 v2 primary / TODO

**这是独立排版预览，不是 v3 数值核验或投稿定稿。Primary 数字、表 1、图 8 及相关归因仍为旧 v2，并有 TODO。PDF 保留醒目预览页眉。**

新快照为 2,908 whitespace tokens，SHA-256 `83940a91244d3cb0698bbb775a67d76d7c1695096176f98cad0c8f261f0ce51a`。它相对上一份快照减少约 320 tokens，但当前仍未达到 12 技术页。

| 预览 | 总页数 | 末尾技术页 | Native 图页 | References 起点 | Overfull |
|---|---:|---:|---:|---:|---:|
| 当前 compact 原样快照 | 14 | 13 | 13 | 12 | 0 |
| 仅前移 native figure 声明的独立试排 | 14 | 13 | 12 | 13 | 0 |

原样快照的正文和 References 已到第 12 页，但 native 图因在第 12 页才声明，仍浮到第 13 页。为把 float 延迟与实际内容容量分开，额外建立 `float-placement-trial/`：只将**完全相同**的 native `figure*` block 前移到 Quota pressure 段之前，不改文字、图、字号、页边距或行距。试排使图进入第 12 页，但 `Scope of the Evidence` 整节移到第 13 页，因此单纯前移 float 仍不足以达到 12 技术页。

## 精确剩余量及建议

试排第 13 页上方的 Scope 占 **17 行正文 + 1 行节标题**，共约 125 个 PDF 提取词；含标题的文本块高 213.8 pt（约 75.4 mm）。`float-placement-trial/OVERFLOW_LINES.json` 保存每行文字及坐标。这里的 18 是实际占用行：PDF 将节号和标题分成两个提取记录，不能误报成 19 个排版行。

建议保留前移后的 native float 声明，正文再节省约 **18–22 个单栏行，约 130–170 英文词**，然后重新构建。该估计需要为标题/段间距留余量，并非最终 v3 数字替换后的页数保证。不要直接删除 Scope 中的证据边界。

- **Native：约 9–12 行。** 两套长 coverage 百分比列表可合并成区间或最必要的具体对照，并用 artifact 承载完整逐模型数列。保留 K=16 不支持 few misses、K=64 MiniCPM 仍落后、coverage 不是 WCT/运行时命中率；新组件的 131.072/128.683、−2.389 和 209.436/218.124 μs 关键差值继续保留。把正文与图注重复的三文档聚合、假设 compute、oracle 非最优等说明各保留一处，不能删除 per-object/core LoadBatch、prepared state 和非 native kernel/WCT 的区别。
- **Methodology：约 6–8 行。** 完整 196-shape 网格枚举、metadata 逐字节参数和历史 483 条矩阵细分可移到已封存 artifact；合并末尾反复列出的 artifact 保存项。保留 12 WF/6 training runs/570 labels、submission-to-final 含队列、fold 内 priors、workflow-group guard、统计单位和新旧 predictor 版本区别。
- **如还差 2–4 行：** 压缩 Operating Range 中已由图 10 表达的重复逐点数值或表述。不要删掉容量失去 checkpoint、Slack/WCT null、DMA 健康代价/不可行 cohort break-even、TTL 非 crossing、checkpoint 与 compute 耦合的负例。

以上仅为修改建议，本目录没有应用正文压缩。Background、Motivation、System Design 均无需改动，也不需要缩小图或字体。

## 构建和实际查看

两份副本均以 `latexmk -pdf -interaction=nonstopmode -halt-on-error -outdir=../build main.tex` 成功构建；最终日志没有未定义引用/引文。原样快照有 22 个非致命 Underfull 警告，试排具体记录保存在其 `BUILD_INSPECTION.json`。原有 Description/vspace 提示保持，新增 native 图没有 Overfull。

已实际查看 compact 的第 9–13 页和 float-only 试排的第 12–13 页；试排 native 页另查看 96 dpi 灰度。Native 图维持源宽 178 mm、源文字 10.3 pt，在正文宽 177.8 mm 下约为 10.289 pt。彩色/灰度标记、正负方向、误差范围和图注仍可读，没有可见裁切、重叠或缩字体。源图及数值未变化，本轮不重新做数值认证。

文件：

- `LAYOUT_PREVIEW_NOT_V3_RESULTS.pdf`：当前 compact 快照原样预览。
- `float-placement-trial/FLOAT_PLACEMENT_PREVIEW_NOT_V3_RESULTS.pdf`：仅前移 native float 的试排。
- 两个 `renders/` 目录：逐页 PNG/文本及 native 页彩色、灰度预览。
- `SOURCE_SNAPSHOT.json`、`BUILD_INSPECTION.json`、`LAYOUT_REVIEW.json`、`SEAL.json`：来源、日志统计和封存。

## 保全

原 paper 的 28 个文件、上一轮预检的 75 个文件、native 图包的 18 个文件均按已有哈希复核不变。没有编辑 live draft、原 paper、旧预检、原图或冻结数据；没有新 DES。当前快照中 40,960-token request-context 表述已经由 root 修正，本轮无需再改该句。
