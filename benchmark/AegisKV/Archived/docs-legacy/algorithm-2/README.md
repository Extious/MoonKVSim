# SlackLandlord 算法 2

当前版本：**Agent 子租约与尾块收租**（2026-09-08）。Agent 管理生命周期与续租资格，物理 chunk 分摊一份容量租金，连续前缀决定可回收边界。

- [完整设计、三个冲突的修改与公式](AGENT_LEASE_DESIGN.md)
- [可编辑两页流程图](../drawio/slacklandlord-patent-revised/algorithm-2-patent-revised.drawio) · [PDF](../drawio/slacklandlord-patent-revised/algorithm-2-patent-revised.drawio.pdf)
- [CPU 参考实现](agent_lease_slacklandlord.py) · [行为测试](test_agent_lease_slacklandlord.py) · [验证记录](AGENT_LEASE_VALIDATION.json)

当前流程直接计算 P_{a,x}=W_{a,x}/b_x；W_{a,x} 是不重复计价的 Agent 收益份额，G_x 只汇总一次供准入比较。信用来自恢复对 WCT 的贡献；新请求只允许对应 Agent 续租。普通刷新不补信用；内部前缀暂停扣租，成为尾块后用剩余余额继续。每次推进租金前检查全部合法尾块，避免陈旧键漏选。

当前是可执行的元数据模型和设计图，未部署到 Mooncake / MoonKVSim，专利原文未修改。固定顺序分账不对称，严格单块准入保留组合收益盲点，不主张经典 Landlord 竞争比。

历史方案保留用于比较：[仅按当前收益的单块设计](SINGLE_CHUNK_VALUE_DESIGN.md)、[当时的租值键评审](RENT_KEY_REVIEW.md)、[前缀组合方案](PREFIX_BUNDLE_DESIGN.md)、[精确小模型](EXACT_REFERENCE.md)。这些历史文档中的“当前”指其各自版本。
