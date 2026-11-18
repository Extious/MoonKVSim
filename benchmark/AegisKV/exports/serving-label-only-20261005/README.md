# Workflow 只改标识的纠正

用户澄清：“我的意思是workflow 的图像不变，变的只是标识”。本次恢复 `../serving-compact-order-20261005/before/` 中批注原图的 runtime 框、节点坐标、端口和全部箭头路径，只用显示别名将字母按列排成 A/B/C、D/E、F、G。下方 KV 所属 Agent 同步显示同一别名；实验 Agent ID 和其他图没有重命名。

保留单行 tokens/KV 图例这一独立布局修改。最终图 84.68×82.19 mm，最小字号 10.24 pt；14 个原生箭头与连续直线段对齐连接。`review/LABEL_ONLY_AUDIT.json` 比对了 18 个 runtime/节点/边对象（仅节点文字不同），以及 6 个 KV 所属 Agent 标签。原生源和生成入口仍在 `../workflow-motivation-measured-20261005/`，发布图为 `../../paper/figures/serving_model.pdf`。

现有 `paper/main.tex` 通过项目原编译脚本构建；最终 12 页主文的第 2 页已在彩色和灰度下查看。当前接口没有 `compile_latex_document` 工具。

`before/` 保存本轮改动前的中间版本；其节点重排已被本次澄清覆盖。`LESSON.json` 记录本次项目内纠正。全局经验库因既存记录的指纹不匹配阻止追加，未改旧指纹或换目录绕过。
