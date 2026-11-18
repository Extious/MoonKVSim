# Background 引用与配图交付记录

- 主稿：`paper/main.pdf`，23 页；新 serving 图为 Figure 1，位于第 2 页。
- 英文：`paper/background.tex` 直接采用老师重写稿。移除 figure 环境和引用命令后，与用户粘贴原文进行空白归一化比较，正文完全一致。增加的是 3 处空引用的内容、4 处支撑引用及与实际图对应的 caption / Description。
- 文献：原有 6 个 key、新增 2 个 key；详见 `CITATIONS.md`。新增项与原始论文／正式出版信息核对，LUMEN 保留预印本身份。
- 中文：`paper/paper_draft.md` 的 Background 已同步；旧中文参考文献编号与主稿原本不一致，本次按稳定 cite key 映射到 `main.aux` 的 51 项编号。
- 旧稿及被替换的 workflow-example 图存于 `before/`。旧故障统计和重建成本图移至 Motivation，复用原图文件与图注；WCT 定义移至 Motivation 开头。

## 新图来源与语义

`sources/serving_model.drawio` 是原生可编辑源；`serving_model.svg` 和原生 PNG 内嵌 Draw.io XML。主稿使用保持矢量与可提取文字的 `paper/figures/serving_model.pdf`。

这是一个构造的工作流到模型服务映射示例，无测量数据、无统计重复或误差线。图中 A1/A2、D1/D2 是相同 Agent 的不同调用；每个 fork/join 的边均保持无环。Worker 0 共置工作流 1 的 B 与工作流 2 的 E，Worker 1 共置 C/F；各 TP rank 保存这些 Agent 的局部 KV shards，而非完整 KV 的两份复制。图不指定 host 布局、故障发生时间或恢复副本放置。下方前缀示意只解释满足前缀匹配且 KV 仍可用时的跨轮次复用，不表示 cache-hit 率或长度比例。

## 实际导出检查

- 使用官方 Draw.io Desktop headless exporter 导出后查看原生 PNG，检查 DAG 边、请求派发、返回路径、rank／worker 边界以及文字换行。
- 修正了首轮字体回退：系统 fontconfig 未发现 LaTeX 安装中的 Libertine，导致 DejaVu Sans 替代和 worker 标题换行。当前导出为进程配置 fontconfig，只增加既有 TeX 字体目录，不修改系统字体设置。Libertine CFF 在 Chromium PDF 中为 Type 3 glyphs，文字仍可提取；不能仅凭空白 PDF BaseFont 字段判定字体缺失。
- 按主稿实际列宽 84.6825 mm 制作矢量 PDF；在 84.68 mm 检查时，最小文字约 10.2495 pt，未发现页外文字或内嵌位图。元数据记录：`figure-inspection.json`。
- 已查看 `review/serving_model.column-144dpi.png` 对应的实际导出与灰度图、原生 PNG，以及 `review/main-page-2.png` 的嵌入效果。新图无观察到的文字重叠／裁切，颜色之外仍有 Agent 名称、位置和线型区分。
- 已查看主稿第 3–5 页，确认 WCT 定义和被移动的两张旧图仍在相应论证附近。对旧图不重新声称全图审查或实验验证。
- 按 [EuroSys 2027 官方要求](https://2027.eurosys.org/cfp.html)检查新图的至少 10 pt 字号与灰度辨识度；本任务不作全篇投稿合规认证。

## 编译与范围检查

`build_paper.sh` 完成；最终 `main.log` 无 undefined citation/reference、无 Overfull、无编译错误。所有 `\cite`、`\ref`／`\subref` 和图片路径可解析，label / BibTeX key 无重复，`paper/` 仍有五个根 TeX 文件。已有部分其他图像缺 Description 和 `\vspace` 的 acmart 提示保留，不影响此次新图的 Description 或引用。

可复现命令（仓库根目录）：

```bash
bash benchmark/AegisKV/experiments/scripts/paper/render_serving_model.sh
sh benchmark/AegisKV/experiments/scripts/paper/build_paper.sh
```

输入、输出和脚本哈希见 `manifest.json`。无需运行仿真或新增硬件实验。
