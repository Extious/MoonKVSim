# 两个业务场景的 Agent 与逐轮请求

状态：应用设计与请求模板已具体化；没有调用模型。示例企业、供应商、产品、报价和访谈均为虚构，仅用于说明请求，不能用作真实实验输入或典型性证据。正式运行须换成真实授权材料并冻结版本。

图只画 Agent 依赖；全部资料在启动前就绪。每个 Agent 的前驱产物只在第一轮输入，内部不等待其他 Agent。下一轮请求携带同一固定 system、所有此前 user 消息和实际 assistant 回复，再追加当前 user 消息。

下面“轮”指一次实际模型请求，不是一次回答中的思维步骤。每个列出的基础步骤都有明确输入或产物；第三方应用并未验证这些具体轮次。是否需要如此分轮仍需质量核验及与合并调用比较。

## 固定 system prompt

```text
你是一个文档型多 Agent 应用中的独立任务 Agent。
只使用本任务已提供的文档、前驱的已完成产物和自己的历史消息。事实引用格式为 [文档ID#段落ID]；无证据的项标记 unknown，不把缺失信息解释为不支持。
区分原文事实、分析推论与待确认项。沿用已有记录 ID，修订时给出变更理由。不要请求另一个 Agent、用户或外部工具补充材料。
每次返回 JSON：{"status":"continue|done|revise|needs_review","artifact":{角色规定的字段},"issues":[],"changes":[]}。中间步骤返回 continue；最后一步检查通过返回 done，有可修复问题返回 revise，输入不足则保留 unknown 或 needs_review，不能编造。
```

每个 Agent 在这段固定 system 后追加下面的角色说明和 artifact 字段，随后保持不变。请求中不启用 tools。

## 请求消息的累计方式

```text
第1轮：[system_a, user_1]
第2轮：[system_a, user_1, actual_assistant_1, user_2]
第3轮：[system_a, user_1, actual_assistant_1, user_2, actual_assistant_2, user_3]
```

完整展开后的 messages 见 [REQUEST_BLUEPRINTS.json](REQUEST_BLUEPRINTS.json)。其中前驱产物和 assistant 回复用明确占位符标记；它们不是模型结果或真实 trace。token 前缀和 KV 命中须在真实后端验证。

## 企业软件采购选型

用户提交：

```text
为一家 300 人的软件公司评估三家企业知识库方案。第一年总费用不超过 12 万元，六周内上线；满足 SSO、权限、审计与导出要求。交付候选比较、选型建议、风险和采购前验证清单。只分析已准备的材料，不进行下单。
```

依赖：`A→D, B→D, B→E, C→E, C→F, D→F, E→G, F→G`。

示例附件：`RFP-REQ`, `RFP-POLICY`, `VENDOR-A`, `VENDOR-B`, `VENDOR-C`；[完整示例输入](example-inputs.json)。

### Agent A：需求分析

直接前驱：无。
固定角色说明：把采购目标变成有来源、可检查的需求矩阵；不评价产品。
最终 artifact：`requirements`, `hard_constraints`, `preferences`, `ambiguities`。

**第1轮：抽取需求**

```text
读取 RFP-REQ。逐项建立 R1、R2…需求记录，列出 requirement、hard_or_preference、acceptance_check、source。保留预算口径、人数和上线期限。此轮仅输出初版需求矩阵，status=continue。
```

此轮附上已准备的文档：`RFP-REQ`。

**第2轮：审查并定稿**

```text
逐项复核上一轮需求矩阵与原文，检查是否漏项、把偏好当硬约束、改变费用口径或虚构优先级。修正后输出完整 requirements、hard_constraints、preferences、ambiguities；无遗漏则 done，有可修复问题则 revise。
```

完成上述步骤后，仅当其最终检查返回可修复 issues 时追加修订请求；不固定填充额外轮次。

### Agent B：产品比较

直接前驱：无。
固定角色说明：按相同维度提取各候选方案；本轮候选依次阅读，最后形成可比较的事实表。
最终 artifact：`vendor_facts`, `comparison_table`, `missing_information`。

**第1轮：读取供应商甲**

```text
读取 VENDOR-A。提取套餐范围、第一年完整报价、上线时间、功能、迁移和明确限制。每条事实保留供应商、字段、value、source，未知项标 unknown。保存甲的记录，continue。
```

此轮附上已准备的文档：`VENDOR-A`。

**第2轮：读取供应商乙**

```text
现在读取 VENDOR-B。用上一轮相同字段建立乙的事实记录，追加到候选集合；不要覆盖甲的记录，也不要开始推荐产品。continue。
```

