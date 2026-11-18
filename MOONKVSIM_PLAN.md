# MoonKVSim：基于 vLLM 与 Mooncake 的全局虚拟时钟 KV 模拟器实施计划

> 文档状态：规划草案
> 目标项目：`MoonKVSim`
> 推荐仓库路径：`/home/comp/zhanzhao/MoonKVSim`
> 基线分支：`main`
> AegisKV 分支：`aegiskv`
> 时间模型：单一全局虚拟时钟、离线离散事件模拟（DES）
> AegisKV 设计权威：`benchmark/AegisKV/docs/patent/AegisKV专利交底书-final-version.docx`
> 更新时间：2026-08-30

## 0. 交付范围修订：纯全局虚拟时钟模拟

本项目的当前交付范围以用户在 2026-08-30 的明确要求为准：只实现和运行
单一全局虚拟时钟驱动的离线元数据 DES，不执行任何真实 GPU、CUDA、Slurm、
vLLM/Mooncake 端到端或组件物理校准实验。

- 第 9 节“物理资源模型”表示模拟器内逐 GPU、HBM、DRAM、copy engine、NIC、
  fabric 和传输 lane 的逻辑资源身份、容量账本与可用时间日历，不表示访问真实设备。
- Vanilla/AegisKV 对比、故障、消融和敏感性实验均为 CPU 上的全局 DES 重放。
- forward、传输和网络参数可以使用源码派生值或显式的 modeled/assumed 参数；每个
  结果必须保留参数来源，并标记 `modeled/preliminary`、`not_calibrated`。
- 当前 Definition of Done 的证据上限为 E2。E3 组件物理校准、E4 实机 matched
  validation 和 E5 paper-ready claim 均不属于本次交付门槛。
- 未完成的物理/正式 provenance blocker 必须保留，不得伪装为已解决；它们只禁止
  calibrated、physical、formal 和 paper-ready 声明，不阻止明确限定为 E2 的模拟实验。

## 1. 执行摘要

MoonKVSim 是一个新的、独立于 SGLSim 的纯元数据离散事件模拟器。它以固定版本的 vLLM 为推理引擎语义来源，以固定版本的 Mooncake Store 和 Transfer Engine 为 KV 存储与传输语义来源，以 AIConfigurator 预测 GPU forward 时间，并用一个全局虚拟时钟统一推进所有 DP rank、GPU、Store、网络、故障和恢复事件。

项目分两步实施：

1. 在 `main` 分支实现并验证 Vanilla Mooncake baseline，包括真实 multi-agent trace 重放、最高 128K 上下文、vLLM-style continuous batching、GPU KV block 生命周期、Mooncake 全局 Store、跨 DP rank KV 复用、DRAM 容量和传输竞争。
2. 在 `main` 达到基线验收标准并发布 `v0.1.0-mooncake-baseline` 后，从该 tag 创建 `aegiskv` 分支，在同一个 KV 目录和物理数据平面上实现 AegisKV unified KV management、Peer-HBM、SlackLandlord、故障 reroute 和恢复。

最重要的架构边界是：

- `main` 不包含任何 AegisKV 策略，以保证 Mooncake baseline 可独立验证。
- `aegiskv` 不建立第二套备份目录；cache reuse 和 failure protection 必须共享唯一 KV 真相源。
- AegisKV 语义以随仓库保存的专利终稿为最高权威；Mooncake 与 SGLSim 中的旧设计、代码和实验仅作为实现映射、历史与证据来源，发生冲突时不得覆盖终稿。
- 不建立持久的 vLLM 私有 Host L2。Host staging buffer 只是传输临时空间；由 Store 管理的本机 DRAM 属于全局 Store DRAM pool。
- AIConfigurator 只预测 GPU forward；Store DRAM、网络、RPC 和恢复时间由独立资源模型产生。
- 设计同步、代码实现、单元测试、模拟结果、真机校准和论文证据必须分别报告。

## 2. 项目目标

### 2.1 功能目标

MoonKVSim 最终需要支持：

- 多节点、多 GPU、多 DP/TP/PP rank 的 vLLM-style 推理部署；
- continuous batching、chunked prefill、decode、preemption 和 recompute；
- 使用真实 multi-agent workflow trace，保留 agent、会话、依赖、tool call、时间戳和source token/hash字段（原文可用时同时保留），并重放最长 131,072-token 上下文；
- GPU HBM 中按 block/page 管理的 active KV 和 prefix KV；
- Mooncake Store 的全局 key、replica、DRAM segment 和 eviction；
- 任意兼容 DP rank 通过 block hash 查询和复用已提交 Store KV；
- GPU compute、GPU copy engine、PCIe、NVLink、NIC、fabric 和 Store DRAM 的竞争；
- 首版只注入一种 `GPU_FAILURE`，并完整模拟检测、fence、reroute、KV恢复和重算；
- Router fence、reroute、Store load、recompute 和恢复；
- AegisKV Peer-HBM 与 Store DRAM 独立准入；
- request、failure、deployment 三层 JSON 配置；
- 完整 event journal、容量账本、KV residency timeline、迁移记录和请求指标；
- matched-seed baseline/AegisKV 实验与论文图像。

### 2.2 科学目标

MoonKVSim 应能回答以下问题：

1. Vanilla Mooncake 的跨 DP Store reuse 能在多大程度上降低重算和 TTFT？
2. 故障发生在请求不同阶段时，默认 Mooncake Store、Peer-HBM 和 AegisKV 的恢复收益分别是多少？
3. AegisKV 是否能在相同 HBM/DRAM/网络预算下改善 agent workflow completion time、goodput 和 tail recovery latency？
4. cache reuse value 与 failure protection value 统一管理是否优于两套独立 manager？
5. Peer-HBM budget、Store DRAM capacity、网络带宽和 GPU failure rate 改变时，策略是否仍然稳定？
6. 在真实multi-agent workflow的8K至128K上下文增长过程中，KV常驻/迁移成本与GPU failure恢复收益如何变化？

### 2.3 非目标

首个版本不尝试：

- 执行真实 CUDA、Triton、NCCL 或 RDMA；
- 复刻 vLLM/Mooncake 的每一行实现或线程级 race；
- 用模拟器单独证明真实硬件性能；
- 在 `main` 中提前加入 AegisKV 特殊状态；
- 把 Host staging buffer 误称为持久 Host KV cache；
- 把 Mooncake Master 建模成 KV 字节的数据转发路径；
- 把静态测试通过当作 simulator accuracy 或论文证据。
- 使用合成 multi-agent workload 替代正式实验 trace；
- 对真实 trace 静默截断、补齐或伪造到 128K；
- 模拟 Store SSD、NVMe、NVMe-oF、LOCAL_DISK 或其他持久存储 tier。

## 3. 名称、仓库与分支策略

### 3.1 统一命名

| 对象 | 名称 |
|---|---|
| 项目名 | MoonKVSim |
| Git 仓库 | `MoonKVSim` 或 `moonkv-sim` |
| Python package | `moonkvsim` |
| CLI | `moonkv-sim` |
| 配置 schema 前缀 | `moonkvsim.*` |
| 结果 schema 前缀 | `moonkvsim.result.*` |

### 3.2 分支

#### `main`

`main` 只表达 Vanilla Mooncake baseline：

- vLLM engine replicas；
- Router 与 DP selection；
- MooncakeStoreConnector-style shared Store；
- Store Master、Store Client、DRAM segments；
- 默认 allocation/eviction；
- 默认 GPU failure 行为；
- AIConfigurator 与全局 DES。

`main` 可以保存本计划和不可变的专利终稿作为未来分支的设计输入，但不得包含 AegisKV runtime policy、Aegis 专用实验结果或让 baseline 行为读取该策略。

#### `aegiskv`

必须在 `main` 验收并打 tag 后创建：

```bash
git switch main
git tag v0.1.0-mooncake-baseline
git switch -c aegiskv v0.1.0-mooncake-baseline
```

`aegiskv` 增加：

- unified reuse/protection KV metadata；
- Peer-HBM pool；
- independent HBM/DRAM admission；
- SlackLandlord；
- HBMQuotaAIMD；
- critical-aware protection；
- failure fence、route version、recovery 和 silent replay；
- AegisKV 实验与图像。

### 3.3 修复同步规则

- 通用 DES、vLLM、Mooncake、predictor 和 artifact bugfix：先进入 `main`，再同步到 `aegiskv`。
- AegisKV-only 策略和 schema：只进入 `aegiskv`。
- baseline 与 treatment 运行必须使用相同 workload、deployment、failure schedule、seed 和 predictor fingerprint。
- 不允许在 `aegiskv` 中悄悄修改 baseline scheduler 或 forward model来改善结果。

## 4. 源码权威与版本锁定

### 4.1 权威来源

| 优先级 | 子系统 | 权威来源 | 用途与冲突规则 |
|---:|---|---|---|
| 1 | AegisKV 设计 | `benchmark/AegisKV/docs/patent/AegisKV专利交底书-final-version.docx` | 最高设计契约；算法、状态机、故障语义和实验定义不得与之冲突 |
| 2 | vLLM scheduler、block manager、connector 生命周期 | 固定 commit 的 vLLM 源码；首选核验本机 `/home/comp/zhanzhao/.tmp/aegiskv-1cat-vllm-v1.2.2-sm89-src` 后锁定 | `main` 的引擎语义来源；不能凭文档或 SGLang 猜测 |
| 2 | Mooncake Master、Store、Transfer、replica | `/home/comp/zhanzhao/Mooncake` 的固定 vanilla baseline commit | `main` 的存储、目录、传输与公开命名来源 |
| 3 | Mooncake AegisKV 资料 | `/home/comp/zhanzhao/Mooncake/aegiskv/` 及相关代码 | 仅用于把终稿映射到 Mooncake；冲突项登记为 superseded |
| 3 | SGLSim AegisKV 资料 | `/home/comp/zhanzhao/sglsim/AegisKV/` | 复用配置、实验、审计和绘图经验；不得带入 SGLang/HiCache 层级语义 |
| 3 | SGLSim DES 方法 | `/home/comp/zhanzhao/sglsim/python/sglsim/srt/simulation/global_des.py` | 只参考通用全局 DES、事件日志和可复现机制 |
| 3 | AIConfigurator adapter | `/home/comp/zhanzhao/sglsim/python/sglsim/srt/time_predictor/` | 复用 predictor 接口思想，针对 vLLM 重新适配和校准 |

专利终稿至少冻结以下必须进入机器可读 contract 和测试的语义：

- workflow runtime 提供 Slack，AegisKV 不绑定某一种 Slack predictor；信息不足时使用保守规则；
- Peer-HBM 与 DRAM 各自维护容量、租金、候选 frontier、`PENDING` 和提交索引，并独立准入；
- 合法结果为 `HBM_ONLY`、`DRAM_ONLY`、`HBM_AND_DRAM`、`BYPASS`；
- 统一租值同时纳入 Slack 对应的恢复边际收益、命中概率/复用节省、LRU 新近性、字节数和 pool rent；
- Slack 或命中信息变化采用 Lazy Refresh：只更新版本，在候选暴露或 heap-top 校验时惰性重算，不做全池扫描搬移；
- 源端 production buffer 独立发起 Peer-HBM D2D/P2P 与 Store DRAM D2H/远端传输；禁止 Peer-HBM 到 DRAM 的目标端 writeback/destage；
- 只有 model/KV ABI/layout/version/shard 完整且物理传输完成的连续前缀才可 `COMMITTED` 并参与恢复；其余后缀重算或 silent replay；
- `HBMQuotaAIMD` 只改变 Peer-HBM quota；收缩时先撤销恢复资格再安全释放，不要求已有 DRAM 副本。

第一项 M0 产物应是 `benchmark/AegisKV/docs/patent/patent-contract.yaml`：逐条记录上述约束、专利章节/段落、代码 owner、测试 id 与当前状态。DOCX 本身是设计权威，YAML 只是可审计转录，不得另创语义。

### 4.2 `source-lock.json`

新仓库必须首先创建：

```text
reference/source-lock.json
```

建议 schema：

