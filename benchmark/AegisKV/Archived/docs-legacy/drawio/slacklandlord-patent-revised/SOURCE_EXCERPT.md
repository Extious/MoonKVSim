# 原专利公式与算法来源

原文保留供对照；现有 Agent 方案的修改见 README。段落按 document.xml 中 w:p 零起始计数。

## 段落 89

工作流运行时为每个当前请求提供 Slack，并附带请求标识、观测时间和版本。同一智能体连续发出的不同请求分别使用各自的当前 Slack；新值到达时覆盖旧版本，执行期间可按经过时间递减。Slack 的具体计算方法不构成本保护点的限制。

## 段落 90

对资源层 r∈{Peer-HBM, DRAM}，令 Tir(Sir) 为只依据本层已确认连续保护前沿计算的立即故障恢复时间，其中包含本层加载、未保护后缀重算和静默重放。其 Slack 可见恢复损失为 Jir(Sir,t)=max(Tir(Sir)-si(t),0)。候选 x 的工作流恢复收益为 Wxr=max(Jir(加入前)-Jir(加入后),0)。Slack 越小且本层副本越能缩短恢复，Wxr 越大。

## 段落 91

令 px(t) 为候选命中或再次复用概率，Cxr 为一次复用可节省的加载或重算代价，Uhitxr=px(t)·Cxr；令 Ulrux=ψ(t-tlastx)，其中 ψ 随距最近访问时间增大而单调减小。本层复合收益为 Gxr=λwWxr+λhUhitxr+λlUlrux，λw>0，λh、λl≥0。单位字节优先级 Pxr=Gxr/bx，租值键 Hxr=Lr+Pxr。由此，传统命中率和 LRU 信息仍参与判断，而 Slack 通过故障恢复收益 Wxr 使工作流中更关键的请求获得更高保护优先级。

## 段落 93

Router 先为每个路由版本固定满足模型版本、KV 格式、并行布局和故障域约束的 Peer-HBM 目标。Peer-HBM 与 DRAM 分别维护租金 Lr、容量、每请求连续尾部和本池最小堆，并各自调用 SlackLandlord。另一层的接纳结果和已有副本不替代本层判断，因此可形成仅 HBM、仅 DRAM、两层都有或两层都没有四种结果。

## 段落 94

Slack、命中统计、最近访问时间或连续前沿变化时，系统只更新相应版本。当某个尾部成为堆顶或因前一尾部被选中而新暴露时，系统才按最新信号执行 Lazy Refresh；隐藏分块保留原键。候选复合收益超过本层拟淘汰集合的联合损失且容量可满足时，系统撤销并释放淘汰集合，分配最终空间并建立 PENDING 记录。源 Worker 从仍存活的生产缓冲区通过 D2D/P2P 复制到目标 HBM，并通过 D2H 直接传入 DRAM；两条路径可并行或分别执行，不经过对方中转。只有全部必要分片、路由版本、模型版本、KV 格式和布局均校验通过且物理传输完成，本层记录才转为 COMMITTED；失败路径转为 ABORTED 并释放本层空间，不改变另一层。故障时先隔离旧执行方，只使用已确认副本，其余区间重算。

## 段落 110

S1. 工作流运行时为当前请求 i 提供 Slack si(t)、观测时间和版本；KV 管理器同时读取候选 x 的命中率估计 px(t)、最近访问时间 tlastx、复用可节省代价 Cxr、字节数 bx 和本层连续保护前沿 Sir。

## 段落 111

S2. 对 r∈{Peer-HBM,DRAM}，分别估计加入 x 前后的立即故障恢复时间 Tir，计算Jir=max(Tir-si(t),0) 以及工作流恢复收益 Wxr=max(Jir(加入前)-Jir(加入后),0)。

## 段落 112

S3. 计算命中复用收益 Uhitxr=px(t)·Cxr，并以随访问间隔增加而减小的函数 ψ 计算 Ulrux=ψ(t-tlastx)。按 Gxr=λwWxr+λhUhitxr+λlUlrux 融合工作流与传统缓存信息。

## 段落 113

S4. 得到单位字节优先级 Pxr=Gxr/bx 和租值键 Hxr=Lr+Pxr。Slack、命中统计或最近访问时间变化时只更新版本；当前尾部在实际参与比较时才按最新信号刷新，不因优先级变化搬运 KV。

## 段落 114

