# Teacher Design: partial replicas and invocation histories

本次按 2026-09-23 用户两项纠正修改 `paper_teacher/system_design.tex`、算法及三张 Design 图。老师提供的 Background、Motivation（含禁用段落）逐字保持；当前老师稿仍只有 Background、Motivation、System Design 和参考文献。其他版本章节没有进入老师稿。

| 需求 | 本次正文与图中的处理 |
|---|---|
| 两层 selected 后再放置 | O1 产生 Agent history 候选，O2 产生 KV region 集合，之后分配 Peer HBM/DRAM；不先建立完整 DRAM 检查点。算法按相同顺序执行。 |
| DRAM 也是部分备份 | 稳态 `S = H ⊎ D`；原执行 KV 单独计量，迁移期间的两份物理分配同时计量。任一层及两层并集都不要求完整。 |
| 前 L 层优先 Peer | 仅已选且位于前 L 层的区域进入 Peer 候选；空间不足放 DRAM，已选的更后层区域也放 DRAM。有限 DRAM 不足时重新选择并计入重建代价。 |
| 一个节点一次 invoke | 节点身份是 `(workflow, Agent, invocation)`。新图使用 `A(1)`、`A(2)` 区分调用序号，避免与原 Motivation 的 Agent 名称 `A1`、`A2` 混淆。 |
| 同一 Agent 后续调用复用 | 历史 manifest 和引用跨调用存续；一次调用结束不直接释放其 KV。按精确公共 token 前缀及模型/布局检查兼容性；不按调用数重复分配物理副本。 |
| 部分备份的恢复路径 | 缺失区域按模型原生依赖闭包重建，计入底层激活、因果前驱和 selector 状态；引擎不支持部分恢复时明确全前缀 Prefill，不能虚报跳过重算。 |
| Peer 缩容 | 仍然选中的区域先预留 DRAM、完成复制并发布新 owner，再等读者退出后释放 HBM；没有默认存在的完整 DRAM 后备。 |

O1 继续保留共同故障、多恢复资源竞争和 join 非加性；增加正常连续调用复用的同一工作流时间线。`lambda` 与源故障权重是声明的策略参数，不是测得的故障概率。O2 的访问频率仍以原生选择单元和因果可见机会归一化，只用于产生候选。O3 只调每 rank 总配额，`L` 是模型/布局配置。

## 图的来源和可支持的结论

三图都是设计示意，独立实验数量、重复数和置信区间不适用；不证明局部重建已经实现或 WCT 已改善。

- `teacher-system-overview` 沿用现有 DP/TP 部署几何，改成选 Agent / KV 与部分 DRAM；A(1)、B(1)、C(1)、A(2) 均为调用。
- `teacher-invocation-reuse` 新建连续调用 A(1) → A(2) → A(3)；绿色条是兼容逻辑历史，不表示这些历史的全部 KV 已备份。`E2 = U2 + accepted A(2) output`。
- `teacher-selective-recovery` 使用 `data/selective-state.json` 中的构造状态：12 个区域选 5 个，Peer 2 个、DRAM 3 个；L=2、Peer 两区域的容量下，L2/B1 回退 DRAM。H/D 不重叠、并集等于选中集合，7 个区域没有备份。区域均代表所需 TP shards，不能把 5 个区域误记为 5 个 rank 对象。

可编辑源在 `sources/`，原生 Draw.io PNG/PDF 在 `figures/`，最终论文只使用 `paper_teacher/figures/` 下的 PDF 与预览。调用序号用括号，token block ID 仍用 B0/B1/B2/B3。

## 核对结果

- `review/check_revision.py` 的 19 项有限检查全部通过，包括源图与数据一致、前 L 层限制、溢出放 DRAM、连续调用边、引用与编译检查。
- 与修改前 manifest 比较：老师两章不变，canonical `paper/` 全部 44 个文件及文件集合不变。
- 最终 `paper_teacher/main.pdf` 为 8 页。没有未定义交叉引用、引用文献、LaTeX 错误或 Overfull box。已有参考文献的 underfull 行和 ACM 对算法周围间距的提示未影响已检查页面。
- 实际查看了三张原生 PNG，Design 实际页面 3–7 及参考文献页；最终第 4、6 页还检查了灰度。字号、文字边界、图注、公式、TP 对应关系和算法换行已核对。
- 最终单栏宽 84.6825 mm，三图最小文字分别约 10.170、10.160、10.170 pt，均为矢量 PDF，无嵌入位图。灰度使用 S/H/D 和位置区分，不单靠颜色。
- `review/checks.json` 保存 PDF hash、具体有限检查和字体尺寸；本次是设计稿、图文语义和排版验证，没有运行新的服务实现、故障实验或性能矩阵。

复核命令（仓库根目录）：

```bash
bash benchmark/AegisKV/experiments/scripts/paper/render_teacher_design.sh
sh benchmark/AegisKV/experiments/scripts/paper/build_teacher_paper.sh
python3 benchmark/AegisKV/exports/teacher-partial-replicas-invocations-20260923/review/check_revision.py
```

修改前老师稿和脚本在 `before/`。它们只用于追溯，不属于老师上传目录的现行稿件。
