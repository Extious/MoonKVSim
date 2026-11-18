# Serving 图两处高度批注

按用户最新两处 PDF 批注修改 C→F 的下绕线和 runtime/Router/worker 间隔。七个节点、图内显示标识、八条依赖和其余七条 DAG 箭头保持不变。worker/rank/KV 内容只整体上移；字体、尺寸、绿色/斜线编码和单行页脚保留。

当前单栏图 84.68×77.42 mm，之前为 84.68×82.19 mm（降低 5.80%）；最小字号仍约 10.24 pt。runtime 到 worker 跨度由 68 减至 48 源单位（减少 29.41%）。原生 SVG 的 14 个箭头均连接连续直线段，最短可见直段为 7.03 源单位；新版缩短间隔是用户明确请求，覆盖以前 26 单位长箭头的间隔规则。

生成入口与编辑源仍在 `../workflow-motivation-measured-20261005/`。发布图为 `../../paper/figures/serving_model.pdf`。`before/` 和 `BEFORE_SHA256.json` 保留本轮前稿。`review/SPACING_AUDIT.json` 保存源比对、箭头及字号核验；原生彩色/灰度图和 canonical 主文第 2 页均已查看。沿用 `experiments/scripts/paper/build_paper.sh` 编译现有 `paper/main.tex`，没有 LaTeX 致命错误、未定义引用或溢出；保留既有 class/参考文献地址提示。当前没有内置 `compile_latex_document` 接口。

`LESSON.json` 和项目 `AGENTS.md` 已记录本次局部布局纠正。全局经验库既存 `20260923T213943533276Z-d9d508c58b-scientific-figure-aegiskv-technical-page-count-includes-late-floats.md` 指纹不匹配，禁止追加；未重算旧指纹或换目录绕过。