中文伪代码 1：工作流感知的租值型 KV 优先级计算输入：请求 i 的 Slack si(t)，候选 x，资源层 r，前沿 Sir，字节数 bx，命中率 px(t)，最近访问时间 tlastx，租金 Lr。1）估计加入 x 前后的本层恢复时间 Tbefore、Tafter。2）Jbefore←max(Tbefore-si(t),0)，Jafter←max(Tafter-si(t),0)，Wxr←max(Jbefore-Jafter,0)。3）Uhitxr←px(t)·Cxr；Ulrux←ψ(t-tlastx)，其中 ψ 随访问间隔增大而减小。4）Gxr←λwWxr+λhUhitxr+λlUlrux。5）Pxr←Gxr/bx；Hxr←Lr+Pxr。6）返回优先级、租值键和信号版本；信号变化只标记索引键陈旧，不移动 KV。

## 段落 119

S1. 源 Worker 封装完整逻辑分块；Router 为当前路由版本固定兼容 Peer-HBM 目标。Peer-HBM 与 DRAM 分别维护容量、租金 Lr、每请求连续尾部、本池最小堆、索引版本和提交记录。两个资源池互不读取对方的准入结果。

## 段落 120

S2. 对每个资源层分别计算候选复合收益 Gxr、单位字节优先级 Pxr 和接纳阈值 Θxr=Lr+Pxr，读取本层可用容量，并建立本池最小堆的临时视图。

## 段落 121

S3. 容量不足时重复检查本池最小堆，并跳过候选所属请求以保持其前缀依赖。若堆顶键版本陈旧，只刷新该尾部后重新比较；选中尾部后只暴露并刷新同请求的前一尾部。无法找到低于 Θxr 的合法尾部，或候选复合收益不大于淘汰集合 Y 的联合损失时返回 BYPASS；否则撤销 Y、推进租金、分配候选最终空间并建立 PENDING 记录。

## 段落 122

S4. 源 Worker 从生产缓冲区对 HBM 发起 D2D/P2P、对 DRAM 发起直接 D2H；两条路径可并行或分别执行，互不作为中转，并由各自完成回调独立确认。

## 段落 123

S5. 本层全部必要分片、路由版本、模型版本、KV 格式和布局通过校验后，PENDING 才转为 COMMITTED；失败路径转为 ABORTED 并只释放本层空间，另一层记录保持不变。组合两层提交状态得到 HBM_ONLY、DRAM_ONLY、HBM_AND_DRAM 或 BYPASS。

## 段落 124

S6. 源故障时，Router 先隔离旧执行方和输出权限，再冻结已提交连续前沿；系统按剩余 Slack 截止顺序处理请求，只从可访问的 COMMITTED HBM 或 DRAM 副本恢复，其余区间静默重算到已提交输出位置。请求结束时等待两条路径均提交或终止后再清理。

## 段落 125

中文伪代码 2：动态租值驱动的独立分层 KV 管理输入：已封闭分块 x=(c,r)、当前时刻 t、本层租金 Lr、本池尾部最小堆 Qr；对 Peer-HBM 和 DRAM 分别执行。1）计算 Gxr、Pxr、接纳阈值 Θxr←Lr+Pxr；Y←∅；Q←Qr 的临时视图；f←本层空闲字节。2）当 f<bx：读取 Q 的最小尾部 (y,Hy)，跳过候选所属请求；若 y 的 Slack/命中/LRU/前沿版本陈旧，则 Lazy Refresh 后重新比较。3）若无合法 y 或 Hy≥Θxr，则本层 BYPASS；否则 Y←Y∪{y}，累计可释放字节。4）y 被选中后，只把同一请求新暴露的前一连续尾部按最新版本计算后插入 Q。5）容量满足后计算 Y 的复合联合损失 D_Yr；若 Gxr≤D_Yr，则本层 BYPASS。6）原子撤销并释放 Y；Lr←max(Lr,max_{y∈Y}Hy)；分配 x 的最终空间并记 PENDING。7）源 Worker 发起直接复制：Peer-HBM 使用 D2D/P2P，DRAM 使用 D2H。8）全部必要分片和版本校验通过：按完成时最新信号重算 Gxr，令 Hxr←Lr+Gxr/bx，记 COMMITTED 并加入本层索引；否则记 ABORTED 并释放本层空间。9）组合两层状态得到 HBM_ONLY、DRAM_ONLY、HBM_AND_DRAM 或 BYPASS；恢复只使用 COMMITTED 连续前沿。

## 段落 127

附图 3  动态租值驱动的独立分层 KV 管理流程

