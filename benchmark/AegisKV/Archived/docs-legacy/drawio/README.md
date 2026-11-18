# Mooncake 与 AegisKV 架构图

**最新算法 2：H/L 租值键下的一次请求、一个 KV chunk 决策（2026-09-09）。** [阅读说明](slacklandlord-patent-revised/README.md) · [完整 Draw.io](slacklandlord-patent-revised/algorithm-2-patent-revised.drawio) · [完整 PDF](slacklandlord-patent-revised/algorithm-2-patent-revised.drawio.pdf) · [单页流程](slacklandlord-patent-revised/algorithm-2-rental-management.drawio.pdf) · [逻辑与审查](slacklandlord-patent-revised/SEMANTIC_AUDIT.md)。明确以 Agent a 的请求到来、决策其中一个完整块 x 为入口。先计算 a 的收益、结算旧租金、只续租 a，再以 Q 中最小 H 与候选 H 比较；试算推进 L，新入队和复制完成时按当前 L 重建键。20 个执行节点，26 组设计算术检查含 12288 个与显式扣租的对照案例；当前为设计图核对。

**此前 SlackLandlord 讨论稿：保留租金与 Lazy Refresh。** [流程与完整符号表](slacklandlord-lazy-refresh/README.md) · [单列 PDF](slacklandlord-lazy-refresh/slacklandlord-lazy-refresh.drawio.pdf) · [Draw.io 源文件](slacklandlord-lazy-refresh/slacklandlord-lazy-refresh.drawio)。保留 Q、L、Θ、Y 等 10 类核心记号，删去重复下标与辅助函数缩写；菱形和回路展示决策，图底附速查图例，说明文档列出含义、单位与作用。这是设计草案，共享汇总和安全下界索引仍待验证。

**2026-09-07 算法三单窗口决策（保留 AIMD）：** [阅读说明](algorithm-3-guarded-aimd/README.md) · [可编辑 Draw.io](algorithm-3-guarded-aimd/algorithm-3-guarded-aimd.drawio) · [单页 PDF](algorithm-3-guarded-aimd/algorithm-3-guarded-aimd.drawio.pdf) · [PNG](algorithm-3-guarded-aimd/algorithm-3-guarded-aimd.drawio.png)。外部输入收敛为显存预算与前台性能反馈，内部维护额度和稳定计数；公式采用 LaTeX/MathJax 原生数学排版。属于待实现和验证的设计提案。

**此前从单个请求看 KV 生成与备份：** [请求流程及 Priority/Credit 说明](request-lifecycle/README.md) · [单页 PDF](request-lifecycle/request-kv-production-and-admission.drawio.pdf) · [Draw.io 源文件](request-lifecycle/request-kv-production-and-admission.drawio)。主线按较早的 revision 3 展开，历史 Credit 明确作为待选机制说明。

**此前算法 2 / 算法 3 的 revision 3 完整流程：** [五页阅读入口](algorithm-flows-v3/README.md) · [合并 PDF](algorithm-flows-v3/algorithms-2-3-complete.pdf) · [算法 2 Draw.io](algorithm-flows-v3/algorithm-2-prefix-admission.drawio) · [算法 3 Draw.io](algorithm-flows-v3/algorithm-3-foreground-budget.drawio)。算法 2 展开准入、删除闭包、异步提交与多轮共享；算法 3 展开前台预算、配额兑现、逐批许可与 watchdog。下面的 native 架构图保留较早的 SlackLandlord / AIMD 实现，版本边界见新入口说明。

2026-09-06 整理。两张新图使用相同的 Application、Router、Store Master、Worker 和 Store 布局，便于逐项比较；全部节点、文本、分组与连线均为原生 Draw.io 对象。

## 1. 原生 Mooncake 如何管理 KV

[可编辑 Draw.io](mooncake-kv-management.drawio) · [PNG 预览](mooncake-kv-management.drawio.png) · [矢量 PDF](mooncake-kv-management.drawio.pdf)

![原生 Mooncake 的 KV 管理架构](mooncake-kv-management.drawio.png)

读图顺序：

1. 应用发出请求，Router 可参考 Conductor 的 prefix 命中索引选择 Worker。Conductor 提供索引，实际路由策略属于 Router。
2. vLLM Scheduler/KV manager 拥有主 KV pages；标准 `MooncakeStoreConnector` 决定哪些 blocks 保存或加载。
3. Store Client 调用 `PutStart`；Master 分配 replica 的 segment/offset，并维护状态、租约和淘汰策略。
4. Transfer Engine 在注册 buffers 和实际 Store DRAM 之间搬运 bytes；Master 不承载 KV payload。
5. `PutEnd` 发布完整可读副本。另一个 Worker 查询并读取相同 prefix，可减少重算；对象可跨请求保留。