此轮附上已准备的文档：`VENDOR-B`。

**第3轮：读取供应商丙**

```text
现在读取 VENDOR-C。追加丙的记录，沿用相同字段与来源格式；未说明的离线能力不能标成不支持。continue。
```

此轮附上已准备的文档：`VENDOR-C`。

**第4轮：统一口径并定稿**

```text
对自己的三家供应商记录作交叉核查：费用是否都为第一年完整报价，套餐、上线时间、功能和缺失项是否对齐。输出 vendor_facts、comparison_table、missing_information；保留各候选，不做采购选择。检查通过 done，否则 revise。
```

完成上述步骤后，仅当其最终检查返回可修复 issues 时追加修订请求；不固定填充额外轮次。

### Agent C：安全约束

直接前驱：无。
固定角色说明：依据已提供的企业政策独立检查候选的准入条件；不等待 A 的需求提取。
最终 artifact：`security_requirements`, `vendor_admission`, `evidence_gaps`。

**第1轮：建立准入表**

```text
读取 RFP-POLICY 及三家方案。建立安全准入检查项，逐家记录 SSO、权限、审计保留期、部署区域和导出是否满足，状态只用 pass/fail/unknown，附原文来源。continue。
```

此轮附上已准备的文档：`RFP-POLICY`, `VENDOR-A`, `VENDOR-B`, `VENDOR-C`。

**第2轮：审查条件与缺证**

```text
复核自己的准入表：只声明审计存在是否被误判为达到 180 天；模糊部署承诺是否被误判通过；缺少说明是否被误判失败。定稿 security_requirements、vendor_admission、evidence_gaps，不臆造法律结论。通过 done，否则 revise。
```

完成上述步骤后，仅当其最终检查返回可修复 issues 时追加修订请求；不固定填充额外轮次。

### Agent D：需求匹配

直接前驱：A、B。
固定角色说明：使用 A 的需求矩阵和 B 的产品事实，检查业务适配；安全准入由后续 F 使用 C 处理。
最终 artifact：`requirement_vendor_matrix`, `hard_constraint_gaps`, `tradeoffs`。

第一轮另附原始证据：`RFP-REQ`, `VENDOR-A`, `VENDOR-B`, `VENDOR-C`，便于直接核对而非只信前驱摘要。

**第1轮：逐项匹配**

```text
A、B 的最终产物已提供。对每个 R-id 和每家供应商建立匹配记录，区分满足、不满足、证据不足，引用 A 的需求及 B 的原文事实。单独比较预算与上线硬约束；不把偏好当淘汰项。continue。
```

**第2轮：核验覆盖与定稿**

```text
检查需求×候选矩阵是否完整、引用是否对应、未知项是否被填成确定结论。输出 requirement_vendor_matrix、hard_constraint_gaps、tradeoffs；不要做尚未经过 C 准入检查的最终推荐。通过 done，否则 revise。
```

完成上述步骤后，仅当其最终检查返回可修复 issues 时追加修订请求；不固定填充额外轮次。

### Agent E：风险审查

直接前驱：B、C。
固定角色说明：使用 B 的方案事实和 C 的准入结果，形成有具体后果和采购前验证动作的风险清单。
最终 artifact：`risks`, `blocking_risks`, `verification_actions`。

第一轮另附原始证据：`RFP-POLICY`, `VENDOR-A`, `VENDOR-B`, `VENDOR-C`，便于直接核对而非只信前驱摘要。

**第1轮：列出风险**

```text
B、C 的最终产物已提供。逐家列出安全缺口、报价范围不明、迁移与导出风险，给出证据、影响和可执行的采购前验证动作。区分已违反政策与证据未齐，不虚构概率或损失金额。continue。
```

**第2轮：去重并定稿**

```text
检查风险是否重复或只有笼统的“存在风险”，每条是否有事实依据、影响和验证动作。定稿 risks、blocking_risks、verification_actions。此轮只审查候选方案，不等待 F 的草案。通过 done，否则 revise。
```

完成上述步骤后，仅当其最终检查返回可修复 issues 时追加修订请求；不固定填充额外轮次。

### Agent F：选型草案

直接前驱：C、D。
固定角色说明：使用 C 的准入结论与 D 的需求匹配，形成预选方案；E 的风险审查将在 G 阶段整合。
最终 artifact：`provisional_recommendation`, `candidate_comparison`, `pending_risk_review`。

第一轮另附原始证据：`RFP-REQ`, `RFP-POLICY`, `VENDOR-A`, `VENDOR-B`, `VENDOR-C`，便于直接核对而非只信前驱摘要。