```json
{
  "schema": "moonkvsim.source-lock.v1",
  "vllm": {
    "repository": "/home/comp/zhanzhao/.tmp/aegiskv-1cat-vllm-v1.2.2-sm89-src",
    "commit": "",
    "version": "",
    "patches": []
  },
  "mooncake": {
    "repository": "/home/comp/zhanzhao/Mooncake",
    "baseline_commit": "",
    "aegiskv_commit": ""
  },
  "sglsim_reference": {
    "repository": "/home/comp/zhanzhao/sglsim",
    "commit": ""
  },
  "aiconfigurator": {
    "package_version": "",
    "database_mode": "",
    "database_sha256": "",
    "hardware_profile": ""
  },
  "aegiskv_design": {
    "path": "benchmark/AegisKV/docs/patent/AegisKV专利交底书-final-version.docx",
    "sha256": "d80de557e63edfc0d77a860a262470bf3dca666340724e9a6bfe7f34a507ecb9",
    "authority": "highest"
  }
}
```

当前源目录均可能包含未提交修改，因此 `source-lock.json` 必须记录实际读取文件的 Git commit、dirty 标志、必要文件 SHA256 和迁移 manifest；不能只写分支名，也不能把本机包版本字符串当成源码 commit。

### 4.3 源码对齐记录

每个模拟模块必须在 `reference/` 中记录：

- 对应源码文件和函数；
- 被保留的控制流；
- 被抽象掉的细节；
- 有意的模拟替换点；
- 已知 fidelity gap；
- 验证 trace 和结果。

## 5. 总体架构

```text
Workload / Agent DAG / Sessions
                │
                ▼
        Global Request Router
                │
       route / reroute / fence
                │
     ┌──────────┼──────────┐
     ▼          ▼          ▼
 vLLM DP0    vLLM DP1   vLLM DP2
 Scheduler   Scheduler  Scheduler
 GPU HBM     GPU HBM    GPU HBM
     │          │          │
     └──────────┼──────────┘
                ▼
      Mooncake Connector Model
                │
                ▼
       Global KV Directory
                │
      ┌─────────┴──────────┐
      ▼                    ▼
 Store Master         Transfer Engine
 allocation           GPU/DRAM copy
 replica metadata     resource reservation
      │
      ▼
Store Nodes
 └── DRAM segments
```

在 `aegiskv` 分支增加：

```text
Global KV Directory
├── PRIMARY_HBM
├── PEER_HBM       AegisKV protection pool
└── STORE_DRAM     shared reuse + protection pool
```

## 6. 唯一 KV 真相源

### 6.1 KV identity

每个可共享 KV object/block/chunk 至少包含：

- tenant ID；
- model ID 与 revision；
- KV dtype；
- KV ABI/layout；
- TP/PP layout；
- block size；
- stable block hash；
- token interval；
- shard identity；
- request/session/workflow lineage；
- route version；
- source physical GPU id（首版唯一 failure domain）。

### 6.2 KV location

建议位置类型：

```text
PRIMARY_HBM
PEER_HBM
STORE_DRAM
```

`main` 只使用 `PRIMARY_HBM` 和 `STORE_DRAM`；`PEER_HBM` 只在 `aegiskv` 出现。首版没有 `STORE_SSD` location，配置、runtime enum、恢复选择和输出 schema 都不得保留隐式 SSD fallback。

### 6.3 Replica state

状态名称最终应对齐 pinned Mooncake，但至少必须表达：

```text
ALLOCATED
PENDING
COMMITTED
ABORTED
LOST
EVICTED
REMOVED
```

硬约束：

- `PENDING` 不可用于 cache hit 或 recovery；
- 只有所有 shards 完成且版本兼容才可 `COMMITTED`；
- failure/eviction 必须原子地更新目录与容量账本；
- Store Master 只管理逻辑位置和状态，不搬运 KV bytes；
- 一个物理副本只能计费一次。

### 6.4 Unified role

`aegiskv` 分支中的一个副本可以同时具有多个 role：

```json
{
  "location": "STORE_DRAM",
  "roles": ["CACHE_REUSE", "FAILURE_PROTECTION"],
  "state": "COMMITTED"
}
```

这样普通 cache lookup 和故障恢复查询相同目录，不再维护 HiCache/AegisKV 两套真相源。

### 6.5 逻辑副本与物理分配分离

目录中的 KV object/replica/role 是逻辑状态，显存或 DRAM 中真正占空间的是 `PhysicalAllocation`。二者必须通过稳定 id 关联：

```text
KVObject → Replica → PhysicalAllocation → ResourceLedger
                    └→ zero or more logical roles
```

一个物理分配同时承担 `CACHE_REUSE` 和 `FAILURE_PROTECTION` 时，只占用一次物理容量；增加或删除 role 只改变逻辑 metadata，不产生 capacity delta。切片、TP shard、PP stage、Store replica 和 Peer-HBM target 各有独立 `allocation_id`，禁止仅按 object key 推断物理占用。

`PhysicalAllocation` 至少记录：

```json
{
  "allocation_id": "alloc-...",
  "object_id": "kv-...",
  "replica_id": "replica-...",
  "resource_id": "gpu-3.hbm",
  "owner_account": "PEER_PROTECTION_KV",
  "payload_bytes": 15728640,
  "requested_bytes": 16777216,
  "allocated_bytes": 16777216,
  "padding_bytes": 1048576,
  "allocator_metadata_bytes": 0,
  "internal_fragmentation_bytes": 0,
  "alignment_bytes": 256,
  "allocator_extent": {},
  "state": "RESERVED",
  "created_at_ns": 1000,
  "released_at_ns": null
}
```

`payload_bytes` 表示有效 KV 数据，`requested_bytes` 表示包含 layout/block padding 后提交给 allocator 的大小，`allocated_bytes` 表示经过 page/slab/alignment 后真实扣除的 extent。padding、allocator metadata 与 allocation 内部碎片仍计入该 owner account；无法归属某个 allocation 的 allocator 外部碎片才单列为 pool 的 `ALLOCATOR_FRAGMENTATION` account。目录可见性由 replica state 决定，物理占用由 allocation state 决定，两者不可合并成一个布尔量。

## 7. DRAM 与 L2 语义

MoonKVSim baseline 不定义持久、rank-private Host L2。

### 7.1 Host staging

- 只用于无 GDR/TCP 等传输路径的临时 buffer；
- 生命周期与 transfer operation 绑定；
- 不参与 prefix lookup；
- 不提供跨请求复用；
- 不计入 Store DRAM residency。

### 7.2 Store DRAM

- 由 Mooncake Store Client/daemon 提供；
- 由 Master 统一分配和发布；
- 对所有兼容 DP rank 全局可见；
- 本机与远程 segment 属于同一个逻辑 pool；
- locality 只影响复制路径、带宽和 setup；Peer-HBM 保护副本必须位于不同的物理 GPU；
- `GPU_FAILURE` 只使目标 GPU 上的 HBM/compute/copy 失效；Host DRAM 与 Mooncake Store 副本仍可使用。

## 8. 全局虚拟时钟 DES

### 8.1 基本模型

模拟器使用单一、单调递增的 `now_ns`：

```python
schedule_at(timestamp_ns, event)
schedule_after(delay_ns, event)
reserve(resources, ready_ns, duration_ns)
run(until_ns=None)
```

所有事件按以下 key 排序：

```text
(timestamp_ns, priority, stable_sequence)
```

禁止：

- `sleep()`；
- rank-local clock 最后再取 max；
- transfer 完成前提前发布 metadata；
- 在一个 aggregate delay 中隐藏多个资源竞争；
- 在失败后继续提交已失效 source/target 的传输。

### 8.2 事件类别

```text
REQUEST_ARRIVAL
ROUTE_REQUEST
SCHEDULER_STEP_READY
FORWARD_START
FORWARD_COMPLETE
KV_BLOCK_ALLOCATE
KV_BLOCK_FREE
RESOURCE_RESERVE
RESOURCE_RELEASE
STAGING_ACQUIRE
STAGING_RELEASE
STORE_QUERY
PUT_START
PUT_ALLOCATED
TRANSFER_START
TRANSFER_SLICE_START
FLOW_RATE_UPDATE
TRANSFER_SLICE_COMPLETE
TRANSFER_COMPLETE
PUT_COMMIT
GET_START
GET_COMPLETE
EVICTION_START
EVICTION_COMPLETE
DIRECTORY_PUBLISH
FAILURE_INJECT
FAILURE_DETECT
ROUTE_FENCE
REROUTE
RECOVERY_START
RECOVERY_COMPLETE
SILENT_REPLAY_COMPLETE
REQUEST_COMPLETE
REPAIR_COMPLETE
```

事件 payload 必须带稳定的 request/object/replica/allocation/transfer/flow/resource id 以及触发原因；不可只保存聚合后的 GPU used bytes。每个会改变资源的事件必须通过 `ResourceTransaction` 写出 before/delta/after，确保离线 replay 能重建任意时刻的逐设备状态。

### 8.3 同时间事件顺序

必须在设计阶段冻结并测试：

- failure 与 transfer completion 同时发生时谁先执行；
- fence 与 output token 同时发生时是否允许输出；
- commit 与 eviction 同时发生时副本是否可见；
- request completion 与保护副本释放同时发生时如何计费；
- repair 与 reroute 同时发生时哪些 route version 合法。

默认建议采用保守故障语义：在相同 timestamp 上先处理 failure/fence，再处理尚未完成的 commit/output；最终仍以固定源码和实验协议为准。

## 9. 物理资源模型

“准确”首先指每次状态变化都能解释真实容量和资源占用，而不是只让最终延迟接近。MoonKVSim 必须同时维护：

1. capacity resources：GPU HBM、Host DRAM、Store DRAM；
2. rate resources：HBM/DRAM bandwidth、PCIe、NVLink、NIC 和 fabric link；
3. concurrency resources：GPU compute/copy engine、CPU worker、registration worker、QP/endpoint 和 Master RPC lane；
4. logical resources：vLLM KV block id、Mooncake object/replica、AegisKV quota、route/GPU-failure eligibility。

逻辑资源不能代替物理资源；policy quota 也不能代替 GPU/DRAM 的真实容量检查。

### 9.1 KV 字节数与分配粒度

每种模型必须从锁定的 model config、vLLM `CacheConfig`/`CacheSpec` 和实际 TP/PP placement 生成 `kv-layout.json`，禁止只用“token 数 × 常数”的手工估计。普通 MHA/GQA 层的单 token、单 TP shard payload 可由下式审计：

```text
kv_payload_bytes_per_token(stage, tp_rank)
  = Σ(layer in pp_stage)
      2(K,V)
      × local_num_kv_heads(layer, tp_rank)
      × head_dim(layer)
      × kv_dtype_bytes
    + layout_specific_auxiliary_bytes

requested_block_bytes
  = block_size_tokens × kv_payload_bytes_per_token

allocated_block_bytes
  = allocator_round_up(requested_block_bytes,
                       page/slab/alignment/granularity)
```

必须从源码处理而非套用上述普通公式的情况包括 MLA、hybrid attention、sliding-window/cache groups、跨层共享、KV quantization/scale metadata、非均匀 PP layer placement、GQA head replication 与不能整除的 TP layout。每个 block/chunk 都保存 payload、padding、metadata、allocated 四类字节，实验默认报告 `allocated_bytes`，避免低估物理占用。

分配动作必须镜像 pinned vLLM：prefill 按本 step 实际 scheduled tokens/blocks 分配；decode 在对应 prepare/allocate 阶段为下一 token 获取 block；prefix hit 只增加引用或 block-table mapping，不重复占用同一物理 block；copy-on-write、preemption、free 和 recompute 的顺序由 differential trace 固定。

### 9.2 GPU HBM 精确账本

每张 GPU 建立独立 `CapacityLedger`。以下互斥 owner accounts 的和必须等于 GPU 可用物理容量：

```text
MODEL_WEIGHTS
RUNTIME_FIXED
RUNTIME_DYNAMIC
ACTIVE_PRIMARY_KV
INACTIVE_REUSABLE_KV
PEER_PROTECTION_KV          # aegiskv only
RECOVERY_DEST_RESERVED
TRANSFER_STAGING
ALLOCATOR_FRAGMENTATION
UNATTRIBUTED_RESERVE        # validation gap; formal runs require zero
FREE
UNAVAILABLE_CAPACITY        # GPU_FAILURE/degraded device
```

DP/TP/PP rank 是逻辑执行实体，不是独立显存。deployment 必须把每个 rank 映射到唯一 physical GPU id；若多个进程/rank 共享同一 GPU，其 weights、runtime 与 KV allocation 全部进入同一 ledger 并竞争同一 compute/copy/HBM bandwidth 资源。

