# AegisKV Overview v7：以 Mooncake 的职责边界设计架构

## 定位与证据边界

本方案依据完整 `../draft/system_design.md`。用户所说的“参考 Mooncake”是借鉴组件职责、接口和运行机制；三层视觉布局来自用户参考图。图像相似不能代替架构合理性。

建议沿用 Mooncake 的“控制端维护元数据，客户端直接传输 KV”分工，将 AegisKV Controller 组织为 Store Master 的策略扩展。本地旧原型提供这一部署选择的依据：`/home/comp/zhanzhao/Mooncake/mooncake-store/include/master_service.h:181` 由 Master 持有 AegisController；`include/aegiskv_controller.h:269` 定义 metadata-only、PENDING→COMMITTED 与完成回调。它不是上游已实现 AegisKV 或新策略已经完成的证明。

旧原型仍含 Credit/Alpha/AIMD；新版 K/L 足迹、Slack 整体准入与并行恢复以当前论文为准。`../draft/implementation.md` 明确其端到端实现尚待验证。

## 1. 架构复用与新增职责

| 组件 | 可复用基础 | AegisKV 扩展 |
|---|---|---|
| Router | 请求入口与普通路由，可查询 Conductor 缓存索引 | 传递 DAG 元数据，执行既定 Retry-DP 路由；不按保护顺序串行恢复 |
| Controller / Store Master extension | 副本、容量与成员元数据，异步完成机制 | Workflow Tracker、新 Placement Planner、固定恢复映射、已提交保护覆盖与恢复计划 |
| 每 DP 的 Adapter | 引擎 allocator、调度、块表接口 | 选择器索引观测、Peer 预算/回收、兼容地址绑定、逐层就绪与尾部重放 |
| 每 DP 的 Connector | Mooncake Store Client 与 Transfer Engine | 密封块增量复制、Peer/DRAM 独立路径、完成上报、预取与按需补取 |
| DRAM KV Store | Mooncake Store DRAM 池与对象访问 | 保存保护对象和选择器辅助状态；位置满足故障域约束 |

Adapter/Connector 是职责边界，不要求独立进程，也不与现有代码类强行一一对应。Connector 执行传输并上报完成；Controller 维护可恢复的提交状态。不能让两边各自定义不同的“已提交”覆盖。

