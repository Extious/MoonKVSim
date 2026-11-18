# 论文辅助脚本

## 当前中文初稿

[Paper_Draft.md](../../Paper_Draft.md) 的正文源为
[agent-lease-draft.md](templates/agent-lease-draft.md)，中文图注在
[agent_lease_draft_captions.py](agent_lease_draft_captions.py)。
本轮固定为 Motivation 3 张、System Design 1 张、Evaluation 8 张。
重画新视图先执行 [render_compact_paper.py](render_compact_paper.py)，仅重组已有数据，
不启动实验。旧全量生成器执行后也须执行此渲染器，以恢复紧凑版 Overview。
修改正文源后执行 [build_agent_lease_index.py](build_agent_lease_index.py)，同步初稿、
连续图号、导航及图像来源记录。该入口沿用冻结数据，不启动实验或修改算法实现。

可选浏览器预览使用系统 Python 的 markdown-it / mdit-py-plugins，以及
tmp/figure-browser 下的 Playwright 和 KaTeX 0.16.22。
先执行 [render_agent_lease_markdown.py](render_agent_lease_markdown.py)，再运行
tmp/figure-browser/review-agent-lease.cjs。正文中的 Markdown 数学公式不依赖此预览环境。
图像内容未变时复用已有 PDF 查看记录，重新核对正文、图注和 Markdown 排版。

## 原有 8B LaTeX 修订稿

所有命令从仓库根目录执行，使用项目 `.venv/bin/python`。
`paper_paths.py` 统一定位论文、图像数据、说明文档和构建产物。

```bash
# 从已有统计生成结果文字和宏
.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/write_result_sections.py

# 由保存的输入重绘当前图像
.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/render_submission_figures.py
.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/build_submission_diagrams.py

# 绑定图像来源，检查交付资料，再打包并独立构建源码包
.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/record_figure_manifest.py
.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/verify_delivery.py
.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/package_delivery.py
.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/verify_source_bundle.py
```

这些工具不启动模拟实验。图像或论文 PDF 改变后，`verify_delivery.py` 会要求更新与之对应的
视觉检查记录；重绘后需完成检查才能打包。更多环境和原始事件审计命令见
[REPRODUCE.md](../../../docs/paper/REPRODUCE.md)。