`roles`、`pinned`、`in_flight_source`、`recovery_eligible` 是这些物理字节上的 overlay/tag，不得再次加入容量总和。例如正在 D2D 复制的 primary block 仍只属于 `ACTIVE_PRIMARY_KV`，但在传输结束前增加 source pin/refcount；Peer-HBM 目标则在传输开始前完整计入 `PEER_PROTECTION_KV` 的 `RESERVED/PENDING` 子状态。

每次 scheduler admission 必须先通过两层检查：

```text
vLLM block availability
AND
physical HBM ledger availability after alignment/reserve
```

若任一失败，只能执行 pinned vLLM 允许的 wait/preempt/recompute/evict 路径，不能产生负显存或事后补账。AegisKV Peer-HBM quota 是 `PEER_PROTECTION_KV` 的上限之一，但总 HBM、block allocator 和 hard safety reserve 仍是更强约束。

### 9.3 Host DRAM 与 Store DRAM 账本

每个 node 的 Host DRAM 和每个 Store segment 必须是不同 resource ledger：

- Host DRAM：framework/runtime reserve、registered client buffer、TCP bounce/staging、temporary Get destination、fragmentation、free；
- Store DRAM segment：allocator metadata、`PENDING` replica、`COMMITTED` replica、evicting-but-not-freed、fragmentation和free；

首版不创建 SSD/NVMe capacity ledger、queue、promotion event 或 replica state；如果输入配置出现相应 tier，必须在启动前报错。

Store DRAM 本机或远程只改变 placement/path，不改变其全局可查询语义；首版不注入 Store failure。Host staging 不得出现在 Store directory；但它必须真实消耗 Host DRAM，并受 buffer-pool capacity、registration、copy engine 和生命周期约束。

Mooncake allocation 需要保存 `requested_bytes`、slice placement、replica number、best-effort partial allocation、allocator extent 与 `allocated_bytes`。对象由多个 slices/replicas 组成时，只有协议要求的全部 slices 成功才发布对应 replica；已分配但未提交的空间始终计入 `PENDING`，失败回滚后才进入 `FREE`。

### 9.4 节点内外的 rate/concurrency 资源

每条数据路径按拓扑展开为一组共享资源：

- GPU HBM read/write bandwidth；
- D2D/H2D/D2H copy engine；
- PCIe link/switch/root complex；
- NVLink/NVSwitch；
- CPU socket、NUMA DRAM channel 与 UPI/inter-socket link；
- NIC TX/RX、RDMA QP/endpoint、TCP worker；
- top-of-rack/fabric links 与 oversubscription；
- Store DRAM read/write lane；
- Master/metadata RPC worker。

资源可以是 full-duplex 或 directional；配置必须说明共享域。例如同一 PCIe switch 下多 GPU 和 NIC 不能各自都获得完整峰值带宽。compute 与 copy 是否 overlap、H2D 与 D2H 是否共享 engine、GDR 是否绕过 host staging，都由 hardware/transport profile 决定。

### 9.5 KV 管理与传输的原子资源状态机

一次新副本或恢复传输必须按以下顺序产生资源事务：

```text
policy selects candidate                 # no physical delta
→ destination allocate/reserve           # FREE → PENDING/RESERVED
→ pin source allocation                  # overlay refcount only
→ acquire staging if protocol requires   # Host/GPU FREE → STAGING
→ submit BatchTransfer/slices
→ consume copy/PCIe/NIC/fabric/memory rates over virtual time
→ all required slices complete
→ PENDING → COMMITTED                     # capacity total unchanged
→ publish directory/version atomically
→ release source pin and staging          # STAGING → FREE
```

Abort/failure path：

```text
failure or cancellation
→ prevent commit with generation/route version
→ cancel unsent slices and remove active flows
→ release endpoint/queue slots
→ release staging
→ release destination reservation, or mark UNAVAILABLE/LOST
→ release source pin if source still exists
→ append balancing ledger deltas
```

Eviction 不得在选择候选时立即释放空间：先撤销 lookup/recovery eligibility，等待 pin/refcount 为零并完成必要 metadata protocol，最后物理 free。failure 后已损坏设备上的 allocation 可以从可用容量中转为 `UNAVAILABLE_CAPACITY`，但不能假装已经变成其他健康设备的 free bytes。

所有资源变化通过一个事务接口提交：

```python
ResourceTransaction(
    event_id=...,
    timestamp_ns=...,
    cause="AEGIS_PEER_BACKUP",
    allocation_deltas=[...],
    overlay_deltas=[...],
    flow_deltas=[...],
    directory_deltas=[...],
)
```

事务提交前后都运行局部 invariant；任何一项失败则整笔事务不生效并终止 run，禁止 warning 后继续得到图表。

### 9.6 通信的默认精度层级

MoonKVSim 的默认通信后端不是 `bytes / peak_bandwidth`，而是和全局 DES 共用同一个 `now_ns` 的 topology-aware flow/slice model：

```text
BatchTransfer
  → 按 Buffer/Segment 边界拆 operation
  → 大 operation 拆为 slice
  → 为每个 slice 选择 source NIC、fabric path、target NIC
  → 预约 GPU copy/PCIe/NUMA/NIC/link/DRAM lane
  → 根据并发 flow 重新分配可用带宽
  → 完成、因GPU failure取消、abort 或 commit
```

必须建模的资源和开销：

- Buffer 注册与 memory-region registration，可区分 startup、cold 和 cached；
- `openSegment`、Master/metadata RPC、endpoint 建连和 QP warm-up；
- GPU Direct RDMA 与 host-staging TCP 两条不同路径；
- GPU copy engine、PCIe switch/root complex、NUMA/UPI、NIC ingress/egress、fabric link、目标 memory controller；
- Mooncake topology matrix 的 preferred/secondary NIC；
- 大请求切片、多 NIC striping、并行 I/O、endpoint pooling；
- preferred/secondary NIC 的正常选路与负载分摊，以及 GPU failure 时未完成 slice 的取消；
- DRAM 队列与网络路径重叠，以及协议允许的 full-duplex。

网络共享默认使用 work-conserving、congestion-aware fluid model：同一瓶颈上的 active flows 按可配置 max-min fair 或 weighted max-min fair 分带宽，flow 到达/完成时重新计算下一完成事件。不得把整条链路独占到一个 transfer 完成，也不得只在提交时一次性加 aggregate delay。GPU copy engine、DRAM lane、registration worker 等离散设备则使用可配置 lane/queue discipline。

每个 slice 的延迟由以下可校准组成构成：

```text
T_slice = T_submit + T_lookup + T_register/cold_connect
        + T_queue(resources, concurrent_flows)
        + bytes / effective_path_rate
        + T_completion
```

这里 `effective_path_rate` 是经过 PCIe/NUMA/NIC/fabric/目标介质瓶颈及并发份额后的动态速率，而不是硬件峰值。Master RPC 与字节数据面必须分开；Master 只做元数据和放置决策。

提供统一 adapter 接口和四个 fidelity backend：

| 后端 | 用途 | 是否进入常规全矩阵 |
|---|---|---|
| `analytical_fast` | 无拥塞或简单共享的快速 sanity check | 可选 |
| `flow_contention` | topology-aware slice/flow 竞争，默认论文模拟后端 | 是 |
| `trace_replay` | 回放真机传输 trace，验证事件/队列语义 | 小规模 |
| `astra_validation` / `ns3_validation` | 对选定拓扑和拥塞微案例做外部交叉验证 | 否，只做 golden/校准 |

所有 adapter 都只能向 MoonKVSim 返回 future completion/flow update 事件，不得维护第二套时钟。ASTRA-Sim/SimAI/ns-3 适合作为多精度参考和选定案例的验证器，而不是替代 vLLM/Mooncake 状态机或让每个论文 cell 都跑 packet-level 仿真。

### 9.7 占比、归因与可重建性

“KV 管理传输导致的资源占比变化”必须由事件账本直接计算，而不是运行结束后按总字节估算。每个 resource delta 和 flow 都带 `cause`：

```text
MODEL
INFERENCE_PRIMARY_KV
CACHE_REUSE
MOONCAKE_PUT
MOONCAKE_GET
AEGIS_PEER_PROTECTION
AEGIS_DRAM_PROTECTION
RECOVERY
PREFETCH
EVICTION
TRANSFER_STAGING
ALLOCATOR_FRAGMENTATION
CONTROL_PLANE
```

定义三类占比：

```text
memory_share[cause, t]
  = allocated_bytes[cause, t] / physical_capacity_bytes

bandwidth_share[cause, window]
  = ∫ transferred_rate[cause, t] dt
    / ∫ available_link_rate[t] dt

engine_share[cause, window]
  = busy_time[cause, window] / available_engine_time[window]
```

还必须给出 `payload_bytes / allocated_bytes`、staging high-watermark、pending high-watermark、fragmentation、queue wait、service time、aborted bytes 和 energy/cost（若配置）等分项。Baseline 与 AegisKV 的资源差值必须用 matched workload/failure/seed 计算，并分解为常驻容量、临时峰值、传输 byte-time、排队和重算节省。

### 9.8 守恒与逐事件审计

任意健康 capacity resource、任意时间必须满足：

```text
allocated_bytes
  = payload_bytes + padding_bytes
    + allocator_metadata_bytes + internal_fragmentation_bytes

physical_capacity
  = Σ(all allocation owner accounts)
    + external_allocator_fragmentation
    + fixed/free/unavailable accounts
```

每个事件之后至少检查：

- 所有账户非负且不超过 capacity/quota；
- `FREE` 的变化与 allocation/free delta 完全对应；
- `PENDING → COMMITTED` 不改变总占用，只改变子状态；
- logical alias/role/refcount 变化不改变物理容量；
- 每个 active flow 的 source/destination allocation 存在且合法；
- 每个 rate resource 的同时分配速率不超过有效容量；
- transfer payload、slice payload、完成/重试/abort 字节守恒；
- COMMITTED replica 必须拥有完整物理 allocation 和全部 shards；
- journal replay 后的最终 ledger 与在线 ledger byte-identical。

输出 `capacity-audit.json` 时既给最终结果，也给第一次错误的 event id、前后账户、对象/replica/allocation/flow id 和最小重放前缀。只要出现守恒错误，该 run 的 `valid=false`，禁止进入汇总或论文绘图。

## 10. vLLM-style 推理引擎

### 10.1 必须对齐的行为

- request/sequence 生命周期；
- waiting、running、preempted、finished；
- continuous batching；
- chunked prefill；
- decode allocation；
- paged KV block；
- prefix block hash；
- cached block lookup；
- preemption 与 recompute；
- block free；
- scheduler output；
- connector metadata；
- DP routing hints。

### 10.2 DP 与 Router 边界

- 外部 Router 选择初始 DP target；
- vLLM 内部 DP balancing 与外部 routing 分开记录；
- Mooncake Store 提供 KV lookup，不决定最终 target；
- cache-aware Router 可以使用目录 hit 信息，但必须记录评分和选择原因；
- reroute 必须生成新 route version并 fence旧执行。

### 10.3 Prefix key 一致性

跨 DP cache reuse 至少要求：

- 一致的 `PYTHONHASHSEED`；
- 一致的 block size；
- 一致 model/revision；
- 一致 KV ABI/layout；
- 一致 tenant/namespace；
- 一致 TP/PP layout 或明确 reshard 路径。

## 11. AIConfigurator 预测器

### 11.1 Engine-neutral 输入

建议公共输入：

```python
PredictionRequest(
    extend_length: int,
    past_kv_length: int,
)

PredictionBatch(
    requests: list[PredictionRequest],
    phase: Literal["prefill", "decode"],
)
```

vLLM adapter 负责把实际 scheduled batch 转换为预测输入。

### 11.2 预测边界

AIConfigurator 只返回：

```text
predicted_forward_duration_ns
```

以下时间必须独立建模：

- scheduler CPU；
- connector metadata；
- Master RPC；
- D2D/H2D/D2H；
- RDMA/TCP；
- Store DRAM；
- failure detection；
- reroute；
- recovery replay。

如果选定 AIConfigurator profile 已包含 TP/PP collective 或某段通信，该部分必须在 profile manifest 中声明，MoonKVSim 不得再次计费。默认边界是：预测器负责一次 vLLM scheduler step 的 GPU forward（包括被该 profile 明确包含的模型内 collective），Mooncake KV 外部传输始终由 Transfer Engine 模型负责。

