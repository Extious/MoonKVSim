# 最后一轮独立版面预检：12 技术页，但不是 v3 数值定稿

**Primary 数字、表 1、图 8 和相关归因仍为旧 v2，并含 TODO。本目录是 layout preview，不是 v3 结果验收或 paper-ready 判定。** PDF 页眉明确标注 `LAYOUT PREVIEW: primary results remain v2 (TODO)`。

本轮准确快照为 2,766 whitespace tokens，SHA-256 `89caa9ec52c0cbbb0b34ad66f3fd05cf1b6088913cd404b1f319ff6b676b7dfb`。直接编译此快照已达到 **12 个技术页**，无需在副本中再压缩任何文字。

| 项目 | 实测结果 |
|---|---|
| PDF 总页数 | 14 |
| 最后含技术内容的页 | 12 |
| Native Figure 11、图注 | 第 12 页 |
| 完整 Scope of the Evidence | 第 12 页 |
| References 起点 | 第 12 页右栏末尾 |
| 第 13、14 页 | 仅参考文献；第 14 页是最后一条参考文献的三行延续 |
| Overfull hbox/vbox | 0 |
| Underfull hbox/vbox | 18，非致命 |
| 最终日志未定义引用/引文 | 无 |

此页数按最后一处技术文字、图和图注统计，没有把 References 开始当作技术页结束。此前两份预检分别保留了 13 技术页的快照和仅前移 float 的独立试排；本次源中已提前 native figure 声明，并完成 root 的正文压缩。

## 构建与实际查看

将原 paper 完整复制到本目录 `paper/`，逐字节使用 `evaluation-v3-draft.snapshot.tex` 替换 `evaluation.tex`；仅增加预览页眉并复制已封存 native 图为 `figures/eval-native-component.pdf`。没有改变正文、图尺寸、字号、行距或页边距。构建命令：

```sh
latexmk -pdf -interaction=nonstopmode -halt-on-error -outdir=../build main.tex
```

交付 PDF 为 `LAYOUT_PREVIEW_NOT_V3_RESULTS.pdf`。`renders/` 保存全部 14 页的 96 dpi PNG/提取文本，以及 native 所在第 12 页的 96/144 dpi 彩色、灰度图。

本轮实际查看第 8、11、12、13、14 页及第 12 页灰度版本：新增 native 图及图注没有可见裁切、标签碰撞或遮挡；正负方向、三类 marker、分类 compute 设置和三文档范围可读。源宽 178 mm、文字 10.3 pt，按原论文 177.8 mm 正文宽嵌入后约为 10.289 pt。第 12 页保留 native 的不利结果与全部 Scope 边界。原 paper 其他页面不在本轮新增科学复核范围内。

正文的 Context/queueing、训练/guard、旧 service-proxy 与新 walltime 版本区别，以及 component 非 native-kernel/WCT 的证据边界仍在本快照中。此处仅确认这些内容在版面中保留，不替代数值、代码或实验归因审计。

## 后续限制

当前 12 技术页成立于该精确快照和现有旧 primary 图表尺寸。v3 primary 数字、表、图与归因替换之后必须重新构建和查看；不保证新增文字仍能保持 12 页。无需为消除参考文献尾页而删引用、缩字号或改前文。没有进一步压缩候选被应用。

## 来源保全

结束时复核：原 paper 28 个文件、第一份预检 75 个文件、第二份预检 138 个文件和 native 图包 18 个文件均与先前哈希一致。live draft 未被本代理修改，原 paper/图/冻结实验数据未改，没有新 DES。

`SOURCE_SNAPSHOT.json` 记录来源和旧 seal；`BUILD_INSPECTION.json` 记录各页内容及编译警告；`LAYOUT_REVIEW.json` 和 `SEAL.json` 记录实际审查范围与本目录全部文件哈希。
