# 本机 SGLang 稀疏注意力图

同日新增：[NOSA-1B 真实 GPU 逐层选块轨迹](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/docs/paper/NATIVE_SPARSE_TRACE_20260914.md)已完成。真实热点集中度应引用这批模型观测；下列 SGLang 构造参考图继续用于解释机制。

本轮依据 `/home/comp/zhanzhao/sglang` 的 DSA / HiSparse 实现，生成三张图和可复算参考输出：

1. [逐 Query、逐层选择与位置频次](/home/comp/zhanzhao/MoonKVSim/output/pdf/sglang-sparse-20260914/sglang-per-query-selection.png)。
2. [逻辑选择到物理备份块的映射](/home/comp/zhanzhao/MoonKVSim/output/pdf/sglang-sparse-20260914/sglang-selection-to-physical-blocks.png)。
3. [HiSparse 已有 Decode 装入路径与拟议 Retry Prefill 扩展](/home/comp/zhanzhao/MoonKVSim/output/pdf/sglang-sparse-20260914/sglang-hisparse-recovery-path.png)。

完整图注、代码来源、环境边界和复算命令见[交付说明](/home/comp/zhanzhao/MoonKVSim/output/pdf/sglang-sparse-20260914/README.md)。前两张来自明确构造分数上的本机 SGLang PyTorch Top-k 参考计算；第三张来自源码。它们解释机制，不能作为真实模型热点集中或故障 WCT 改善的观测。

与当前方法的关系：已有 HiSparse 提供少量 GPU KV 与完整 Host KV 的正常 Decode 管理；当前论文仍需实现并评价固定 Retry DP、备份可靠性、重试 Prefill 的分层装入与 WCT/Slack 驻留决策。接口背景见[请求内 KV 方法规格](REQUEST_KV_POLICY_SPEC_20260914.md)。