预测值不能只作为一次 `schedule_after` 延迟：在 `[FORWARD_START, FORWARD_COMPLETE)` 内必须占用 GlobalDES 中对应 rank 的模拟 GPU compute resource，并根据 modeled profile 决定与 D2D/H2D/D2H、HBM bandwidth 和 collective 是否可重叠。KV transfer 导致的 forward slowdown 只能来自已声明且带 provenance 的共享资源/overlap matrix，不能既在 flow model 中竞争一次、又在 AIConfigurator duration 上重复加罚。

KV 管理控制面也不是零成本。scheduler bookkeeping、prefix lookup、Master allocation、directory publish、Slack update、Lazy Refresh heap validation、eviction selection 和 failure fence 分别占用配置中的 CPU/RPC worker lane并产生事件；阻塞调用会延迟对应 state transition，异步调用只占资源而不阻塞 GPU。其 service-time profile 必须区分源码默认、实测拟合与 sensitivity-only。

### 11.3 Modeled profile 与高等级证据边界

- prefill 和 decode 分开；
- 不直接继承 SGLSim HiCache scale；
- 不使用一个全局 scale factor吸收 shape error；
- 对 batch size、input length、past KV length 做 shape-aware 验证；
- 当前交付保存 raw modeled prediction、参数来源和 sensitivity 结果，不生成虚假的
  calibrated prediction、observed value 或 residual；
- 所有当前结果标记为 `modeled/preliminary`、`not_calibrated`。真机校准只作为
  E3 的未来证据路径，不属于当前执行计划。

## 12. Vanilla Mooncake 模型（`main`）

### 12.1 Master

模拟：

- segment mount/unmount；
- client registration；
- key/object metadata；
- replica list；
- allocation strategy；
- `PutStart`；
- finalize/commit；
- `GetReplicaList`；
- lease；
- remove；
- tenant quota；
- high-watermark eviction trigger；
- node join/leave；

### 12.2 Store Node

模拟：

- local DRAM allocation；
- fragmentation/granularity；
- local eviction候选；
- watermarks；
- read/write queue；
- replica lost notification。

### 12.3 Transfer Engine

模拟实际数据路径而非一个总延迟：

```text
GPU → Store DRAM
Store DRAM → GPU
GPU → temporary host staging → TCP → Store
GPU → remote GPU（如基线 connector 需要）
```

每条路径必须声明：

- source/destination；
- byte count；
- setup；
- required resources；
- bottleneck bandwidth；
- ready/start/end；
- state；
- abort reason。

内部对象和命名必须贴合 Mooncake：`Segment`、`Buffer`、`BatchTransfer`、`TransferTask`、`TransferMetadata`、`MultiTransport`、`Topology`、`MemoryLocation` 与具体 `Transport`。大于当前锁定 Mooncake 源码阈值的 operation 按源码规则切成 slices；初版可把官方文档给出的 64 KiB 作为待源码确认的默认值，但 resolved manifest 必须记录最终阈值和来源。

### 12.4 Baseline recovery

Vanilla Mooncake 也可能已经存在 committed Store KV。因此默认故障路径应是：

```text
GPU failure
→ Router reroute
→ query Store by compatible block hash
→ load committed continuous prefix
→ recompute missing suffix
```

AegisKV 的收益不能错误地与“全部重算且完全没有 Mooncake Store”的弱 baseline 比较。

## 13. AegisKV 专利终稿落地（`aegiskv`）

专利终稿已经把 AegisKV 定义为面向复用与故障恢复的统一 KV management，而不是 HiCache 上新增的一层备份。实现前的任务是把终稿逐条转录成状态机、公式、配置与验收测试；不得重新发明一套与终稿不同的“修订设计”。

### 13.1 两个策略 pool

- Peer-HBM pool；
- global Store DRAM pool。

Store DRAM 中的 local/remote segments 不是两个独立算法 tier，只是不同 placement 和传输 path；首版 GPU failure 不使 Store segment 失效。

### 13.2 独立准入

同一 sealed chunk 的 HBM 和 DRAM 决策必须独立支持：

```text
HBM_ONLY
DRAM_ONLY
HBM_AND_DRAM
BYPASS
```

两条路径：

- Source production HBM → designated Peer-HBM；
- Source production HBM → Store DRAM final space。

禁止：

- Peer-HBM → Store DRAM writeback；
- target-owned background destage；
- DRAM 成功作为 HBM 准入前提；
- 一条路径失败终止另一条路径。

### 13.3 Unified value

每个 pool 对安全可释放连续尾部计算租值型优先级。实现必须保留专利终稿规定的共同输入：

```text
priority(chunk, pool, version)
= combine(
    slack_dependent_recovery_marginal_benefit,
    hit_probability × expected_reuse_saving,
    lru_recency,
    actual_bytes,
    pool_rent
  )
```

具体归一化、权重和单调方向必须从专利公式逐项转录进 `patent-contract.yaml`，并由公式 golden tests 固定，不能在编码时用经验分数替代。请求执行期间副本可以同时具有 reuse 和 recovery value；请求完成后 recovery value 归零，但 reuse value 可以继续保留。

Slack、hit probability 或 recency 改变时执行 Lazy Refresh：增加 metadata version，不扫描或搬移全池；仅在新 suffix 暴露、候选进入 heap top 或准备淘汰时验证版本并重算。每个 pool 的 heap/index 仍然独立，统一的是价值语义和 KV directory，不是把两个 pool 合成一个容量池。

### 13.4 HBMQuotaAIMD

- 只调整 Peer-HBM quota；
- DRAM 由 Store capacity和策略管理；
- HBM contraction 停止新 admission并淘汰低价值安全尾部；
- 删除 HBM 不要求 DRAM 已提交；
- 无其他副本时允许以后重算。

## 14. GPU 故障与恢复模型

### 14.1 首版唯一故障类型

```text
GPU_FAILURE
```

首版不注入 process、inference node、Store node、Master、NIC、network partition 或 correlated/rack failure，也不把它们作为隐藏的随机错误。`GPU_FAILURE` 采用保守、统一的 fail-stop 语义，不再细分 software/hard failure：从故障发生时刻开始，该物理 GPU 的 compute、copy engine 和 HBM 内容均不可访问且不可信。

### 14.2 `GPU_FAILURE` 精确影响范围

failure target 必须是一个 physical `gpu_id`，而不是模糊的 DP rank。故障会影响映射到该 GPU 的全部 DP/TP/PP rank，并执行：

- 立即停止/取消该 GPU 上尚未完成的 forward；对应 batch 不产生 output/KV completion；
- 取消 source 或 destination 位于该 GPU 的 D2D/H2D/D2H/RDMA/TCP transfer 和未完成 slices；
- 该 GPU 上的 primary KV、reusable KV、Peer-HBM、recovery reserve 和 staging allocation 全部从可恢复集合移除并标为 `LOST`；
- GPU 容量账本转为 `UNAVAILABLE_CAPACITY`，直到可选 repair 完成；
- 该 GPU 上保护其他请求的 Peer-HBM 也同时丢失，不能只删除当前失败请求的 primary KV；
- fence 所有受影响 route version；检测完成后才允许 Router 发起 reroute；
- 对包含失败 GPU 的 TP/PP engine replica，整个 replica 在恢复前不可作为目标，不能只让缺失 shard 的 rank继续运行。

明确不受影响：

- 同一节点的 Host DRAM 和 temporary staging pool 的物理容量；与失败 transfer 绑定的 staging allocation在取消协议完成后释放；
- Mooncake Store DRAM 中已经 `COMMITTED` 的副本，包括与失败 GPU 同机但属于独立 Store segment 的副本；
- Store Master、Store daemon、其他 GPU、NIC 和 fabric；网络只移除与失败 GPU transfer 对应的 active flows；
- 其他健康 GPU 上的 Peer-HBM 副本。

因此首版评估的是“单 GPU fail-stop 下的 KV 状态恢复”，而不是节点掉电或机架相关故障。部署仍记录 node/NIC/topology，用于传输竞争和 placement，但 failure injector 不能选择它们。

### 14.3 发生、检测与可选修复

```text
FAILURE_INJECT(at_ns)
  → GPU execution/data path immediately unavailable
  → cancel forward/transfers and mark GPU allocations LOST

FAILURE_DETECT(at_ns + detection_delay_ns)
  → fence affected route versions
  → Router selects healthy compatible engine replica
  → start recovery
```

正式首版实验默认 `repair_after_s=null`，即失败 GPU 在整个 run 中不返回。若 calibration/sensitivity run 显式启用 repair，则 repair 后 GPU 以空 HBM 和新 generation 重新加入：旧 KV allocation/endpoint/route version永不自动复活，weights/runtime reinitialization 时间和资源必须单独模拟。

### 14.4 恢复协议

```text
GPU_FAILURE occurs
→ detection
→ fence failed GPU routes and output
→ select healthy compatible engine replica
→ increment route version
→ query committed continuous prefix
→ choose Peer-HBM / Store DRAM / recompute
→ reserve destination HBM and transfer resources
→ load all required shards
→ materialize target block table
→ silent replay to committed output position
→ atomic activation
→ resume output
```

硬约束：

- 未提交副本不可恢复；
- 不兼容 model/revision/ABI/layout 不可恢复；
- 只采用完整、连续 prefix；
- 所有 TP/PP shards完成后才能激活；
- stale route 不可输出；
- output token 不可重复或丢失；
- recovery adoption 后再释放健康设备上的旧保护容量；
- 目标 GPU 必须健康且具有整个 TP/PP replica 所需的容量；
- 无健康 compatible target 时显式结束为 `RECOVERY_FAILED_NO_TARGET`，不得无限等待或静默换成无故障结果。

## 15. 三层 JSON 配置

### 15.1 `requests.json`

负责请求层：

```json
{
  "schema": "moonkvsim.requests.v1",
  "seed": 1,
  "arrival": {
    "mode": "causal_trace_replay",
    "request_rate": null,
    "max_concurrency": null
  },
  "workload": {
    "kind": "real_multi_agent_trace",
    "dataset": "semianalysisai/cc-traces-weka-062126",
    "raw_trace_path": "/home/comp/zhanzhao/sglsim/AegisKV/doc/Archived/2026-08-06-pre-kvcache-centric/presentations/presentation/experiments/sglsim_large/traces/cc-traces-weka-062126/traces.materialized.jsonl",
    "normalized_trace_path": "traces/normalized/...parquet",
    "trace_sha256": "29b6a19e751ff5230771519aab755f80a0f43a4ba9cf96b72d3a6a437ec99276",
    "normalizer_commit": "",
    "closed_loop": true,
    "preserve_agent_dag": true,
    "preserve_recorded_tool_delay": true,
    "derive_prefix_sharing_from_source_hash_ids": true
  },
  "trace_token_count": {
    "mode": "source_hash_blocks_64",
    "source_block_size_tokens": 64,
    "hash_id_scope": "within_workflow_only"
  },
  "target_model_tokenizer": {
    "model_id": "Qwen/Qwen3-8B",
    "revision": "",
    "tokenizer_config_sha256": ""
  },
  "context": {
    "max_model_len_tokens": 131072,
    "required_observed_context_buckets": [8192, 32768, 65536, 98304, 131072],
    "require_real_128k_samples": true,
    "overflow_policy": "fail",
    "truncation_policy": "forbid",
    "synthetic_padding": "forbid"
  }
}
```

必须记录：

- 真实 trace 的来源、采集时间、许可/访问级别、raw hash、normalizer版本和 normalized hash；
- `workflow_id`、`session_id`、`agent_id`、`span_id`、parent/child edge、并行 fan-out/fan-in 与 causal dependency；
- 真实 request submit/complete timestamp、tool call/response、think/tool delay和重试关系；
- trace 可用时保存实际 prompt/messages 或可复现 token ids；Weka trace缺少自然语言内容时保存真实 `hash_ids`、`in`、`out`、model和source block size，并明确其token-count evidence边界；
- prompt、prefix-cached、generated 和 total context token 数及其计算模式；不能把source hash-block计数伪装成Qwen tokenizer精确计数；
- 从真实 source token block/hash 推导的 shared prefix，不使用人工命中率或随机 prefix sharing；
- 原始并发和 causal replay 后的有效并发；正式实验不通过 `request_rate` 合成到达；
- seed 只用于相同 timestamp tie-break、GPU target/failure抽样等非 trace 内容，不能改变请求文本、DAG 或长度。

#### 真实 multi-agent trace contract

正式实验只能使用实际 multi-agent 系统运行产生的 trace。合成请求、随机长度、复制同一个 prompt、人工 padding 到 128K 或按分布重新采样只允许 unit/smoke test，结果必须标记 `synthetic=true` 且不能进入论文主结果。