橙色展示 Worker A 写入 Store，绿色展示 Worker B 从共享 Store 读取。图中只画一组代表性的 Worker↔Master RPC，Worker B 同样需要查询 Master。下方两段 DRAM 表示不同 Store 节点的 segments，不是一个跨机器连续地址空间，也不表示每个对象必须恰好写两份。

原生 Mooncake 的租约、副本、缓存淘汰和传输错误处理是既有能力。可选 SSD offload、Store HA、复杂 P/D 拓扑及 TE endpoint metadata 服务未在本图展开。

## 2. 增加 AegisKV 后的具体实现

[可编辑 Draw.io](mooncake-aegiskv-implementation.drawio) · [PNG 预览](mooncake-aegiskv-implementation.drawio.png) · [矢量 PDF](mooncake-aegiskv-implementation.drawio.pdf)

![AegisKV 在 Mooncake 上的实现架构](mooncake-aegiskv-implementation.drawio.png)

蓝色为沿用的 Mooncake/推理引擎能力；紫色为新增或扩展的 AegisKV 模块；橙色为保护写入，绿色为加载/恢复。虚线表示控制、元数据、quota 或反馈，不承载 KV bytes。Application 内和底部流程的短箭头表示处理顺序。

| 增加位置 | 当前实现 | 作用 |
|---|---|---|
| Application | `application/algorithm1.py` | 用因果特征预测残余时长，CPM 计算并校准 Slack，附到 LLM request；缺失结构或预测时取零 |
| Router | `router/state.py`、`router/server.py` | Rendezvous 选择 primary/兼容备用 Worker；维护 request salt、route version、输出 fence、恢复顺序和结束清理 |
| Store Master | native `AegisController`，由 Master 持有并通过 RPC 暴露 | Algorithm 2 SlackLandlord、请求/tier/chunk 状态、恢复计划、Algorithm 3 HBMQuotaAIMD；内部 mutex 串行处理元数据 |
| Source Worker | `AegisKVConnector`、`vllm/gate.py` | 在 forward 完成后 seal 4096-token prompt / 256-token decode chunks；共享 ordinal gate，分别执行 HBM/DRAM 准入与复制确认 |
| 备用 Worker | `vllm/hbm.py`、`vllm/aimd.py` | 承载 Peer-HBM slots、实施配额并反馈压力；恢复时实际复制到独立 vLLM 主 KV slots |
| Store DRAM | 原生 Store Client/TE + Aegis 请求保护目录 | 承载直接来自 Source 的 DRAM 保护对象；独立提交和独立清理 |

图中三个编号表示：

- **① HBM 保护**：Source buffers → Router 绑定的 Peer-HBM target。
- **② DRAM 保护**：同一 Source buffers → Store DRAM；路径从图的底部绕过备用 Worker，明确没有 Peer-HBM→DRAM destage。
- **③ DRAM 恢复**：目标 Worker 先尝试已提交的本地 Peer-HBM，再加载 DRAM 中可用的剩余 keys；缺失 suffix 重算。

两层分别产生 `PENDING → COMMITTED / ABORTED`。组合结果为 `HBM_ONLY`、`DRAM_ONLY`、`HBM_AND_DRAM` 或 `BYPASS`。共享 ordinal 是当前 connector 的限制：一层提交而另一层 bypass 时，落后的层会被 seal；两层都 bypass 时可重试同一块，但必须使用本轮的新结果。请求结束需等待 pending 到终态，然后回收私有保护。

本图描述真实 Mooncake/vLLM prototype 的模块关系，**不是 MoonKVSim 的 GPU 部署图**。逻辑 Source→Peer copy 在 4090 pilot 中通过 host-staged TCP/D2H/H2D 实现，不能据图认定已验证直接 CUDA P2P、NVLink 或 RDMA。图中正时间 HBM load 对应 `load_local_batch` 的真实复制，备份与恢复主 KV 不能算作同一块显存。

## 3. 找到的旧图

已将四份源文件原样复制到 `references/`，逐份验证 SHA-256；具体原路径和哈希见 [历史图来源清单](references/MANIFEST.json)。

