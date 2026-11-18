# Worker 0 的 A/B 行顺序

按用户 main.pdf 第 2 页批注，将 Worker 0 两个 TP rank 的 KV 行都改为上 A、下 B。每个 Agent 的整行 K/V 及原有条形长度、斜线和字母一起移动，未改变历史归属。源比对确认仅 44 个行内对象平移，上方 workflow、Router、Worker 1、容器与页脚等 80 个对象保持完全一致。

生成入口和编辑源仍在 `../workflow-motivation-measured-20261005/`；规范发布文件是 `../../paper/figures/serving_model.pdf` 和 `../../paper/main.pdf`。图尺寸仍为 84.68×77.42 mm，最小字号约 10.24 pt。Background 的可访问描述同步更新了两行顺序。

原生彩色/灰度导出与本地最终主文第 2 页均已查看。现有项目构建脚本编译同一 main.tex 通过，仍为 12 页，无致命错误、未定义引用或溢出。当前没有 `compile_latex_document` 工具，本地成功不表示此前依赖缺失的在线预览已修复。

`before/` 保存本次前稿；`review/ROW_ORDER_AUDIT.json` 保存比对和编译证据。`LESSON.json` 和项目 AGENTS.md 记录了单图行顺序纠正。全局经验库的既存旧记录指纹异常仍阻止追加，未改旧指纹或绕过存储保护。