normalized trace 每个 LLM span 至少包含：

```text
workflow_id, session_id, agent_id, span_id, parent_span_ids,
parent_edge_origin, parent_edge_confidence,
observed_submit_ns, observed_finish_ns,
messages_or_token_ids, prompt_token_ids_hash,
prompt_tokens, cached_prefix_tokens, output_tokens,
tool_name, tool_delay_ns, dependency_release_rule,
model_id, model_revision, token_count_mode, tokenizer_fingerprint
```

默认 `causal_trace_replay` 不照搬真实服务器的排队/推理完成时间：root span 按真实相对到达时间进入 DES；child span 必须等待其父 LLM 模拟完成，再叠加 trace 中真实记录的非 LLM/tool delay后释放。这样既保留真实 multi-agent DAG 和 think/tool timing，又让 MoonKVSim 自己决定排队、forward、KV 和恢复时间。

#### 128K 上下文定义与门槛

本计划中的目标模型窗口上限定义为 `131072 tokens`。若 trace 有原始文本/token ids，则按锁定 tokenizer/chat template 计算；当前 Weka 候选 trace 使用采集端真实的64-token KV hash-block计数 `in`，必须标记为 `source_hash_blocks_64`，不能声称是 Qwen tokenizer 的语义等价tokenization：

```text
context_before_step
  = tokens(all retained system/user/assistant/tool messages)

model_length_guard
  = context_before_step + scheduled/generated output tokens
  <= 131072
```

正式 workload 必须包含真实观测到的 128K 样本，而不是仅把 vLLM `max_model_len` 配成 128K。建议报告 8K、32K、64K、96K、128K 五个实际 context bucket；每个 bucket 的样本数、workflow数和 token 分布在 manifest 中列出。若真实 trace 没有达到 128K、样本不足、tokenizer无法复现或发生任何截断，该实验矩阵标记 incomplete并阻止 paper-ready，不允许自动补齐。

对于单个 span，prefix cache lookup 使用该 span 的真实 source `hash_ids`；这些 id 只允许在同一 workflow/trace 内比较。对于跨 agent 的共享上下文，只有 source hash block、namespace、目标 model/KV ABI 和转换后的block boundary全部一致才能命中。累计 workflow token 总数达到 128K 但任何一次 model context 未达到 128K，不能冒充“128K context”样本。

#### 当前真实 trace 候选与预审计

当前本机已有可作为首选输入的真实 Weka Claude Code multi-agent proxy trace：

```text
dataset: semianalysisai/cc-traces-weka-062126
path: /home/comp/zhanzhao/sglsim/AegisKV/doc/Archived/
      2026-08-06-pre-kvcache-centric/presentations/presentation/
      experiments/sglsim_large/traces/cc-traces-weka-062126/
      traces.materialized.jsonl
sha256: 29b6a19e751ff5230771519aab755f80a0f43a4ba9cf96b72d3a6a437ec99276
license in local README: Apache-2.0
```

2026-08-29 对该文件的只读流式预审计得到：393个workflow、98,827个model request；46,401个request满足`in<=131072`，52,426个超过目标窗口而必须排除、不能截断。可用分桶为：

| source `in` bucket | requests | workflows |
|---|---:|---:|
| `(0, 8K]` | 6,189 | 371 |
| `(8K, 32K]` | 3,746 | 189 |
| `(32K, 64K]` | 15,099 | 349 |
| `(64K, 96K]` | 12,168 | 370 |
| `(96K, 128K]` | 9,199 | 339 |

其中`126,976≤in≤131,072`的近128K请求有1,164个，覆盖249个workflow，main-agent 663个、subagent 501个，最大可用`in`恰为131,072。因此该真实数据集在source-native计数下具有128K覆盖，不需要padding。

但它不是可直接宣称“Qwen tokenizer精确真实prompt”的数据：本地README明确说明`in = 64-token hash block数量 × 64`，自然语言prompt未提供，极长上下文可能被高估；`hash_ids`只在单个trace内可比，而且subagent group缺少每个parent request的显式id。MoonKVSim必须把它标成`real_trace_shape_replay/source_hash_blocks_64`：长度、并发、时序、main/subagent结构和局部prefix来自真实trace；目标Qwen上的forward/KV byte layout由目标模型模拟。parent edge由时间线推断时保存`edge_origin=inferred`和confidence，不能把推断边冒充原始观测。

不得把历史的`weka_subagent_cdf_*_workload.jsonl`等派生 workload当作新的raw真实trace：这些文件是由workflow metadata构造的模拟器载体，可以作为normalizer回归参考，但正式输入必须回到上述`traces.materialized.jsonl`和固定sample ids重新生成。

上述数字只是当前预审计，不是已迁移/已验证的MoonKVSim artifact。正式使用前仍需在新仓库运行normalizer、生成`TRACE_MANIFEST.json`、复核hash/许可/字段、固定128K筛选集合，并将统计与sample ids写入run manifest。

### 15.2 `failure.json`

负责故障注入层：

```json
{
  "schema": "moonkvsim.failure.v1",
  "enabled": true,
  "events": [
    {
      "failure_id": "f0",
      "type": "GPU_FAILURE",
      "at_s": 30.0,
      "target": {"node_id": "n0", "gpu_id": 0},
      "detection_delay_ms": 100,
      "repair_after_s": null,
      "semantics": "fail_stop_hbm_lost"
    }
  ]
}
```

必须记录：

- `type` 必须且只能为 `GPU_FAILURE`；
- exact physical GPU target，或在启动时解析为具体 GPU 的随机选择规则；
- injection time/distribution，resolved config 中必须展开为 exact virtual timestamp；
- detection；
- 可选 repair；正式首版实验默认关闭；
- 受影响 rank/engine replica 清单；
- reroute规则与无健康target时的显式失败行为。

schema 对其他 failure type 必须 fail-closed 拒绝，而不是忽略或降级为 `GPU_FAILURE`。

### 15.3 `deployment.json`

AegisKV 实验树将这一层落盘为
`benchmark/AegisKV/experiments/configs/engine.json`。计划正文仍使用
`deployment.json` 作为该层的历史名称。

负责部署层：

```json
{
  "schema": "moonkvsim.deployment.v1",
  "model": {
    "id": "Qwen/Qwen3-8B",
    "revision": "",
    "dtype": "bf16",
    "kv_dtype": "bf16",
    "config_sha256": "",
    "kv_layout_path": "resolved/kv-layout.json"
  },
  "engine": {
    "kind": "vllm",
    "source_commit": "",
    "dp_size": 8,
    "tp_size": 1,
    "pp_size": 1,
    "block_size": 16
  },
  "memory": {
    "gpu_profiles": [],
    "host_dram_profiles": [],
    "allocation_alignment_bytes": 256,
    "allocator_granularity_bytes": 2097152,
    "account_fixed_runtime": true,
    "account_fragmentation": true
  },
  "store": {
    "kind": "mooncake",
    "dram_segments": [],
    "eviction_policy": "baseline",
    "allocator": {
      "kind": "source_aligned",
      "granularity_bytes": null,
      "metadata_bytes_per_allocation": null
    }
  },
  "network": {
    "protocol": "rdma",
    "gdr": true,
    "backend": "flow_contention",
    "slice_size_bytes": 65536,
    "bandwidth_allocator": "max_min_fair",
    "endpoint_pooling": true,
    "retry_count": 0,
    "registration": {
      "mode": "calibrated",
      "workers_per_context": 4
    },
    "topology_matrix": "configs/topology/hgx-or-cluster.json",
    "nodes": [],
    "nics": [],
    "links": []
  },
  "predictor": {
    "kind": "aiconfigurator",
    "profile": ""
  },
  "policy": {
    "kind": "mooncake_default",
    "resource_accounting": "byte_exact"
  }
}
```

`aegiskv` 分支将 `policy.kind` 改为 `aegiskv` 并加入显式 HBM/DRAM policy 配置。

每个 `gpu_profile` 必须列出物理 HBM、weights、runtime reserve、block allocator、copy engine 和 bandwidth profile；每个 Host/Store profile 必须列出物理容量、固定保留、allocator/alignment、staging pool 和读写 lane；每个 network link 必须列出端点、方向、带宽、延迟、共享域、duplex 和 queue。禁止用集群总显存或总带宽替代逐 GPU/逐 segment/逐 link 配置。

部署配置中的数值必须标记来源：`source_default`、`measured`、`fitted`、`assumed` 或 `sensitivity_only`。例如 slice size 可用 Mooncake 文档的 64 KiB 启动，但在锁定 commit 后必须核对源码并写入 source-map；带宽、setup、registration、weights/runtime reserve 和 allocator fragmentation 都不得从厂商峰值或理论公式直接冒充有效观测值。

首版正式实验中 `retry_count=0`，不注入连接、NIC 或链路错误；secondary NIC 只参与正常 topology-aware path selection/striping。由 `GPU_FAILURE` 触发的 transfer cancellation 直接进入 abort 结算，不重试到另一网络路径。以后若扩展其他 failure type，必须升级 failure schema 和实验协议，不能偷偷复用首版结果。

resolved deployment 必须展开为无继承、无默认歧义的逐资源清单：每个 GPU、NUMA node、Host DRAM pool、Store DRAM segment、PCIe/NVLink/NIC/fabric link 和 queue 都有稳定 `resource_id`。模拟器只读取 resolved 文件，原始简写配置只负责生成它。

首版 deployment schema 不提供 `ssd_segments`、NVMe/NVMe-oF、`LOCAL_DISK` 或 persistence 参数；出现这些字段时按 unknown/forbidden field 失败，不能忽略。

### 15.4 Run manifest

每次运行生成：

```text
resolved-config.json
manifest.json
SHA256SUMS
```

manifest 必须包括：

- 三个配置文件及 hash；
- code commit和dirty状态；
- source-lock hash；
- predictor database hash；
- workload trace hash；
- raw/normalized trace hash、normalizer hash与trace provenance；
- tokenizer/model/chat-template fingerprint；
- workflow/span/sample count和8K/32K/64K/96K/128K coverage；
- `synthetic=false`、`truncated_count=0`和`overflow_count=0`；
- seed；
- start/end virtual time；
- validation/evidence class；
- result completeness。

## 16. 输出与可观测性

### 16.1 规范化输出

```text
event-journal.jsonl
trace-audit.json
context-coverage.json
workflow-metrics.parquet
request-metrics.parquet
batch-events.parquet
kv-residency-events.parquet
kv-transfer-events.parquet
physical-allocation-events.parquet
resource-ledger-deltas.parquet
resource-ledger-snapshots.parquet
flow-rate-events.parquet
resource-utilization.parquet
store-directory-snapshots.parquet
failure-events.parquet
recovery-events.parquet
capacity-audit.json
run-audit.json
summary.json
```

### 16.2 必须可重建的状态

- 每个 DP rank waiting/running/preempted 队列；
- 每个真实workflow/agent/span的causal release与完成状态；
- 每个span的实际prompt/cached/output/total context tokens和context bucket；
- 每张 GPU 的 HBM账户；
- 每个 Store DRAM segment 的占用；
- 每个 KV block/chunk 的 locations、roles和state；
- 每次 KV 迁移的 source、destination、bytes、start/end；
- 每个 network/resource 的 busy intervals；
- 每个 failure 的检测、fence、reroute和恢复过程；
- 每个请求 TTFT、TPOT、E2E、recompute、restore和WCT贡献。

### 16.3 精确资源输出 contract

`resource-ledger-deltas.parquet` 是容量变化的规范真相源，每行至少包含：

```text
timestamp_ns, stable_sequence, event_id, cause,
resource_id, resource_kind, allocation_id,
object_id, replica_id, transfer_id,
account_from, account_to,
requested_bytes, allocated_bytes, delta_bytes,
before_bytes, after_bytes, capacity_bytes
```

`flow-rate-events.parquet` 记录每次 flow 加入、离开或公平份额变化后的区间：

```text
[start_ns, end_ns), flow_id, transfer_id, slice_id, cause,
path_resource_ids, payload_bytes, remaining_bytes,
allocated_rate_Bps, queue_wait_ns, service_ns
```

`resource-ledger-snapshots.parquet` 和 `resource-utilization.parquet` 都是从 delta/flow event 确定性派生的加速产物，不能成为第二真相源。绘图脚本可以按固定 virtual-time interval 采样，但必须保留事件边界，避免短暂 staging/pending 峰值被平均掉。

