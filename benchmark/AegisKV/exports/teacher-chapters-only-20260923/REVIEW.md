# 老师版仅保留已提供的两章

用户要求：“老师版本只保留提供的内容Background 和 Motivation ，不要有其他版本的稿件”。本次仅收敛 `paper_teacher/`；规范主稿 `paper/` 未修改。

- 老师版根目录仅有 `main.tex` 编译入口、`background.tex`、`motivation.tex` 三个 TeX 文件。PDF 不显示继承稿标题，直接从 Background 开始。
- 移除继承的 Abstract、Introduction、Design、Evaluation、Related Work、Conclusion、AI assistance 和测量附录。Abstract、Design、Evaluation 源文件及不相关图片也从上传目录移出，不仅是取消引用。
- 保留三张原有配图 `serving_model`、`agent_value`、`kv_value` 及对应预览、14 条实际引用文献和必要的 LaTeX 支持文件。没有重画图、修改数据或增加实验。
- Background 字节完全不变。Motivation 只删除图注中指向已移除附录的括号引用，并把老师原文中指向尚未提供 Design 的末句留在注释中；其余正文不变，老师提供的禁用备选稿逐字保留。
- 构建脚本改为两章输入约定；父目录 AGENTS.md 记录最新版本范围，取代此前允许继承其他章节的老师版规则。

完整修改前老师稿、移出的源文件和图片保存在 `before/paper_teacher/`，未放回老师版目录。原主稿 44 个文件的前后 SHA-256 完全一致。

运行 `sh benchmark/AegisKV/experiments/scripts/paper/build_teacher_paper.sh` 成功，当前 `paper_teacher/main.pdf` 共 4 页：仅 Background、Motivation 及其参考文献。最终日志无未定义引用、未定义文献、重复标签或 overfull；文献长链接仍有常规 underfull 提示。

已打开实际导出的全部 4 页及第 3 页灰度预览。两栏排版正常，图 1 在第 1 页，图 2/3 在第 3 页；没有看到裁切、文字碰撞或失效引用，灰度下的纹理和线型仍可区分。第一次无标题编译未触发 acmart 的两栏模式，已在编译入口显式开启两栏并重编译。最终检查记录及文件哈希见 `review/checks.json`。
