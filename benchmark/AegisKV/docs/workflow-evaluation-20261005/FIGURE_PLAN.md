# 测量图的具体排版与统计口径

本表为未来 Evaluation 的图规格，不改变原论文 Background/Motivation 的图型。最新用户要求后两节沿用原有图型、绘制方式和风格，只更换 workflow 和新实测数据。其当前图稿与数据口径见 `exports/workflow-motivation-measured-20261005/README.md`；E0--E11 的全面评估仍未完成。最终插入：通常单栏约84.7 mm、宽图168 mm；字号至少10 pt。配对比较同轴、零差值可见；颜色之外用线型/符号/填充区分。

| 图 ID | panel、坐标、图形 | 分组/聚合与误差 | 支持的 claim 与否证条件 |
| --- | --- | --- | --- |
| F1 工作负载 | (a) x=调用数/Agent，y=Agent ECDF；(b) x=真实轮次，y=输入/公共前缀token，role small multiples；(c) x=实测时间，y=Agent，调用区间、工具与排队分别编码 | 两应用分列；角色聚合跨任务；真实案例按无故障应用特征接近中位数选择；附工具/衔接表 | 多轮、增长、实际并行与连续提交。单轮、摘要破坏token前缀或工具长则不能声称目标负载已获得 |
| F2 状态与恢复 | (a) x=自然prefix长度tokens，y=完整KV+元数据GiB；(b) x同，y=resume latency ms，restart/DRAM/+HBM；(c) x=负载，y=健康WCT开销%/复制GiB/s，分别panel | 同prefix同tail配对，实际任务length bins；先每任务聚合timing repeats，再任务CI；微基准range独立标注 | DRAM覆盖收益、容量代价。自然长度短且重建很廉价也保留 |
| F3 Slack价值 | (a) x=故障时Slack ms，y=完整reconstruction ms，点/hexbin、R=s参考线；(b) x=同预算策略，y=paired WCT penalty difference ms | predicted与oracle不混；故障landmark来自预冻结schedule；CI按task+arrival block | cost-only与Slack-aware优先级不同并有实际WCT价值。gap不充当Slack；误判/共故障收益小则缩小claim |
| F4 主结果 | 每应用一行：(a) x=负载fraction，y=绝对F1 mean WCT s；(b) x=policy，y=P_policy−P_restart ms；(c) x=负载，y=F0 WCT cost%或SLO job goodput，分panel | Restart/Fixed/Cost/Aegis-DRAM/Aegis-fixed/Aegis；bootstrap95%CI、任务和arrival-block n；小样本p99单独限制 | 在有限预算下改善故障完成，代价可接受。允许P差为零/正；不以单victim结果替代cohort |
| F5 故障影响 | (a) x=failure-relative wall time s，y=TTFT/TPOT相对F0增量ms，独立panel；(b) x=job cohort，y=paired WCT delta ms或ECDF | direct/indirect/all；actual victim sets另表；部署自然fault与受控victim固定实验分开 | shared retry/bandwidth/queue耦合与不受害job影响。缺少admission timestamp时不能将latency差叫queue delay |
| F6 区域增量 | (a) x=实际HBM bytes，y=held-out required unique-byte coverage%；(b) x=selector或effective bandwidth，y=+HBM−DRAM retry/WCT差ms；(c) x=time，y=layer/transfer/compute lane真实timeline | samephysicalbytes、sameDRAMmanifest；count/recency/random与未来oracle；先每Agent归一、再任务聚合；重复query读去重 | HBM减少暴露等待，而非仅频次集中。有充分带宽、分散需求、复制干扰时HBM可能零/负收益 |
| F7 消融 | x=8个selection/HBM/Adapter配置，y=paired WCT difference ms；第二panel y=F0 cost/occupiedbytes，量纲分开 | 相同预算上限、同arrival/fault；交互项报告，不将8组当8次独立任务 | 三个模块各自作用与交互。HBM-off时Adapter无操作等价组也记录，不编造8个独立贡献 |
| F8 动态容量 | x=实测time s；上panel y=GiB，foreground/safe-ceiling/quota/resident；下panel y=TTFT/TPOT ms或SLO违例率 | fixed-small/fixed-large/adaptive相同burst；quota可暂高于resident、actual+pending不得越physicalcapacity | Adapter利用闲置并保护前台；观察churn和收缩lag，不能只画quota而省略latency |
| F9 预测 | (a) x=remaining prediction absolute/relative error，y=ECDF；(b) x=Slack overestimate ms，y=漏保护或WCT regret；(c) x=active DAG规模，y=控制CPU/壁钟ms | leave-task/source/repository-out；最初/后续calls分别；真剩余≈0的relative denominator规则预设 | causal预测可部署、guard代价；oracle是非部署对照，不用目标总时长当提交时feature |
| F10 边界 | x=λ/Z/K/L/bytes/bandwidth/concurrency，各自small multiples；y=paired WCT差、F0 cost、copylag，独立panel | 自变量一项一项扫；除K/L allocation研究外不同时改bytes与算法；同轴含零线 | 可适用资源区域与失败边界，不画只有有利parameter的截断坐标 |
| F11 权衡 | (a) x=同人口policy/预算，y=H和D ms；(b) x=假设fault概率p，y=(1−p)H−pD，同一objective | task/cohort各自population_id；H、D的同一个bootstrap draw联合传播；p不冒充实测部署频率 | Healthy成本与恢复收益的trade-off。D≤0或break-even不在[0,1]如实显示，不给伪可靠性保证 |

## 与 Background / Motivation 的关系

当前 Agent DAG 是应用设计图；F1 的新执行证据证明实现与所述负载匹配。O1 的示意不能替代 F3；O2 的示意不能替代 F6；O3 的示意不能替代 F8。F2 证明状态/恢复成本，F4承接最终WCT目标。论文写作顺序应让测量先支撑 premise，再展示整体结果与组件分析。

## 分母与特殊情况

前缀复用同时给全部请求和follow-up请求的token分母：potential reused prefix tokens / full input tokens。观测runtime cache hit另列，不以文本前缀匹配冒充physicalhit。每role包含全部Agent，不只挑大历史；各请求prefix占比直接平均与token-weighted结果分开。

覆盖率分母为一个实际恢复窗口中去重的required历史字节，不含重建suffix的新KV；auxiliary metadata单列并纳入实际容量与恢复时间。native logicalselection、kernel tile和physicalKVblock建立映射后计数，不能用逻辑top-k数量推物理bytes。

完成率用所有已提交job；超时、质量失败与物理restore失败分别列。服务时延统计以提交任务为总体，未完成项censor/timeout声明；不在成功样本CDF里隐去失败率。置信区间只能由原始任务/运行块生成，设计图没有误差条。