**第1轮：形成预选**

```text
C、D 的最终产物已提供。先用已知硬约束筛选，再解释业务适配与迁移取舍。输出一个预选方案或“现有材料不足以预选”，不要用虚构权重评分。标明这是尚未整合 E 风险清单的草案。continue。
```

**第2轮：反证检查并定稿**

```text
对自己的预选逐项找反例：被忽略的硬约束、unknown、偏好误用、候选优点。修订并定稿 provisional_recommendation、candidate_comparison、pending_risk_review；不请求 E 的结果。通过 done，否则 revise。
```

完成上述步骤后，仅当其最终检查返回可修复 issues 时追加修订请求；不固定填充额外轮次。

### Agent G：决策报告

直接前驱：E、F。
固定角色说明：使用 E 的风险清单与 F 的预选草案，交付完整的采购决策材料；这不是下单或采购审批动作。
最终 artifact：`decision_memo`, `decision_conditions`, `unresolved_items`。

第一轮另附原始证据：`RFP-REQ`, `RFP-POLICY`, `VENDOR-A`, `VENDOR-B`, `VENDOR-C`，便于直接核对而非只信前驱摘要。

**第1轮：整合建议书**

```text
E、F 的最终产物已提供。检查 E 的阻断风险是否推翻 F 的预选，形成建议书：需求摘要、候选比较、建议及理由、采购前验证事项、未知项。所有关键结论附原文来源，必要时改为不建议立即采购。continue。
```

**第2轮：最终验收**

```text
按用户原始任务审查自己的建议书，检查预算、六周上线、SSO/权限/导出/审计、排除理由和未知项是否齐全，风险是否影响最终建议。输出 decision_memo、decision_conditions、unresolved_items；通过 done，否则 revise。
```

完成上述步骤后，仅当其最终检查返回可修复 issues 时追加修订请求；不固定填充额外轮次。

## 新品发布营销方案

用户提交：

```text
为示例企业知识库产品“知页”制作七天新品发布方案。目标客群为研发与运营负责人；交付官网、邮件、公众号三份文案和 Day-3 至 Day+3 排期，统一 CTA 为“预约产品演示”。只使用现成产品、访谈与品牌材料，不执行在线发布。
```

依赖：`H→K, I→K, I→L, J→L, J→M, K→M, K→N, L→N, M→O, N→O`。

示例附件：`CAMPAIGN-BRIEF`, `PRODUCT-FACTS`, `AUDIENCE-OPS`, `AUDIENCE-ENG`, `BRAND-RULES`, `CHANNEL-RULES`；[完整示例输入](example-inputs.json)。

### Agent H：产品卖点

直接前驱：无。
固定角色说明：把产品事实变成有依据的卖点边界，不能用虚构效果包装功能。
最终 artifact：`verified_facts`, `supported_benefits`, `unsupported_claims`。

**第1轮：抽取产品事实**

```text
读取 PRODUCT-FACTS。逐项提取 feature、source、可演示的使用方式，给事实分配 F1、F2…ID。区分产品已支持的能力与没有验证的效果。continue。
```

此轮附上已准备的文档：`PRODUCT-FACTS`。

**第2轮：检查卖点边界**

```text
检查自己的事实表与利益表述，每个 supported_benefit 要说明其由哪个功能支持，不能把场景价值写成已测量提升。定稿 verified_facts、supported_benefits、unsupported_claims。通过 done，否则 revise。
```

完成上述步骤后，仅当其最终检查返回可修复 issues 时追加修订请求；不固定填充额外轮次。

### Agent I：客群分析

直接前驱：无。
固定角色说明：基于现成访谈分析客群，不把少量访谈扩大成市场比例或转化率。
最终 artifact：`audience_profiles`, `pain_points`, `decision_questions`, `evidence_limits`。

**第1轮：分析运营客群**

```text
读取 AUDIENCE-OPS。提取运营负责人的痛点、使用情境、关注点和愿意采取的下一步，逐条附访谈位置；没有提到的预算、采购意向不要补。continue。
```

此轮附上已准备的文档：`AUDIENCE-OPS`。

**第2轮：分析研发客群**

```text
读取 AUDIENCE-ENG。建立研发负责人的同类记录，保留已有运营记录；指出两个客群的问题有何不同，不套用同一画像。continue。
```

此轮附上已准备的文档：`AUDIENCE-ENG`。

**第3轮：对照并定稿**