每次 run 自动生成以下资源摘要：

- 每张 GPU 各 HBM account 的 time-weighted mean、p50/p95、peak、peak timestamp；
- 每个 Host/Store segment 的 committed、pending、staging、fragmentation、free；
- 每条 PCIe/NVLink/NIC/fabric/DRAM 资源按 cause 的 bytes、byte-time、busy time 和 utilization；
- scheduler/controller/Master/Store CPU 与 RPC worker 按操作类型的 calls、queue time、service time 和 utilization；
- 每类 KV operation 的 source pin、destination reserve、staging、queue、transfer、commit、release 各阶段时间；
- AegisKV 相对 matched baseline 的额外 HBM/DRAM 峰值、额外传输量和节省的 recompute/forward 时间。

## 17. 仓库结构

原则：目录、公开类名、服务边界和配置术语尽量镜像 Mooncake，而不是自行抽象为 `store/mooncake`。类似 SGLSim 对 pinned SGLang 的做法，MoonKVSim 的实现放在 `python/moonkvsim/` 下，但相对模块名尽可能对应 Mooncake 的 `mooncake-common`、`mooncake-store`、`mooncake-transfer-engine`、`mooncake-integration` 和 `mooncake-wheel`。

```text
MoonKVSim/
├── README.md
├── DESIGN.md
├── MOONKVSIM_PLAN.md
├── pyproject.toml
├── reference/
│   ├── source-lock.json
│   ├── source-map.md
│   ├── vllm-notes.md
│   ├── mooncake-common-notes.md
│   ├── mooncake-store-notes.md
│   ├── transfer-engine-notes.md
│   ├── aiconfigurator-notes.md
│   └── fidelity-gaps.md
├── schemas/
│   ├── requests.schema.json
│   ├── failure.schema.json
│   ├── deployment.schema.json
│   ├── multi-agent-trace.schema.json
│   └── run-manifest.schema.json
├── traces/
│   ├── README.md
│   ├── TRACE_MANIFEST.json
│   ├── raw/                         # access-controlled; normally not committed
│   ├── normalized/
│   └── scripts/
│       ├── normalize_trace.py
│       ├── tokenize_trace.py
│       └── audit_128k_coverage.py
├── python/moonkvsim/
│   ├── common/
│   │   ├── types.py
│   │   ├── status.py
│   │   └── hash.py
│   ├── store/
│   │   ├── master_service.py
│   │   ├── master_client.py
│   │   ├── client_service.py
│   │   ├── segment.py
│   │   ├── replica.py
│   │   ├── allocation_strategy.py
│   │   ├── eviction_strategy.py
│   │   ├── metadata_store.py
│   │   ├── transfer_task.py
│   │   ├── tenant_quota.py
│   │   └── kv_event/
│   ├── transfer_engine/
│   │   ├── transfer_engine.py
│   │   ├── transfer_engine_impl.py
│   │   ├── multi_transport.py
│   │   ├── topology.py
│   │   ├── memory_location.py
│   │   ├── transfer_metadata.py
│   │   └── transport/
│   │       ├── base.py
│   │       ├── tcp.py
│   │       ├── rdma.py
│   │       └── nvlink.py
│   ├── integration/vllm/
│   │   ├── scheduler.py
│   │   ├── block_manager.py
│   │   ├── mooncake_connector.py
│   │   └── mooncake_store_connector.py
│   ├── wheel/
│   │   ├── async_store.py
│   │   ├── buffer_pool.py
│   │   ├── mooncake_config.py
│   │   └── mooncake_store_service.py
│   ├── simulation/
│   │   ├── global_des.py
│   │   ├── event.py
│   │   ├── resource.py
│   │   ├── allocation.py
│   │   ├── ledger.py
│   │   ├── transaction.py
│   │   ├── network.py
│   │   └── journal.py
│   ├── time_predictor/
│   │   ├── base.py
│   │   └── aiconfigurator.py
│   ├── router/
│   ├── failure/
│   │   ├── gpu_failure.py
│   │   ├── detector.py
│   │   └── schema.py
│   ├── metrics/
│   │   ├── resource_accounting.py
│   │   └── utilization.py
│   └── cli.py
├── benchmark/
│   ├── mooncake_baseline/
│   │   ├── configs/
│   │   ├── scripts/
│   │   ├── results/
│   │   └── figures/
│   └── AegisKV/                    # main仅可含计划/权威输入；其余由aegiskv维护
│       ├── README.md
│       ├── docs/
│       │   ├── patent/
│       │   │   ├── AegisKV专利交底书-final-version.docx
│       │   │   ├── patent-contract.yaml
│       │   │   ├── runtime-clause-evidence.json
│       │   │   ├── SOURCE_MANIFEST.json
│       │   │   ├── SHA256SUMS
│       │   │   ├── audit_patent_contract.py
│       │   │   ├── audit_aegiskv_runtime_contract.py
│       │   │   └── README.md
│       │   └── experiment-protocol.md
│       ├── paper/
│       │   ├── main.tex
│       │   ├── sections/
│       │   ├── bibliography/
│       │   └── figures/
│       └── experiments/
│           ├── configs/
│           │   ├── requests/
│           │   ├── failures/
│           │   └── deployments/
│           ├── scripts/
│           ├── results/
│           ├── figures/
│           └── reports/
├── docs/
│   ├── architecture/
│   ├── calibration/
│   ├── development/
│   └── research/
├── scripts/
├── benchmarks/                     # 可选：镜像 Mooncake 原生 microbench 命名
│   ├── configs/
│   ├── scripts/
│   ├── results/
│   └── figures/
└── tests/
    ├── unit/
    ├── integration/
    ├── differential/
    └── golden/
```

`aegiskv` 分支增加：

```text
python/moonkvsim/aegiskv/
├── controller.py
├── kv_directory.py
├── rental_value.py
├── lazy_refresh.py
├── slack_landlord.py
├── hbm_quota_aimd.py
├── peer_hbm_pool.py
├── dram_pool_policy.py
├── propagation.py
├── recovery_planner.py
├── failure_fence.py
└── audit.py
```

### 17.1 Mooncake 源码到 MoonKVSim 的映射

| Mooncake 源模块/命名 | MoonKVSim 镜像 | 模拟职责 |
|---|---|---|
| `mooncake-common` | `moonkvsim.common` | 公共 id、status、hash、错误和协议类型 |
| `mooncake-store` `master_service` / `master_client` | `moonkvsim.store.*` | 全局对象、replica、placement、quota、commit |
| `client_service` / `segment` / `replica` | 同名 Python 模块 | Store node 容量、local layout 与副本生命周期 |
| `allocation_strategy` / `eviction_strategy` | 同名 Python 模块 | Vanilla 策略；AegisKV hook 不复制第二数据面 |
| `transfer_task` / `kv_event` | 同名 Python 模块 | 异步任务与可观察 Store 事件 |
| `mooncake-transfer-engine` | `moonkvsim.transfer_engine` | Segment/Buffer/BatchTransfer 与 topology-aware transport |
| `multi_transport` / `topology` / `memory_location` | 同名 Python 模块 | protocol/path/NIC/NUMA/GPU 选择 |
| `mooncake-integration`、vLLM connectors | `moonkvsim.integration.vllm` | pinned vLLM 与 Store/TE 生命周期适配 |
| `mooncake-wheel` Python 服务与 buffer pool | `moonkvsim.wheel` | 仅镜像与模拟相关的用户态接口，不复刻构建包装 |

命名一致不等于盲目逐行翻译。每个镜像模块必须在 `reference/source-map.md` 写明 upstream 文件/类/函数、commit、保留控制流、抽象点、故意替换点和 differential test。真实线程、RPC、CUDA/RDMA 调用替换为全局 DES 事件，但状态转换顺序仍以锁定源码为准。

### 17.2 AegisKV 资料迁移规则

`/home/comp/zhanzhao/Mooncake` 和 `/home/comp/zhanzhao/sglsim` 都可能有脏工作树、历史版本和仅建模结果，因此不能批量复制整个 `aegiskv`/`AegisKV` 目录。迁移时逐文件登记：

```json
{
  "source_path": "absolute source path",
  "source_repository": "Mooncake or SGLSim",
  "source_commit": "git commit at copy time",
  "source_dirty": true,
  "source_sha256": "...",
  "destination_path": "benchmark/AegisKV/...",
  "role": "design|code-reference|config|script|result|figure|paper",
  "evidence_class": "proposal|implemented|tested|modeled|calibrated|physical",
  "status": "active|historical|superseded",
  "authority": "patent-final|reference-only"
}
```

当前只复制用户明确指定的计划和专利终稿。专利终稿可作为 immutable design input 随 `main` 保存，但 baseline runtime 不得读取 AegisKV policy；旧设计、实验结果、图片和 LaTeX 应在 `aegiskv` 分支创建后按 manifest 精选迁移。来源为模拟或未通过证据门槛的资产必须保留标签，不能因复制进 `paper/` 自动变成论文可用证据。

## 18. 分阶段实施与验收

### M0：项目冻结与初始化

任务：

- [ ] 创建新仓库；
- [ ] 写 README/DESIGN；
- [ ] 固定 Mooncake-style 模块映射与命名规则；
- [ ] 固定 vLLM/Mooncake/SGLSim/AIConfigurator版本；
- [ ] 固定专利终稿 hash 并生成 `patent-contract.yaml`；
- [ ] 创建三层 JSON schema；
- [ ] 将 `failure.schema.json` 的 type enum固定为唯一 `GPU_FAILURE`；
- [ ] 定义真实multi-agent trace schema、normalizer和TRACE_MANIFEST；
- [ ] 锁定tokenizer/chat template并定义128K coverage audit；
- [ ] 建立 CI、lint、test骨架；
- [ ] 建立 evidence class 和 manifest规范。

验收：

- source lock完整；
- source-map逐模块指向固定源码文件/类/函数；
- trace来源、许可/访问控制、hash与normalizer lineage完整；
- 专利 contract逐项有章节、owner和test id；
- 所有架构术语无歧义；
- baseline和AegisKV边界明确；
- 未写任何未经源码核对的调度逻辑。

### M1：通用 DES kernel

任务：

- [ ] stable event heap；
- [ ] single `now_ns`；
- [ ] cancellation；
- [ ] resource calendars；
- [ ] typed capacity/rate/concurrency resource；
- [ ] atomic `ResourceTransaction`；
- [ ] physical allocation与logical role分离；
- [ ] event journal；
- [ ] deterministic replay；
- [ ] invariant audit。

验收：

- 时间不倒退；
- 相同 seed byte-identical结果；
- 资源无非法重叠；
- failure能够取消传输且释放reservation；
- journal可重建状态；
- 每个事件后capacity/rate/refcount invariant通过；
- journal replay与在线ledger byte-identical。

### M2：vLLM engine baseline

任务：

- [ ] request states；
- [ ] causal multi-agent DAG replay；
- [ ] source hash-block与target tokenizer两种token-count mode及证据标签；
- [ ] 131072-token guard且禁止truncation/padding；
- [ ] block manager；
- [ ] 从model config/CacheSpec生成`kv-layout.json`；
- [ ] payload/padding/metadata/fragmentation逐block计费；
- [ ] continuous batching；
- [ ] chunked prefill；
- [ ] decode；
- [ ] preemption/recompute；
- [ ] prefix hash；
- [ ] DP router。

验收：

- 小型golden workload与pinned vLLM的batch/token/block序列对齐；
- raw→normalized trace确定性，token计数与真实采集端可解释；
- causal replay保留agent依赖、fan-out/fan-in和tool delay；
- 逐GPU HBM账户与pinned vLLM block分配/释放trace一致；
- HBM容量逐事件守恒，prefix alias不重复计费；
- DP replica独立调度但共享全局时钟。

### M3：AIConfigurator

任务：

- [ ] engine-neutral prediction schema；
- [ ] vLLM batch adapter；
- [ ] prefill/decode预测；
- [ ] profile fingerprint；
- [ ] modeled profile/assumption manifest 与参数敏感性输出。

验收：

- predictor不依赖HiCache；
- forward与I/O分开；
- shape-aware 输入、组合公式和参数来源可审计；
- 未校准结果明确标记 `modeled/preliminary`，不得报告物理误差或准确率。

### M4：Mooncake Store baseline

任务：

