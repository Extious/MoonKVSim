# 修订完成报告（2026-09-06）

## 本轮追加修订

恢复 Mooncake 的历史三联 Motivation，在 sglsim 找到原始 trace，并独立重建
393 条会话中的 124 个合格 workflow；旧 CSV 全部吻合。全部 10 幅图重新设计，
加入原始点、统计单位、明确尺度、灰度编码和证据边界。算法伪代码补正校准 margin
与各 tier 独立 ACK。详情见 `FIGURE_REVISION.md`。

本轮只修改稿件与图像；下述 170 次执行和测试是之前的验收证据，并未重新宣称为
本轮新运行。实机 AIMD 为 5 s、模拟为 1 s；模拟 read pin 强于原生 visibility lease，
activation→load 压力竞争仍未验证。这些差异已写入正文与 `MOONCAKE_ALIGNMENT.md`。

研究上仍未证明稳定 WCT 收益，不能称为高概率录用的投稿终稿。
`SUBMISSION_READINESS.md` 列出具体证据缺口。

## 论文与图像

最初灰阶稿的绘图脚本明确使用 `black`、`0.35` 等灰阶，正文也没有完整引入 Motivation
与 System Overview；这并非 ACM 模板限制。修订参考了 Mooncake、GhostServe、
DejaVu、KVFlow、Pythia、Strata、Cortex 的实际 PDF，补齐动机、架构、提交/恢复图，
并重绘全部定量图。所有插图为原创，未复制相关论文的图像。

最终 PDF 为 13 页：12 页正文、1 页参考文献，10 图、3 算法、4 表、17 项引用。
正文覆盖动机、设计、实现、方法、结果、实机功能验证、局限、相关工作与结论。
全部页面均已逐页查看，无溢出、未解析引用或图像裁切；图中文字按正文嵌入尺寸检查。

## 与指定 Mooncake 会话的对齐

读取了 `01a06fae-403a-7852-97c1-475ca121b4c8` 的本地原始会话，并核对实际
Controller、Router、vLLM connector/gate、HBM 实现、设计与 physical-pilot-146426。
Mooncake 为 dirty checkout，因此以逐文件哈希识别参考实现，不以 Git HEAD 替代。

修复了候选覆盖比例、4096-token prompt 切块、完成前向后的 KV 可见性、共享 ordinal
推进、请求盐与生命周期、rendezvous 绑定、HBM 配额分母、目标本地 HBM
恢复拷贝、独立主 KV 空间、模拟恢复源 pin 及容量等待。双 BYPASS 重试使用新一轮结果，
不会把旧 DRAM BYPASS 与新 HBM COMMIT 混合。

这是 prompt 路径的实现对齐；decode 保护、真实 GBDT 泛化、16-token vLLM 页、
设备时序、网络栈和物理维修均有明确边界。未将 CPU 模拟描述成实机复现。
细节见 `MOONCAKE_ALIGNMENT.md`。

## 验证与来源

| 项目 | 结果 |
|---|---|
| 定向测试 | 127 passed |
| 相关回归 | 184 passed；与定向测试存在重叠，不相加为独立测试数 |
| 原生 Controller 差分 | 260 cases PASS |
| 原生 connector finalizer 序列 | 6 sequences PASS |
| 冻结执行源码 | source-v2，383 个清单文件 |
| 新模拟 | 170/170 完整执行，每次 160 workflows / 1,304 calls |
| 原始事件独立复核 | 170/170 PASS；重新构造 WCT，复核策略、调度、故障/修复、字节与清理 |
| 最终交付一致性 | 6/6 检查 PASS，见 `data/delivery-checks.json` |
| 独立源码包构建 | 结果与逐页像素比较见 `delivery/source-build-check.json` |

精确测试命令、日志和 fixture 哈希见输出根目录 `TEST_VALIDATION.json`。
首次回归启动缺少历史 WEKA fixture 的失败日志保留，修正调用后的 184 项全部通过。
第一次启动原始验证遇到 Python tuple / JSON list 比较问题；`verification-v1`
仅修正这一行序列化比较，清单记录 diff 与哈希，执行源码及原始结果未改动。

source-v1 的测量结果已作废并保留。它的 20 个无保护参考故障计划不调用改变的
保护 gate，因此按哈希导入；170 个策略测量全部重新执行，没有复用策略结果。

## 结论与边界

- full 相对 DRAM-only 的整体平均故障罚时差为 +0.031571 s，区间
  [-0.159076, +0.222218] s；重点 workflow 为 +1.661373 s，区间
  [-2.931194, +6.253941] s。两者均未确定稳定优势。
- 健康期平均保护流量为 5496.961 GiB / 2866.586 GiB，full 增加约 91.8%。
- 三组消融与七点敏感性的整体/重点 workflow 区间全部包含零。
  Slack 改变了保护流量，但当前数据未证明稳定的 WCT 收益。
- 实机 full batch 为 56.570 s，对照 56.310 s；实际发生 HBM 恢复和清理，
  DRAM 没有自然准入。小试验不能证明性能提升，也未校准 A100 模型。
- 最大上下文 86,214 tokens，128K 桶为空；workload 是 FanOutQA 的确定性派生输入，
  不是部署中采集的完整推理轨迹。没有填充或截断来制造覆盖。

正文数字由 `write_result_sections.py` 从通过验收的统计文件生成；
`data/claim-bindings.json` 绑定数值输入、生成脚本、模板及输出正文。
图像来源与导出绑定在 `data/figure-manifest.json`。