```text
交叉核查两组记录，输出 audience_profiles、pain_points、decision_questions、evidence_limits。删除“多数人”“预计转化率”等无法从访谈支持的概括，保留可引用的差异。通过 done，否则 revise。
```

完成上述步骤后，仅当其最终检查返回可修复 issues 时追加修订请求；不固定填充额外轮次。

### Agent J：品牌规范

直接前驱：无。
固定角色说明：整理品牌和渠道发布约束，形成后续策略和文案可直接使用的检查表。
最终 artifact：`voice_rules`, `claim_rules`, `channel_constraints`。

**第1轮：整理品牌与声明规则**

```text
读取 BRAND-RULES。提取语气、禁止用语、事实证明要求和不能承诺的效果，给检查项分配 B1、B2…ID。continue。
```

此轮附上已准备的文档：`BRAND-RULES`。

**第2轮：补齐渠道规则并定稿**

```text
读取 CHANNEL-RULES，合并已有品牌记录。输出 voice_rules、claim_rules、channel_constraints，明确三个固定资产 ID、字符长度限制与统一 CTA。检查规则有无冲突；通过 done，否则 revise。
```

此轮附上已准备的文档：`CHANNEL-RULES`。

完成上述步骤后，仅当其最终检查返回可修复 issues 时追加修订请求；不固定填充额外轮次。

### Agent K：传播主题

直接前驱：H、I。
固定角色说明：使用 H 的事实和 I 的客群画像，将产品能力映射到各客群的问题，提供文案与活动共用的主题。
最终 artifact：`message_map`, `audience_variants`, `fact_references`。

第一轮另附原始证据：`PRODUCT-FACTS`, `AUDIENCE-OPS`, `AUDIENCE-ENG`，便于直接核对而非只信前驱摘要。

**第1轮：构建主题**

```text
H、I 的最终产物已提供。建立“客群痛点→可支持的产品事实→传播主张→演示内容”映射，给主张分配 M1、M2…ID，并为运营、研发各写一个主张方向。不要编造新的功能或效果。continue。
```

**第2轮：审查主张并定稿**

```text
检查自己的每个主张是否既有客群依据又有产品依据，是否跨越了事实边界。定稿 message_map、audience_variants、fact_references。输出主题而非完整活动排期，不等待 J 或 L。通过 done，否则 revise。
```

完成上述步骤后，仅当其最终检查返回可修复 issues 时追加修订请求；不固定填充额外轮次。

### Agent L：渠道策略

直接前驱：I、J。
固定角色说明：使用 I 的客群资料与 J 的规范，为已规定的三个渠道确定用途与触达方式；不改渠道集合。
最终 artifact：`channel_roles`, `audience_channel_map`, `touch_limits`。

第一轮另附原始证据：`AUDIENCE-OPS`, `AUDIENCE-ENG`, `BRAND-RULES`, `CHANNEL-RULES`，便于直接核对而非只信前驱摘要。

**第1轮：分配渠道用途**

```text
I、J 的最终产物已提供。为官网 WEB-1、邮件 EMAIL-1、公众号 SOCIAL-1 定义用途、面向客群和触达方式，遵守品牌与渠道规则；不得创建新渠道或给出未经测量的转化率。continue。
```

**第2轮：检查覆盖并定稿**

```text
检查两个客群和三个资产是否均有合理安排、规则是否冲突。定稿 channel_roles、audience_channel_map、touch_limits；不依赖 K 的具体传播主题，主题由 N 后续整合。通过 done，否则 revise。
```

完成上述步骤后，仅当其最终检查返回可修复 issues 时追加修订请求；不固定填充额外轮次。

### Agent M：渠道文案

直接前驱：K、J。
固定角色说明：使用 K 的主题与 J 的规范连续产出三个固定渠道的文案，保持自己的已写内容用于一致性检查。
最终 artifact：`assets`, `asset_fact_references`, `content_checks`。

第一轮另附原始证据：`PRODUCT-FACTS`, `BRAND-RULES`, `CHANNEL-RULES`，便于直接核对而非只信前驱摘要。

**第1轮：官网文案**

```text
K、J 的最终产物已提供。按主题生成 WEB-1：标题、正文、CTA；遵守官网长度与品牌规则，附每项功能表述的事实来源。此轮只完成官网初稿，continue。
```

**第2轮：邮件文案**

```text
基于同一传播主题和自己已写的官网文案，生成 EMAIL-1：主题、正文、CTA。适配邮件用途，保留 WEB-1，不虚构促销、价格或效率数字。continue。
```

**第3轮：公众号文案**