当前 [Conductor 文档](https://kvcache-ai.github.io/Mooncake/design/conductor/conductor-architecture-design.html) 将它定义为外部 Router 使用的 KV prefix indexer。因此不直接将 Conductor 等同于 Router，也不把其前缀命中索引当成 `(layer, block)` 恢复目录。Overview 不必展开这一普通路由可选基础的内部事件处理。

[Mooncake Store](https://kvcache-ai.github.io/Mooncake/design/store/mooncake-store.html) 提供对象/副本管理，[Transfer Engine](https://kvcache-ai.github.io/Mooncake/design/transfer-engine/index.html) 提供注册内存的异步读写。“GPU 字节已写入”仍不等于“引擎可直接计算”：本地使用 Peer KV 还要求 model revision、KV layout、TP shard、块地址绑定兼容，由 Adapter 保证。[vLLM 集成](https://kvcache-ai.github.io/Mooncake/deployment/integrations/vllm/index.html) 中直接 PD 传输的 MooncakeConnector 与共享缓存的 MooncakeStoreConnector 也是不同接口。

## 2. 故障检测的边界

DP/worker 提供引擎、GPU 健康或执行进展信息，Master 维护客户端心跳和成员状态，Controller 据此触发恢复。图中通过 `Plans / KV status / health` 控制通道表达，控制面保留 Recovery Manager 和 Master 的 `Replica directory / Membership`。

本地 `MasterService::Ping` 和 `ClientMonitorFunc`（`master_service.cpp:7204,11063`）仅证明成员存活机制；宿主进程心跳正常不证明 GPU 仍在执行。Transfer Engine 链路重试也不负责请求恢复。不应把一个 fail-stop DP 作为唯一故障通知来源。

恢复目标在故障前绑定为 p(g)，Router 执行路由，目标引擎按逐请求就绪条件推进。watchdog、超时、误判、fencing 和控制面 HA 尚未由当前草稿完整定义，Overview 不暗示这些协议已经实现。

## 3. 黑底编号与正文

编号是模块索引，不是执行顺序；两个 DP 上相同模块使用相同编号。

| 编号 | 图中模块 | 当前正文位置 | 留在正文展开 |
|---|---|---|---|
| 1 | Workflow Tracker | §3.2 | P90、CPM、动态 DAG、滞回；图中仅 DAG 输入和 Slack 输出 |
| 2 | KV Placement Planner | §3.2–3.4 | R/D/P、K/L 校准、热块身份、足迹、Slack 排序和整体准入 |
| 3 | Connector | §3.5 复制与提交 | ACK、提交前沿、辅助状态、限速；图中显示 Store Client / Transfer Engine 与独立路径 |
| 4 | Adapter | §3.3 观测，§3.5 引擎执行 | 排名、预算、回收、地址兼容、逐层就绪与尾部重算 |

Router、Recovery Manager、Master 目录与成员管理是架构支撑，不全部编号为独立创新模块。离线校准是 Planner 的参数来源，在表 1 与 §3.3 说明，不画成在线服务。

## 4. 内存与路径

两个 DP 都有相同 Adapter、Connector 和 KV HBM。内存条只表示 KV 池，不包括模型权重与工作区。Local KV 占主体，Peer KV 是较小且可回收的借用区。§3.4 的预算是 B = min(B_cap, pool - watermark - headroom)，默认 B_cap = 4 GiB；画图比例不是固定百分比，也不保证任意时刻 Peer 占用都小于 Local 当前实际占用。

蓝线连接两侧 Connector；橙线分别连接各 Connector 与 DRAM Store，两条保护路径独立。KV 字节不经过 Controller。接管 DP 驻留且兼容的 Peer KV 在本地绑定后直接使用，不经第三张 GPU。双向箭头表示双方具备相同能力，不表示故障后的失效 DP 仍传输。

## 5. §3.1 组织段落候选

> 图 5 展示 AegisKV 的应用、控制和引擎三层架构。应用提供请求所属工作流及 DAG 依赖，Router 负责请求分发。AegisKV 沿用 Mooncake 的元数据与数据传输分工，将 Controller 组织为 Store Master 的策略扩展：① Workflow Tracker 生成 Slack 快照，② KV Placement Planner 决定保护层级及层/块级放置；副本目录记录已提交保护覆盖，Recovery Manager 在失效后通过 Router 将请求交给预先绑定的接管 DP。每个 DP 都包含 ③ Connector 与 ④ Adapter：前者基于 Mooncake Store Client 和 Transfer Engine 执行复制、装载和完成上报，后者连接引擎内部的块观测、Peer 容量管理与逐层恢复。KV 数据直接在 DP 与存储池之间传输，不经过 Controller。

§3.2 介绍 ① 与 ② 的请求分层；§3.3 介绍 ② 的请求内放置及 ④ 的观测接口；§3.4 介绍 ② 的容量竞争；§3.5 按 ③ 复制/提交、④ 前台保护/恢复和控制面故障触发展开；§3.6 保留误差、漂移、选择器适配和证据局限。该组织保留当前算法主线。

## 6. 图注候选

**AegisKV system overview.** The Controller is organized as a Store Master extension. Workflow Tracker (1) derives Slack, KV Placement Planner (2) selects protection and placement, and Recovery Manager initiates retries on preassigned DPs using committed replica metadata and health information. Each DP has the same Connector (3), backed by Mooncake Store Client and Transfer Engine, and Adapter (4), integrating KV management and recovery with the inference engine. Peer and DRAM transfers are independent and bypass the control plane. The smaller Peer region borrows reclaimable KV capacity; proportions are schematic. Black badges identify modules discussed in the text, not execution order. This is the proposed architecture, not an end-to-end implementation result.

## 7. 交付状态

独立 v7 候选；保留当前正文和 canonical 图。提示词见 `system-overview-imagegen-v7-paper-roadmap.prompt.md`。使用内置 imagegen。PNG 封装的 PDF 是位图，不是可编辑矢量。选中图片为 [system-overview-imagegen-v7.png](system-overview-imagegen-v7.png)，SHA256 `8b0579adfe7f9dacf43db0e25cd037179b568ddc690664b2797454d80fea5839`。

最终采用引擎层的聚合请求接口和聚合控制接口；它们都作用于全部 DP，不表示仅连接箭头正下方的某一个 DP。初稿中逐 DP 分支造成误连，经过两次局部生图修改后删除这些分支；最终提示词见 `system-overview-imagegen-v7-wiring.prompt.md`。不再把第一版提示词中的逐 DP 分支要求当成最终图语义。

PDF 与审查图位于 `output/pdf/aegiskv-imagegen-20260918/`（相对项目根目录）。按工作假设 178 mm 宽导出，1430×1100 像素，约 204 DPI；实际查看了 144 DPI 的彩色与灰度 PDF 渲染。三层边界、黑底编号、模块名称、请求/控制接口、两条独立数据路径均可辨认，无标题穿线或裁切。Peer 区均小于 Local 区，但绘制比例不完全相同，不作为数值编码。

限制：Store Client / Transfer Engine 小标签仍偏小；灰度版本依靠直接标签与位置区分两类 KV 路径。此版适合架构讨论，不称为最终投稿版，也不是可编辑矢量。元数据见 `output/pdf/aegiskv-imagegen-20260918/artifact-metadata-v7.json`。