- [ ] Master；
- [ ] directory；
- [ ] segments；
- [ ] allocator；
- [ ] Store Client；
- [ ] Put/Get/Remove；
- [ ] DRAM-only Store；
- [ ] eviction；
- [ ] Transfer Engine资源路径；
- [ ] Segment/Buffer/BatchTransfer切片与多transport；
- [ ] topology-aware NIC/path selection；
- [ ] endpoint warm/cold与flow contention；

验收：

- DP0写入后DP1可query/load；
- pending不可见；
- committed才可复用；
- Master不搬字节；
- Store DRAM容量逐segment、逐replica、逐slice守恒；
- local/remote segment路径正确；
- pending/committed/staging/fragmentation可由ledger重建；
- selected communication golden cases与外部模型/trace在声明容差内。

### M5：Baseline GPU failure与端到端 DES replay

任务：

- [ ] 唯一 `GPU_FAILURE` 注入与fail-stop语义；
- [ ] 失败GPU上的forward、HBM和transfer取消；
- [ ] fence与reroute；
- [ ] Store prefix load；
- [ ] missing suffix recompute；
- [ ] repeated source-frozen GlobalDES validation；
- [ ] baseline simulation experiment smoke。
- [ ] 真实multi-agent trace从短上下文到128K的端到端replay。

验收：

- reroute后无重复输出；
- committed Store KV可跨DP恢复；
- failed GPU上的副本不可用；
- results可复现；
- 128K样本来自真实trace且无截断/合成padding；
- 非`GPU_FAILURE`配置在启动前被schema拒绝；
- Host/Store/Master/network状态在GPU故障前后保持守恒且可用；
- 发布`v0.1.0-mooncake-baseline`。

### M6：冻结终稿契约并创建 `aegiskv` 分支

任务：

- [ ] 审核专利终稿的 checksum 与 OOXML 可读性；
- [ ] 生成并人工核对 `patent-contract.yaml`；
- [ ] 从baseline tag创建分支；
- [ ] 冻结KV role/state/schema；
- [ ] 转录并测试reuse+recovery统一租值公式与Lazy Refresh；
- [ ] 定义Peer-HBM和Store DRAM边界；
- [ ] 更新算法、配置、测试和artifact协议。

验收：

- 设计无HiCache overlay语言；
- 每个终稿约束均有代码 owner 和 test id；
- DRAM明确等于global Store DRAM；
- 一个副本只计费一次；
- 独立tier语义保持；
- 禁止HBM→DRAM destage。

### M7：AegisKV normal path

任务：

- [ ] sealed chunks；
- [ ] Peer-HBM candidate；
- [ ] Store DRAM candidate；
- [ ] independent admission；
- [ ] PENDING/COMMITTED/ABORTED；
- [ ] SlackLandlord；
- [ ] unified role；
- [ ] HBMQuotaAIMD。
- [ ] 每个Aegis allocation/transfer写入cause-tagged resource transaction；
- [ ] Peer-HBM/DRAM常驻、pending、staging和传输占比分项输出。

验收：

- HBM_ONLY/DRAM_ONLY/HBM_AND_DRAM/BYPASS均有测试；
- 一个tier失败不终止另一个；
- bytes来自source production buffer；
- Store DRAM副本可被普通cache lookup复用；
- dual-role副本只占一次物理容量；
- capacity/rent/frontier与资源归因审计通过。

### M8：AegisKV GPU failure path

任务：

- [ ] route version；
- [ ] failure fence；
- [ ] standby rotation；
- [ ] recovery source选择；
- [ ] Peer-HBM activation/load；
- [ ] Store DRAM load；
- [ ] recompute；
- [ ] silent replay；
- [ ] atomic output activation。
- [ ] recovery destination reserve、source pin、load staging与释放事务。

验收：

- stale route不能输出；
- incomplete shards不能恢复；
- failed target的Peer-HBM不能重新标记；
- independent Store DRAM record保留；
- 恢复过程和容量hold完整可审计。
- recovery/abort后所有ledger和refcount回到合法状态。

### M9：纯模拟实验和图像资产

任务：

- [ ] baseline/AegisKV matched runs；
- [ ] GPU failure target/timing/rate matrix；
- [ ] 8K/32K/64K/96K/128K真实上下文分桶与coverage audit；
- [ ] scale/sensitivity；
- [ ] ablation；
- [ ] figure scripts；
- [ ] report与evidence matrix。
- [ ] AegisKV SOURCE_MANIFEST与SHA256SUMS；
- [ ] `benchmark/AegisKV/docs|paper|experiments`完整性审计。

验收：

- 所有图由规范化结果自动生成；
- 图中的每个点可追溯到manifest；
- 所有结果明确限定为 modeled/preliminary E2，禁止 calibrated/physical claim；
- 没有缺失cell或静默fallback；
- 真实trace provenance、DAG、tokenizer和128K coverage gate通过；
- 每个 capacity/rate/overlap 参数均有 source-derived 或 assumed provenance，且
  `UNATTRIBUTED_RESERVE=0`；
- 资源峰值由event boundary计算，图表采样不会隐藏瞬时reserve/staging峰值；
- paper-ready gate单独审计。

## 19. 测试计划

### 19.1 Unit tests

- event排序和取消；
- resource reservation；
- HBM/Host DRAM/Store DRAM账本；
- KV layout与TP/PP shard字节公式；
- allocator alignment、padding和fragmentation；
- logical alias/dual-role不增加物理容量；
- `PENDING→COMMITTED`只换账户、不改变总占用；
- abort/evict/failure完整释放或转为unavailable；
- rate resource max-min分配与flow重新计算；
- KV state machine；
- block hash和namespace；
- allocator/eviction；
- predictor adapter；
- trace normalization determinism与schema；
- tokenizer/chat-template fingerprint和token计数；
- multi-agent DAG cycle/missing-parent/fan-in检查；
- observed/inferred parent edge、confidence和ambiguous-edge审计；
- 131072-token guard、overflow fail和zero truncation；
- failed-GPU allocation/route invalidation；
- route version与fence。
- failure schema只接受`GPU_FAILURE`；

### 19.2 Integration tests

- 单DP推理；
- 多DP并发；
- 真实multi-agent causal trace replay；
- Weka source-hash-block normalization与同trace prefix scope；
- 128K context prefill/chunked-prefill/decode与GPU failure恢复；
- 跨agent真实token block prefix reuse；
- DP0→Store→DP1复用；
- DRAM capacity pressure；
- GPU failure reroute；
- network contention；
- source/target GPU failure终止pending transfer；
- GDR与TCP staging路径的容量/速率差异；
- 同时发生Put/Get/recovery时逐资源占比正确；
- journal replay重建逐GPU/segment/link状态。

### 19.3 Differential tests

- vLLM scheduler trace；
- 有原文样本的tokenizer output与pinned tokenizer对齐；Weka样本的`in/hash_ids/block_size`与source记录对齐；
- block allocate/free trace；
- vLLM实际KV cache bytes/block与MoonKVSim `kv-layout.json`；
- Mooncake API/state sequence；
- Mooncake allocator requested/allocated bytes与slice placement；
- default eviction order；
- connector metadata；
- cross-DP prefix hit。

### 19.4 AegisKV tests

- 四种tier组合；
- HBM/DRAM independent admission与单路取消；
- Peer target GPU failure-before-commit；
- source GPU failure-during-transfer；
- simultaneous GPU failure/commit；
- route rotation；
- partial shard completion；
- HBM AIMD contraction；
- unified reuse/protection role；
- request completion后reuse保留；
- Peer-HBM与DRAM两条并发路径各自准确预留/提交/释放；
- Aegis资源增量可从cause tag与matched baseline重建。

## 20. 验证与证据分级

### E0：设计

只有文档、schema和源码映射。

### E1：静态实现

代码存在、类型检查和单元测试通过；不能声称运行时或性能正确。

### E2：模拟器语义验证

golden/differential trace、KV block bytes、allocator state 与逐事件 ledger 对齐；可以声称控制流、状态机和资源记账精确，但不能声称链路/设备时延已物理校准。

### E3：组件校准

forward、transfer、Store、network、copy/CPU overlap 分别有物理测量；可以声称该参数区间内的资源时间占用经过校准。

当前纯模拟交付不执行 E3。

### E4：端到端验证

小规模真实vLLM+Mooncake与MoonKVSim matched；可以报告simulator accuracy。

当前纯模拟交付不执行 E4。

### E5：论文实验

完整matrix、重复、置信区间、audit和provenance通过；才可作为论文结论。

当前交付可以运行完整的 modeled matrix 并生成图像，但其证据仍停留在 E2，
不得因 matrix 完整而升级为 E5 或论文结论。

任何低等级证据不得自动升级为高等级证据。

## 21. 实验矩阵

### 21.1 系统对比

```text
Recompute only
Vanilla Mooncake DRAM
Static Peer-HBM
AegisKV DRAM only
AegisKV Peer-HBM only
AegisKV HBM+DRAM
Full AegisKV unified manager
```

### 21.2 消融

- 无Slack；
- 无reuse value；
- 无recovery value；
- 两套manager而非unified manager；
- 无AIMD；
- static HBM quota；
- random/LRU/LFU eviction；
- 无Peer-HBM跨GPU anti-colocation约束（仅作机制负对照，不作为合法保护配置）；
- 无cache-aware routing；
- 不同chunk size。

### 21.3 敏感性

- DP/TP/PP规模；
- 真实trace中观测到的并发区间；
- 8K/32K/64K/96K/128K实际上下文分桶；
- 真实token决定的prefix sharing程度；
- agent workflow长度和criticality；
- GPU failure time/target/rate（type固定）；
- HBM budget；
- Store DRAM budget；
- RDMA/TCP/GDR；
- NIC/fabric带宽；
- Store node数量；
- detection/reroute delay。

### 21.4 重复性

- matched seed；
- baseline/treatment使用相同请求和failure schedule；
- baseline/treatment使用同一normalized trace、workflow/span集合、tokenizer和causal release规则；
- 至少多个独立seed；
- 报告均值、分位数和置信区间；
- 明确剔除/失败run；
- 禁止只选择成功run。

### 21.5 真实 trace 完整性

- 主结果列出 trace 来源、采集区间、multi-agent framework、workflow/agent/span 数量和访问限制；
- 报告每个 context bucket 的样本数、tokens、prefix reuse、并发和GPU failure覆盖；
- 128K cell 必须由真实 span 贡献，并单独列出其 `context_before_step` 与 output reserve；
- 不把同一长请求切片后当作多个独立128K样本，不跨workflow拼接上下文；
- 隐私清洗只能删除/哈希内容字段，不能改变 token ids、长度、DAG、时间关系和prefix identity；任何改变都记录在normalizer manifest；
- 数据许可不允许发布原文时，发布schema、统计量、hash、normalizer和可审计的token/block派生信息。

## 22. 论文图像计划

### F1：系统架构

vLLM replicas、Router、global directory、Store Master、Store nodes、Peer-HBM和统一KV role。

### F2：故障恢复时间线

failure→detection→fence→reroute→load/recompute→silent replay→resume。

### F3：每GPU HBM占用时间线

逐 GPU stacked area：weights、runtime、active primary KV、inactive reusable KV、Peer-HBM、recovery reserve、staging、fragmentation、free/unavailable；在同一时间轴标注 failure、admission、transfer commit、eviction 和 recovery。主图用真实 `allocated_bytes`，附图对比 payload 与 padding/fragmentation。

### F4：Store DRAM占用时间线

逐 Store node/segment stacked area：pending、committed、evicting、transfer staging、allocator metadata、fragmentation、free；同时给 local/remote placement 分面。首版 GPU failure 不产生 Store `unavailable`。

### F5：KV迁移Gantt

展示 D2D、D2H、RDMA/TCP、H2D 的 reserve、queue、slice transfer、commit、release 阶段，并在下方对齐 PCIe/NVLink/NIC/fabric/DRAM 的 cause-stacked utilization。图中每个 bar 必须可追溯到 transfer/slice/allocation id。

### F6：端到端WCT/goodput

baseline与AegisKV matched comparison。

### F7：恢复延迟CDF

按Peer-HBM、Store DRAM和recompute分组。

### F8：保护覆盖与重算

protected continuous prefix、restore tokens、recompute tokens。

### F9：策略消融

Slack、reuse value、AIMD、unified manager。

### F10：预算敏感性

Peer-HBM/Store DRAM预算与WCT、goodput、恢复收益。

### F11：规模扩展

DP数量、Store nodes、网络带宽与性能。

### F12：模拟器准确性

AIConfigurator、传输和端到端observed-vs-predicted误差。

