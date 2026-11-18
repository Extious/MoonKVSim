# 原主稿同步老师结构

用户最新指令为“原主稿也严格依照老师的思路”。因此，本次将此前独立的 `paper_teacher/` 中已完成的老师章节与配图接入规范主稿 `paper/`。这一指令取代了上一步暂时保留原主稿不动的版本边界。输入是用户提供的 Background 和 Motivation 两段原文，并非实时读取 Overleaf。

## 本次调整

- `paper/background.tex` 与老师版一致；`paper/motivation_and_challenge.tex` 保留既定文件名，但正文标题与结构改为老师的 Motivation：完整 KV 保护成本、O1 Agent 恢复价值、O2 KV 区域恢复价值、O3 复制容量变化。
- 对照用户附件核验：除补充引用与 figure 环境的说明外，两章实际生效的英文正文保持不变。老师放在 `\iffalse` 内的旧稿也逐字保留。原版六个根 TeX 文件结构与构建入口保留。
- 接入已审查的 `agent_value.pdf` 和 `kv_value.pdf`；沿用现有 `serving_model.pdf` 及 DP+TP `system-overview.pdf`。恢复成本图以 `context_recovery.pdf` 放在附录 A；前缀复用图归入 Router。必要的后文引用及 `\system` 定义与老师版同步。
- `paper/paper_draft.md` 翻译新的 Motivation，保留老师的论证顺序和证据限定，同步 Background 图注及后文引用。图号 1–16、公式 1–7、参考文献 1–33 与新 LaTeX 编号一致。原先被附录隔开的参考文献重新集中排列，图和算法的失效锚点已补齐。
- 原来的七项不再引用的 Motivation 图及其 PNG 已转存到 `before/paper/figures/`；原始数据和可编辑图源仍在既有实验、导出目录。前一版主稿 PDF 和修改前文件保存在 `before/`。
- Abstract、Evaluation 与 `references.bib` 未改动。两版当前全部英文内容相同，唯一源文件差别是主文件中的 Motivation 输入名；其他章节仍是此前按用户选择继承的正文。

## 验证

构建：`sh benchmark/AegisKV/experiments/scripts/paper/build_paper.sh`，输出 `paper/main.pdf`。共 18 页，无未定义引用、未定义文献、重复标签或 overfull hbox。既有 acmart vspace 与未使用 subfigure caption 设置提示仍在。

`review/checks.json` 保存附件原文及输出哈希、正文一致性、被禁用稿保留状态、图号与页码、图片路径和 Markdown 锚点检查。对照两版 PDF，逐页提取的文字完全相同。

实际打开并查看了原主稿第 2 页 serving model、第 4 页 O1/O2、第 5 页 DP+TP Overview、第 17 页附录成本图，以及第 4 页灰度渲染。图形未发生裁切或文字重叠；吸收延迟/新增 WCT 仍可借助纹理区分，稀疏模型曲线仍有不同线型和标记。两张 Motivation 图按约 84.68 mm 单栏宽度放置，最小原生文字为 10.25 pt，矢量图没有嵌入位图。页面预览在 `review/`。

没有新增测量或重新绘制统计图。证据边界沿用 `../motivation-teacher-20260923/figure-manifest.json`：重建时间为实测，分支 WCT 增量为固定其余执行条件的计算，O2 的重叠时间线为示意；完整保护成本图的测量条件仍在附录。编译和版式检查不构成新系统性能验证。