| 保存的旧图 | 用途及边界 |
|---|---|
| [共享 KV：vLLM / SGLang / Mooncake](references/mooncake-shared-cache-vllm-sglang-integration.drawio) | 之前绘制的详细共享缓存架构，包含 Conductor、TE endpoint metadata、物理 segments，以及 SGLang L1/L2/L3 路径 |
| [AegisKV System Design v2](references/aegiskv-paper-system-design-v2.drawio) | 之前的三层设计图；本次参考其分层和源侧独立 HBM/DRAM 路径 |
| [早期 Master-centric 三页图](references/historical-aegiskv-master-vllm-mooncake.drawio) | **历史方案**，仍有早期 deadline、SSD、demotion 等语义；保留供追溯，不作为当前实现说明 |
| [本轮论文精简总览](references/paper-simulation-system-overview.drawio) | 当前论文中的精简图；本次新图增加了对象管理、实际模块和恢复加载细节 |

旧图未被覆盖，新图也没有改动论文交付包中的源图。

## 4. 当前实现依据与图示边界

- [Mooncake Store 设计](/home/comp/zhanzhao/Mooncake/docs/source/design/store/mooncake-store.md:22)：Master/Client、Put/Get、replica、租约与淘汰。
- [原生 Conductor](/home/comp/zhanzhao/Mooncake/docs/source/design/conductor/conductor-architecture-design.md:3)：prefix 索引与 Router 的职责区别。
- [AegisKV 当前设计](/home/comp/zhanzhao/Mooncake/benchmarks/aegiskv/design/current_design.md:5)：独立层准入、SlackLandlord、AIMD 和恢复协议。
- [native Controller](/home/comp/zhanzhao/Mooncake/mooncake-store/src/aegiskv_controller.cpp:1388)、[Master 归属](/home/comp/zhanzhao/Mooncake/mooncake-store/include/master_service.h:184)、[RPC 接入](/home/comp/zhanzhao/Mooncake/mooncake-store/src/rpc_service.cpp:1581)。
- [AegisKVConnector](/home/comp/zhanzhao/Mooncake/benchmarks/aegiskv/src/aegiskv/vllm/connector.py:257)、[共享 ordinal gate](/home/comp/zhanzhao/Mooncake/benchmarks/aegiskv/src/aegiskv/vllm/gate.py:1266)、[实际 HBM 恢复 copy](/home/comp/zhanzhao/Mooncake/benchmarks/aegiskv/src/aegiskv/vllm/hbm.py:2010)。
- [三方设计实现对比文档](../../../../docs/development/mooncake-aegiskv-three-way-design-implementation.md)：更完整的算法公式、源码映射与实机/模拟差异。

图示没有将 AegisController 的查询 snapshot 表述为已接入原生 Store HA 的 durable checkpoint；没有声称 Worker recovery lease 和模拟 read pin 完全等价。实机 pilot 的 AIMD 周期是 **5 s**，当前模拟是 **1 s**；本图不通过省略数值暗示两个配置相同。相关实机压力回收、HA、TP/PP 恢复与流输出竞态的验证范围见三方对比文档。

## 5. 编辑和重新导出

用 Draw.io / diagrams.net 打开两个 `.drawio` 文件即可编辑。图形是真正的 parent-child 分组，移动 Master、Worker 或 Application 会带着内部模块移动。生成脚本为 [build_architecture_diagrams.py](build_architecture_diagrams.py)；直接编辑 Draw.io 后不要运行生成脚本覆盖自己的修改。

导出使用本机官方 Draw.io Desktop CLI，而非近似渲染器。PNG 和 PDF 均嵌入 diagram XML，可在 Draw.io 中再次打开。

```bash
# 在仓库根目录运行；以下以原生 Mooncake 图为例。
python benchmark/AegisKV/docs/drawio/build_architecture_diagrams.py
/home/comp/zhanzhao/.codex/skills/drawio/scripts/drawio-cli \
  -x -f png -e -b 20 -s 1.25 \
  -o benchmark/AegisKV/docs/drawio/mooncake-kv-management.drawio.png \
  benchmark/AegisKV/docs/drawio/mooncake-kv-management.drawio
/home/comp/zhanzhao/.codex/skills/drawio/scripts/drawio-cli \
  -x -f pdf -e --crop -b 20 \
  -o benchmark/AegisKV/docs/drawio/mooncake-kv-management.drawio.pdf \
  benchmark/AegisKV/docs/drawio/mooncake-kv-management.drawio
```

内容版本、源代码哈希、导出文件哈希及检查结果见 [MANIFEST.json](MANIFEST.json)。

## 论文图像修订入口

[paper-figures](paper-figures/README.md) 收录恢复的三联 Motivation、英文 System
Overview 和提交/恢复机制图。它们与本目录两张详细中文架构对照图用途不同；
正文图强调论文中需要解释的机制，中文图保留更细的实现与路径对比。