F12 需要 E3/E4 观测值，当前纯模拟交付不生成该图；其编号仅为未来高等级证据保留。

### F13：AegisKV 资源成本分解

相对 matched Vanilla Mooncake，展示 AegisKV 额外 Peer-HBM byte-seconds、Store DRAM byte-seconds、staging peak、网络 byte-time、copy-engine busy time，以及节省的 recompute GPU time；同时给绝对值和增量，避免只报告收益不报告资源成本。

### F14：资源峰值与平均占比

按 DP/GPU/Store node 展示 time-weighted mean、p95、peak occupancy/utilization 及不均衡度；peak 必须来自事件边界而非粗粒度采样。

### F15：真实 multi-agent trace 与 128K 覆盖

展示 workflow DAG规模、agent fan-out/fan-in、真实并发、context length分布，以及8K/32K/64K/96K/128K各bucket的样本数；叠加不同上下文下的HBM KV占用、Store DRAM占用、恢复tokens和WCT。图注必须明确128K是单次model context而不是workflow累计tokens。

## 23. 通信调研结论、校准与外部验证

本节记录未来可选的 E3/E4 提升路径，不属于当前执行范围。当前实现只使用 C0
源码/文档派生值或显式 assumed 参数，并对它们做 DES sensitivity；不启动 C1-C5
中的 microbench、外部校准后端或实机任务。

### 23.1 采用方案

MoonKVSim 应自研与全局 DES 原生集成的 `flow_contention`，而不是把 ASTRA-Sim、SimAI 或 ns-3 作为核心 runtime：

- Mooncake 的通信对象是 `Segment` 和 `BatchTransfer`，具有 Buffer 注册、拓扑感知选 NIC、切片、多 transport 和 endpoint 生命周期；这些语义必须直接嵌入 KV 状态机；
- ASTRA-Sim 提供系统/网络的多精度插件接口，其 analytical backend 同时有 congestion-aware 和 congestion-unaware 模型，适合验证拓扑和共享带宽算法；
- SimAI 提供 analytical 与 ASTRA+ns-3 的精细模式，可借鉴多请求推理和多精度组织方式；
- ns-3 是 packet-level DES，适合少量网络 golden cases，但全量 KV/请求/故障实验使用它成本过高，且仍需额外桥接 Mooncake 状态机。

结论是“两层验证”：常规运行使用可解释、可校准的 slice/flow 模型；选定微案例再用 ASTRA congestion-aware 或 ns-3/SimAI 做交叉验证。若两者差异超过预设阈值，扩大 sensitivity 区间或降低证据等级，不用一个全局修正因子掩盖误差。

### 23.2 校准阶梯

| 阶段 | 数据 | 拟合参数 | 通过条件 |
|---|---|---|---|
| C0 源码/文档 | locked Mooncake defaults、拓扑规则 | slice、retry、NIC eligibility、queue depth | 与固定 commit 一致 |
| C1 Transfer Engine microbench | `tebench`/`transfer_engine_bench`，按 block size、batch、concurrency | submit/setup、warm/cold endpoint、registration、effective BW | 分方向/协议/尺寸报告 p50/p95 误差 |
| C2 路径拆解 | GPU↔GPU、GPU↔DRAM、DRAM↔DRAM | copy/PCIe/NUMA/NIC/DRAM 参数 | 不用 aggregate scale，瓶颈可解释 |
| C3 拥塞 | 多 initiator、多 target、多 NIC、incast/striping | fairness、oversubscription、queueing | 完成顺序和吞吐曲线与 trace 对齐 |
| C4 外部模拟 | ASTRA analytical；选定 ns-3/SimAI 案例 | 模型偏差区间 | golden topology 在容差内或明确标记 gap |
| C5 小规模实机 | vLLM+Mooncake end-to-end trace | 未建模 residual | forward、KV I/O、queue、E2E 分项报告 |

每个 calibration record 至少包含：硬件拓扑、Mooncake/vLLM commit、protocol、GDR、方向、bytes、batch/concurrency、NIC 数、warm/cold、原始 trace、拟合方法、train/test split、p50/p95/max error 和 SHA256。模型参数只在匹配的硬件 profile 内生效，跨平台只能标记 extrapolated。

### 23.3 官方研究入口

- [Mooncake Transfer Engine design](https://kvcache-ai.github.io/Mooncake/design/transfer-engine/index.html)：Segment、BatchTransfer、transport、拓扑感知选路、切片和 endpoint 管理。
- [Mooncake Store design](https://kvcache-ai.github.io/Mooncake/design/store/mooncake-store.html)：参考全局 Store、replica、allocation、DRAM 与多 NIC striping；MoonKVSim 首版明确不实现其中的 SSD 路径。
- [Mooncake Transfer Engine benchmark guide](https://kvcache-ai.github.io/Mooncake/performance/mooncake/tebench.html)：按 block size、batch size 和 concurrency 的校准入口。
- [ASTRA-Sim](https://github.com/astra-sim/astra-sim) 与 [analytical network backend](https://github.com/astra-sim/astra-network-analytical)：多精度系统模拟和拥塞感知/非感知网络模型。
- [SimAI](https://github.com/aliyun/SimAI)：analytical 与 ASTRA+ns-3 两类精度路径。
- [ns-3](https://www.nsnam.org/)：用于选定 packet-level 网络验证案例。

这些外部项目只提供建模依据或验证后端。采用前仍需锁定版本、许可证和 adapter 输入输出；“找到模拟器”不等于 MoonKVSim 已经完成通信校准。

## 24. 主要风险与应对

### 风险 1：vLLM 源码版本不明确

应对：先获取和固定源码，不在此之前实现调度器。

### 风险 2：直接复用 SGLSim 导致 SGLang 语义泄漏

应对：只抽取通用 DES/predictor schema，不复用 HiCache、ScheduleBatch或tier enum。

### 风险 3：Mooncake baseline 被弱化

应对：baseline必须支持跨DP Store reuse和故障后读取已提交Store KV。

### 风险 4：双重 KV 计费

应对：global directory唯一真相源；physical copy与logical roles分离。

### 风险 5：AIConfigurator 校准不可迁移

应对：对vLLM重新采集prefill/decode校准，不沿用HiCache scale。

### 风险 6：传输时间被aggregate delay隐藏

应对：每个copy显式预约所有物理资源并记录start/end。

### 风险 7：模拟器结果被过早当成论文证据

应对：执行E0-E5证据门槛；paper-ready单独审计。

### 风险 8：`main` 与 `aegiskv` 漂移

应对：baseline tag、通用bugfix先main、matched config和source-lock强制检查。

### 风险 9：字节账本精确被误当成物理时间准确

应对：E2 只证明源码对齐的 allocation/accounting；link、copy、CPU 与 overlap 必须达到 E3/E4 才能声称 calibrated accuracy。

### 风险 10：隐藏 reserve 与 allocator 碎片被漏算

应对：逐 rank 对齐 vLLM 启动后的 weights/runtime/KV pool，逐 segment 对齐 Mooncake allocator；未解释差值进入显式 `UNATTRIBUTED_RESERVE` 并使 paper-ready gate 失败，禁止偷偷并入 free。

### 风险 11：真实 trace 不含足够 128K 样本

应对：先运行 `audit_128k_coverage.py`；不足时将对应实验标记 blocked并继续采集真实multi-agent trace，不复制、拼接、padding或随机生成长prompt。

### 风险 12：Mooncake SSD 语义意外进入首版

应对：source-map将SSD/NVMe相关upstream模块标记out-of-scope；schema、enum、factory和golden tests共同拒绝 `STORE_SSD`/`LOCAL_DISK`/NVMe配置，结果审计要求此类location/event计数为零。

## 25. Definition of Done

### 25.1 `main` 完成

- [ ] pinned vLLM semantics已对齐；
- [ ] Vanilla Mooncake Store语义已对齐；
- [ ] 真实multi-agent trace provenance、normalization和causal replay通过审计；
- [ ] 正式trace含真实128K context样本且无截断/合成padding；
- [ ] 首版runtime/config/output均无SSD/NVMe tier或隐式fallback；
- [ ] 跨DP shared KV可用；
- [ ] 无持久私有Host L2；
- [ ] 全局虚拟时钟驱动全部组件；
- [ ] AIConfigurator只驱动forward；
- [ ] `kv-layout.json`与pinned vLLM实际CacheSpec/block bytes对齐；
- [ ] 每个GPU/Host/Store segment使用字节级物理账本；
- [ ] payload、padding、metadata、fragmentation和staging分别计费；
- [ ] 容量、速率、并发、refcount和资源竞争逐事件严格审计；
- [ ] event journal可byte-identical重建全部ledger；
- [ ] baseline `GPU_FAILURE`/reroute可运行；
- [ ] runtime不存在其他fault injector或隐藏随机failure；
- [ ] source-frozen 全局 DES 重复运行及 byte-identical 审计完成；
- [ ] 发布`v0.1.0-mooncake-baseline`。

### 25.2 `aegiskv` 完成

- [ ] unified directory是唯一KV真相源；
- [ ] cache reuse和failure protection互相可见；
- [ ] Peer-HBM与Store DRAM独立准入；
- [ ] 四种residency组合完整；
- [ ] 无HBM→DRAM writeback；
- [ ] 所有AegisKV资源变化有cause tag且不重复计费；
- [ ] Peer-HBM/DRAM并发路径的reserve/transfer/commit/abort资源事务完整；
- [ ] failure/fence/reroute/recovery/silent replay闭环；
- [ ] 每个DP/GPU/Store/transfer状态可观测；
- [ ] 相对baseline的HBM/DRAM/网络/copy-engine资源增量可重建；
- [ ] matched baseline/AegisKV实验完成；
- [ ] 所有matched实验使用同一真实trace span集合和128K coverage；
- [ ] 所有时延和性能字段保持 modeled/preliminary 且无物理准确性声明；
- [ ] 完整纯模拟实验matrix和图像通过provenance audit。

## 26. 立即执行顺序

1. 历史启动状态：先在 `/home/comp/zhanzhao/MoonKVSim` 放置本计划和专利终稿副本；当前实施进度与证据边界以 `docs/development/milestone-status.md` 为准。
2. 初始化 Git/`main`，创建 `README.md`、`DESIGN.md`、`reference/source-lock.json` 与 source-map 骨架。
3. 核验并锁定本机 vLLM 源码、Mooncake vanilla baseline、SGLSim DES/AIConfigurator 参考版本；记录 dirty 状态和 hash。
4. 从专利终稿生成 `patent-contract.yaml`，人工核对公式、状态、独立准入、Lazy Refresh、传播和恢复语义。
5. 写 request/failure/deployment、multi-agent trace 和 resolved manifest schema；SSD/NVMe字段必须被拒绝。
6. 导入真实multi-agent trace，完成provenance、normalization、tokenizer与128K coverage审计。
7. 实现独立 GlobalDES kernel、typed resource ledger、atomic transaction、flow engine 和 event journal，不迁移任何 SGLang tier。
8. 用 toy workload验证稳定事件排序和逐事件守恒；toy数据只用于测试，不进入实验结果。
9. 依照 source-map 实现 pinned vLLM scheduler/block manager，生成并核对 `kv-layout.json`，再接入 engine-neutral AIConfigurator adapter。
10. 按 Mooncake 同名模块实现 DRAM-only Master/Client/Segment/Replica/Transfer Engine baseline。
11. 用源码派生或显式 assumed 参数完成通信资源、拥塞模型和敏感性验证；不执行
    C1-C5 校准阶梯。
12. 完成真实trace跨 DP Store reuse、128K context、baseline `GPU_FAILURE`/reroute
    与重复的端到端 GlobalDES replay。
13. 发布 `v0.1.0-mooncake-baseline`；只有验收通过后才从该 tag 创建 `aegiskv`。
14. 在 `aegiskv` 分支实现专利终稿的 normal path、GPU failure path、Peer-HBM/DRAM 独立 manager 与审计。
15. 按 SOURCE_MANIFEST 从 Mooncake/SGLSim 精选迁移 `benchmark/AegisKV/docs|paper|experiments` 资产。
16. 对真实trace执行纯模拟 matched 实验、生成全部图像，并分别通过128K coverage、
    completeness、determinism、provenance 与 modeled-scope gate；不得标记为 calibrated、
    physical 或 paper-ready。

---

本计划是 MoonKVSim 的实施规范，不代表任何模块已经实现、校准或验证。后续每个 milestone 应更新独立状态、验收证据和未决问题，不能用计划完成度替代代码与实验完成度。