```text
基于同一主题生成 SOCIAL-1：标题、正文、CTA。适配公众号阅读方式，保留 WEB-1 与 EMAIL-1，避免三个渠道成为逐字重复的文本。continue。
```

**第4轮：跨渠道核查并定稿**

```text
逐一审查自己的三个资产：事实和 CTA 是否一致，是否使用禁用承诺，是否符合各渠道长度要求，是否覆盖客群关切。定稿 assets、asset_fact_references、content_checks。未知的效果不补；通过 done，否则 revise。不要等待 N 的排期。
```

完成上述步骤后，仅当其最终检查返回可修复 issues 时追加修订请求；不固定填充额外轮次。

### Agent N：活动排期

直接前驱：K、L。
固定角色说明：使用 K 的主题和 L 的渠道策略规划七天活动，只引用预先规定的资产 ID，不需要 M 的文案成稿。
最终 artifact：`calendar`, `asset_requirements`, `measurement_plan`。

第一轮另附原始证据：`CHANNEL-RULES`，便于直接核对而非只信前驱摘要。

**第1轮：制定排期**

```text
K、L 的最终产物已提供。为 Day-3 到 Day+3 建立活动表：day、channel、asset_id、audience、message_id、purpose。只能引用 WEB-1/EMAIL-1/SOCIAL-1，每渠道每天最多一次。指标只写需要测量什么，不预测数字。continue。
```

**第2轮：审查资源与定稿**

```text
检查七天覆盖、每渠道触达上限、两个客群、主题与渠道用途、资产 ID 是否一致。定稿 calendar、asset_requirements、measurement_plan。M 的资产正文不作为输入，不等待 M。通过 done，否则 revise。
```

完成上述步骤后，仅当其最终检查返回可修复 issues 时追加修订请求；不固定填充额外轮次。

### Agent O：交付编辑

直接前驱：M、N。
固定角色说明：使用 M 的文案与 N 的排期，把两条并行产出整合成用户可检查的发布包；不执行发布或发送。
最终 artifact：`campaign_package`, `final_checks`, `open_issues`。

第一轮另附原始证据：`PRODUCT-FACTS`, `AUDIENCE-OPS`, `AUDIENCE-ENG`, `BRAND-RULES`, `CHANNEL-RULES`，便于直接核对而非只信前驱摘要。

**第1轮：整合发布包**

```text
M、N 的最终产物已提供。把每个排期条目与实际资产绑定，检查目标客群、主题、CTA 与长度规则；必要时在本 Agent 内修改文案或排期。输出一个七天发布包初稿，保持三个资产的 ID 与证据链。continue。
```

**第2轮：最终验收**

```text
检查自己的发布包是否包含七天排期、三个完整渠道资产、统一 CTA、可追溯的功能事实及待确认项。删除无依据的效果或指标承诺。定稿 campaign_package、final_checks、open_issues；通过 done，否则 revise。长度由应用本地计数另行核验，不把本轮自评当作唯一质量判定。
```

完成上述步骤后，仅当其最终检查返回可修复 issues 时追加修订请求；不固定填充额外轮次。

## 所有 Agent 的条件修订请求

```text
这是本 Agent 的追加修订轮。针对上一轮 issues，逐项回到已收到的原文和自己的历史结果修正，不改变输入事实或评估标准。输出完整 artifact、逐项 changes 和未解决 issues。全部角色检查通过则 status=done；仍有可修复问题则 revise；证据缺失无法解决则 needs_review。不要重新询问其他 Agent 或等待新材料。
```

原 Agent 保留完整历史继续执行，最多追加两次修订；上限是防止失控，未解决时记录 needs_review 和问题，不伪装成功。正常任务计时包含检查、修订和队列。

## 连续与并行的边界

采购：A/B/C 可并行；D 只等 A/B，E 只等 B/C；F 只等 C/D，G 等 E/F。营销：H/I/J 可并行；K 等 H/I，L 等 I/J；M 等 J/K，N 等 K/L，O 等 M/N。M 与 N 没有相互等待；N 使用预先规定的资产 ID，不需要 M 的文案内容，O 完成最终绑定。

供应商数量、客群文件数量和问题驱动的修订会改变实际调用次数。没有固定每个 Agent 均三轮，也没有人为延时、随机填充或外部 Agent 逐轮反馈。图允许并行；实际服务重叠、工具占比、完整 prompt token 历史和缓存驻留仍需重新采集。

本地检查器只验证 JSON、来源引用和文案字符数，不是额外 LLM Agent；失败反馈追加到本 Agent 内部修订轮。若需要人工确认，当前任务以 needs_review 结束，不停在任务中等待人回复。

