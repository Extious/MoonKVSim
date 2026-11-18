# Overleaf 前半篇同步记录

用户指定：Overleaf 中 Motivation and Challenges 及此前内容为最新版本；Design 及后续保留本地。

## 已同步

- 摘要、引言、Background、Motivation and Challenges 正文和图注来自上传 ZIP。
- Overleaf 两个章节文件合并到本地 `background_and_motivation.tex`，维持四个根 TeX 文件；main 中仅相应合并 input。
- 将源稿中的 Markdown 粗体／斜体转换为等价 LaTeX 格式；未润色或重写英文内容。
- 六个前置图资产中，仅 recovery-cost.pdf 与本地不同，已导入 ZIP 版本并重新生成中文预览 PNG；其余图和 Design／Evaluation 资产保持原样。
- 保留本地 references.bib：ZIP 缺少正文引用的 InfiniteHBD 条目，其余条目与本地相同。
- 中文完整译稿仅更新前半篇语义内容；全文参考文献编号随编译调整。AutoGen 不再被引用，已从显示文献列表移除；bib 数据库条目保留。

## 保留范围与验证

- system_design.tex、main.tex 从 system_design 输入起至文末的内容，均与同步前逐字节一致。
- 中文 Design 至 Conclusion、附录仅重新编号引用；未改正文语义。
- 保存完整同步前纸稿目录、导入源文件、文本差异、文件 SHA256、前后 aux 和编译日志。
- 编译成功：23 页；无未定义引用或 overfull box。逐页查看前五页及导入图的最终宽度预览，没有裁切或重叠。
- 导入稿缺少 Figures 1、2、4 的 Description，acmart 会提示可访问性警告；另有原有 vspace 和 underfull 提示。此轮按版本同步，不擅自恢复作者删去的描述。

## 已发现并按指定版本边界保留的差异

1. Overleaf 摘要／引言仍写下层完整 checkpoint 加 Peer 复制、逐请求可变层深度和直接重评；本地 Design 已采用跨层独占 owner、固定 Peer 配额和惰性可续租信用。前后尚需未来写作任务统一，本次没有覆写 Design 或改写用户指定前文。
2. 导入 Figure 3 纵轴为 `Prefill (s)`，但导入图注使用包含读取的 KV reconstruction time。忠实保留上传资产，本次未重新绘图。

所有量化数据沿用来源，此次同步没有运行新实验。
