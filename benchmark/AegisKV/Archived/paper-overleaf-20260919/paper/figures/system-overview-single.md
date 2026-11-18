# 单栏 System Overview

此文件描述已撤下的纵向单栏候选 `system-overview-single.drawio`。
2026-09-18 用户要求保留原图比例，正文现使用 `system-overview-v11.drawio.pdf` 等比缩至单栏。
以下为该候选的历史布局与导出记录：
Applications / Control plane / Inference engines 三层不变；Router 与 Controller 分离，
Planner 决策放置和传输，Adapter 调用 Connector 执行。DP0/DP1 均保留 Adapter、Connector、
较大的 Local KV 和较小的 Peer KV。蓝色路径跨 DP，金色路径独立连到 Shared DRAM。

小型 DAG、Slack 条带、Planner 的 R/D/P 与块选择矩阵、Local KV 的逐层块布局、
未密封尾部与并发 retry 分叉均为设计示意。图内尺寸不代表测量数据或实际容量比例。
黑底 1–4 各出现一次；4 仅标 DP0 Adapter，位于独立 `Paper annotations` 图层。

原生画布 700 × 1268；在当前 84.65 mm 单栏宽度下最小 PDF 字体约 10.60 pt。
审阅了原生 PNG、最终宽度的 PDF 渲染，以及整稿第 5 页；修正了 Planner 标签换行、
HBM 标签与本地读写箭头相交、DAG 元数据线穿过 Controller 标题等初版问题。
PDF 保留矢量图元，无位图替代；PNG/PDF 均嵌入 Draw.io XML。源文件保留便于直接编辑。
v11 的原图与生成器仍在，未覆盖。

```sh
.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/build_system_overview_single.py
/home/comp/zhanzhao/.codex/skills/drawio/scripts/drawio-cli -x -f png -e -b 0 -s 2 -o benchmark/AegisKV/paper/figures/system-overview-single.drawio.png benchmark/AegisKV/paper/figures/system-overview-single.drawio
/home/comp/zhanzhao/.codex/skills/drawio/scripts/drawio-cli -x -f pdf -e --crop -b 0 -o benchmark/AegisKV/paper/figures/system-overview-single.drawio.pdf benchmark/AegisKV/paper/figures/system-overview-single.drawio
```

直接编辑 Draw.io 后应重新导出；再次运行生成器会替换手工改动。
检查记录位于 `output/pdf/aegiskv-single-column-20260918/`。
