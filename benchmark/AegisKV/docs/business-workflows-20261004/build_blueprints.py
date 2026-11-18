#!/usr/bin/env python3
"""Materialize application specs and request blueprints without invoking an LLM.

Example inputs are explicitly fictional. Assistant messages and predecessor
artifacts in the previews are placeholders, not model outputs or traces.
"""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parent
COMMON_SYSTEM = '''你是一个文档型多 Agent 应用中的独立任务 Agent。
只使用本任务已提供的文档、前驱的已完成产物和自己的历史消息。事实引用格式为 [文档ID#段落ID]；无证据的项标记 unknown，不把缺失信息解释为不支持。
区分原文事实、分析推论与待确认项。沿用已有记录 ID，修订时给出变更理由。不要请求另一个 Agent、用户或外部工具补充材料。
每次返回 JSON：{"status":"continue|done|revise|needs_review","artifact":{角色规定的字段},"issues":[],"changes":[]}。中间步骤返回 continue；最后一步检查通过返回 done，有可修复问题返回 revise，输入不足则保留 unknown 或 needs_review，不能编造。
'''
REPAIR = '''这是本 Agent 的追加修订轮。针对上一轮 issues，逐项回到已收到的原文和自己的历史结果修正，不改变输入事实或评估标准。输出完整 artifact、逐项 changes 和未解决 issues。全部角色检查通过则 status=done；仍有可修复问题则 revise；证据缺失无法解决则 needs_review。不要重新询问其他 Agent 或等待新材料。'''

DOCS = {
 'RFP-REQ': '''# 演示需求（虚构）
 [p1] 一家 300 人的软件公司要采购企业知识库，用户任务是比较供应商甲、乙、丙，提交建议书与待确认项。第一年含订阅、实施的总费用上限为 120000 元；六周内上线。
 [p2] 必须支持企业 SSO、部门级权限、全文检索和完整文档导出；移动访问和离线访问属于偏好，不是淘汰条件。
 [p3] 安全基线另见 RFP-POLICY。评估时先检查硬约束，再比较需求适配、迁移负担和使用便利性。不允许虚构评分权重。''',
 'RFP-POLICY': '''# 演示企业安全基线（虚构公司政策，不是法律意见）
 [p1] 必须支持企业 SSO、部门隔离权限和至少 180 天的审计日志保留。
 [p2] 数据须保存在企业批准的境内云区域，不能只用模糊的“全球云”表述。必须提供全量文档导出机制。
 [p3] 供应商仅声明某能力存在，但没有明确套餐、范围或保留周期时，结论应为 unknown，列入采购前验证事项。''',
 'VENDOR-A': '''# 供应商甲方案（演示用虚构数据）
 [p1] 300 人套餐的第一年完整报价为 110000 元，包含迁移实施；计划四周上线。支持全文检索、企业 SSO、部门权限及批量导出。
 [p2] 支持移动网页，不支持离线访问。迁移支持导入 Markdown 和附件，复杂链接需要人工检查。
 [p3] 审计日志保留 90 天；没有更长保留期的承诺。提供境内云部署。''',
 'VENDOR-B': '''# 供应商乙方案（演示用虚构数据）
 [p1] 300 人企业套餐的第一年完整报价为 125000 元，包含 SSO 和迁移服务；计划五周上线。支持部门权限、全文检索、全量导出。
 [p2] 支持移动应用和离线阅读。已有知识库迁移包含链接自动检查。
 [p3] 企业套餐审计日志保留 365 天，数据保存于企业批准的境内云区域。''',
 'VENDOR-C': '''# 供应商丙方案（演示用虚构数据）
 [p1] 300 人套餐的第一年完整报价为 118000 元，包含迁移实施；计划五周上线。提供企业 SSO、部门权限、全文检索和全量导出。
 [p2] 支持移动网页；离线能力未说明。迁移只承诺通用文档导入，对历史附件和复杂链接需做验收。
 [p3] 审计日志保留 180 天。数据保存于企业批准的境内云区域。''',
 'CAMPAIGN-BRIEF': '''# 新品发布任务（示例产品与任务均为虚构）
 [p1] 产品“知页”是面向 20–200 人团队的企业知识库。目标用户是研发团队负责人和运营团队负责人。产出一个七天发布方案及官网、邮件、公众号文案，目标 CTA 为“预约产品演示”。
 [p2] 必须交付三个固定资产：WEB-1 官网首屏文案、EMAIL-1 发布邮件、SOCIAL-1 公众号短文。排期只能安排这些已规定渠道与资产，不创建新渠道或在线发布。
 [p3] 时间用 Day-3 至 Day+3 表示，Day0 为发布日。每个渠道每天至多一次触达。客户研究、产品说明和品牌规范在 workflow 提交前全部可用。''',
 'PRODUCT-FACTS': '''# 知页产品资料（演示用虚构资料）
 [p1] 支持跨文档全文检索，并把结果链接到来源段落。
 [p2] 支持部门权限、企业 SSO、Markdown 导入与批量导出。
 [p3] 尚无经过验证的效率提升百分比、客户数量或竞品对照实验；不能宣称“提高效率 70%”“零错误”或“行业第一”。''',
 'AUDIENCE-OPS': '''# 运营访谈摘录（演示用虚构访谈）
 [p1] 一位运营负责人说：新人反复问流程，资料分散在多个群和文件夹，最希望找到可信的最新版。
 [p2] 另一位运营负责人说：交接时常缺少原文出处，愿意先看具体使用示例再申请演示。
 [p3] 以上两条访谈不是有代表性的比例统计，不能写成“多数运营团队”或推导转化率。''',
 'AUDIENCE-ENG': '''# 研发访谈摘录（演示用虚构访谈）
 [p1] 一位研发负责人说：决策记录散落在多个项目，需要查到背景与来源；关心是否能接入已有 SSO。
 [p2] 另一位研发负责人说：先关注权限、迁移和导出，希望演示真实的检索与定位过程。
 [p3] 访谈没有给出预算、采购意向比例或效果预测，不能据此制造营销指标。''',
 'BRAND-RULES': '''# 品牌规则（演示用虚构内部规范）
 [p1] 语气清楚、具体、克制；不使用“最好”“绝对安全”“100%正确”“零幻觉”等绝对或未经证实的承诺。
 [p2] 功能陈述必须由 PRODUCT-FACTS 支持；可表达用户场景与可验证的使用方式，不把合理预期写成已测量的效果。
 [p3] 可设定需要后续测量的活动指标名称，但不能凭空给出预期 CTR、客户数量或 ROI。''',
 'CHANNEL-RULES': '''# 渠道约束（演示用虚构内部规范）
 [p1] WEB-1：主标题不超过 24 个汉字；正文不超过 180 个汉字；CTA 使用“预约产品演示”。
 [p2] EMAIL-1：主题不超过 24 个汉字；正文不超过 300 个汉字；CTA 同上。
 [p3] SOCIAL-1：标题不超过 24 个汉字；正文不超过 400 个汉字；CTA 同上。长度为发布前本地可核验的要求，不用 LLM 自评替代最终计数。''',
}


def round_(title, prompt, docs=()):
    return {'title': title, 'prompt': prompt, 'documents_appended': list(docs)}


def agent(name, role, preds, fields, rounds):
    return {'name': name, 'role_instruction': role, 'predecessors': list(preds),
            'artifact_fields': list(fields), 'base_rounds': rounds,
            'conditional_repair_prompt': REPAIR, 'max_additional_repairs': 2}


AGENTS = {
 'A': agent('需求分析', '把采购目标变成有来源、可检查的需求矩阵；不评价产品。', (),
   ['requirements', 'hard_constraints', 'preferences', 'ambiguities'], [
   round_('抽取需求', '读取 RFP-REQ。逐项建立 R1、R2…需求记录，列出 requirement、hard_or_preference、acceptance_check、source。保留预算口径、人数和上线期限。此轮仅输出初版需求矩阵，status=continue。', ['RFP-REQ']),
   round_('审查并定稿', '逐项复核上一轮需求矩阵与原文，检查是否漏项、把偏好当硬约束、改变费用口径或虚构优先级。修正后输出完整 requirements、hard_constraints、preferences、ambiguities；无遗漏则 done，有可修复问题则 revise。'),
 ]),
 'B': agent('产品比较', '按相同维度提取各候选方案；本轮候选依次阅读，最后形成可比较的事实表。', (),
   ['vendor_facts', 'comparison_table', 'missing_information'], [
   round_('读取供应商甲', '读取 VENDOR-A。提取套餐范围、第一年完整报价、上线时间、功能、迁移和明确限制。每条事实保留供应商、字段、value、source，未知项标 unknown。保存甲的记录，continue。', ['VENDOR-A']),
   round_('读取供应商乙', '现在读取 VENDOR-B。用上一轮相同字段建立乙的事实记录，追加到候选集合；不要覆盖甲的记录，也不要开始推荐产品。continue。', ['VENDOR-B']),
   round_('读取供应商丙', '现在读取 VENDOR-C。追加丙的记录，沿用相同字段与来源格式；未说明的离线能力不能标成不支持。continue。', ['VENDOR-C']),
   round_('统一口径并定稿', '对自己的三家供应商记录作交叉核查：费用是否都为第一年完整报价，套餐、上线时间、功能和缺失项是否对齐。输出 vendor_facts、comparison_table、missing_information；保留各候选，不做采购选择。检查通过 done，否则 revise。'),
 ]),
 'C': agent('安全约束', '依据已提供的企业政策独立检查候选的准入条件；不等待 A 的需求提取。', (),
   ['security_requirements', 'vendor_admission', 'evidence_gaps'], [
   round_('建立准入表', '读取 RFP-POLICY 及三家方案。建立安全准入检查项，逐家记录 SSO、权限、审计保留期、部署区域和导出是否满足，状态只用 pass/fail/unknown，附原文来源。continue。', ['RFP-POLICY', 'VENDOR-A', 'VENDOR-B', 'VENDOR-C']),
   round_('审查条件与缺证', '复核自己的准入表：只声明审计存在是否被误判为达到 180 天；模糊部署承诺是否被误判通过；缺少说明是否被误判失败。定稿 security_requirements、vendor_admission、evidence_gaps，不臆造法律结论。通过 done，否则 revise。'),
 ]),
 'D': agent('需求匹配', '使用 A 的需求矩阵和 B 的产品事实，检查业务适配；安全准入由后续 F 使用 C 处理。', ('A', 'B'),
   ['requirement_vendor_matrix', 'hard_constraint_gaps', 'tradeoffs'], [
   round_('逐项匹配', 'A、B 的最终产物已提供。对每个 R-id 和每家供应商建立匹配记录，区分满足、不满足、证据不足，引用 A 的需求及 B 的原文事实。单独比较预算与上线硬约束；不把偏好当淘汰项。continue。'),
   round_('核验覆盖与定稿', '检查需求×候选矩阵是否完整、引用是否对应、未知项是否被填成确定结论。输出 requirement_vendor_matrix、hard_constraint_gaps、tradeoffs；不要做尚未经过 C 准入检查的最终推荐。通过 done，否则 revise。'),
 ]),
 'E': agent('风险审查', '使用 B 的方案事实和 C 的准入结果，形成有具体后果和采购前验证动作的风险清单。', ('B', 'C'),
   ['risks', 'blocking_risks', 'verification_actions'], [
   round_('列出风险', 'B、C 的最终产物已提供。逐家列出安全缺口、报价范围不明、迁移与导出风险，给出证据、影响和可执行的采购前验证动作。区分已违反政策与证据未齐，不虚构概率或损失金额。continue。'),
   round_('去重并定稿', '检查风险是否重复或只有笼统的“存在风险”，每条是否有事实依据、影响和验证动作。定稿 risks、blocking_risks、verification_actions。此轮只审查候选方案，不等待 F 的草案。通过 done，否则 revise。'),
 ]),
 'F': agent('选型草案', '使用 C 的准入结论与 D 的需求匹配，形成预选方案；E 的风险审查将在 G 阶段整合。', ('C', 'D'),
   ['provisional_recommendation', 'candidate_comparison', 'pending_risk_review'], [
   round_('形成预选', 'C、D 的最终产物已提供。先用已知硬约束筛选，再解释业务适配与迁移取舍。输出一个预选方案或“现有材料不足以预选”，不要用虚构权重评分。标明这是尚未整合 E 风险清单的草案。continue。'),
   round_('反证检查并定稿', '对自己的预选逐项找反例：被忽略的硬约束、unknown、偏好误用、候选优点。修订并定稿 provisional_recommendation、candidate_comparison、pending_risk_review；不请求 E 的结果。通过 done，否则 revise。'),
 ]),
 'G': agent('决策报告', '使用 E 的风险清单与 F 的预选草案，交付完整的采购决策材料；这不是下单或采购审批动作。', ('E', 'F'),
   ['decision_memo', 'decision_conditions', 'unresolved_items'], [
   round_('整合建议书', 'E、F 的最终产物已提供。检查 E 的阻断风险是否推翻 F 的预选，形成建议书：需求摘要、候选比较、建议及理由、采购前验证事项、未知项。所有关键结论附原文来源，必要时改为不建议立即采购。continue。'),
   round_('最终验收', '按用户原始任务审查自己的建议书，检查预算、六周上线、SSO/权限/导出/审计、排除理由和未知项是否齐全，风险是否影响最终建议。输出 decision_memo、decision_conditions、unresolved_items；通过 done，否则 revise。'),
 ]),
 'H': agent('产品卖点', '把产品事实变成有依据的卖点边界，不能用虚构效果包装功能。', (),
   ['verified_facts', 'supported_benefits', 'unsupported_claims'], [
   round_('抽取产品事实', '读取 PRODUCT-FACTS。逐项提取 feature、source、可演示的使用方式，给事实分配 F1、F2…ID。区分产品已支持的能力与没有验证的效果。continue。', ['PRODUCT-FACTS']),
   round_('检查卖点边界', '检查自己的事实表与利益表述，每个 supported_benefit 要说明其由哪个功能支持，不能把场景价值写成已测量提升。定稿 verified_facts、supported_benefits、unsupported_claims。通过 done，否则 revise。'),
 ]),
 'I': agent('客群分析', '基于现成访谈分析客群，不把少量访谈扩大成市场比例或转化率。', (),
   ['audience_profiles', 'pain_points', 'decision_questions', 'evidence_limits'], [
   round_('分析运营客群', '读取 AUDIENCE-OPS。提取运营负责人的痛点、使用情境、关注点和愿意采取的下一步，逐条附访谈位置；没有提到的预算、采购意向不要补。continue。', ['AUDIENCE-OPS']),
   round_('分析研发客群', '读取 AUDIENCE-ENG。建立研发负责人的同类记录，保留已有运营记录；指出两个客群的问题有何不同，不套用同一画像。continue。', ['AUDIENCE-ENG']),
   round_('对照并定稿', '交叉核查两组记录，输出 audience_profiles、pain_points、decision_questions、evidence_limits。删除“多数人”“预计转化率”等无法从访谈支持的概括，保留可引用的差异。通过 done，否则 revise。'),
 ]),
 'J': agent('品牌规范', '整理品牌和渠道发布约束，形成后续策略和文案可直接使用的检查表。', (),
   ['voice_rules', 'claim_rules', 'channel_constraints'], [
   round_('整理品牌与声明规则', '读取 BRAND-RULES。提取语气、禁止用语、事实证明要求和不能承诺的效果，给检查项分配 B1、B2…ID。continue。', ['BRAND-RULES']),
   round_('补齐渠道规则并定稿', '读取 CHANNEL-RULES，合并已有品牌记录。输出 voice_rules、claim_rules、channel_constraints，明确三个固定资产 ID、字符长度限制与统一 CTA。检查规则有无冲突；通过 done，否则 revise。', ['CHANNEL-RULES']),
 ]),
 'K': agent('传播主题', '使用 H 的事实和 I 的客群画像，将产品能力映射到各客群的问题，提供文案与活动共用的主题。', ('H', 'I'),
   ['message_map', 'audience_variants', 'fact_references'], [
   round_('构建主题', 'H、I 的最终产物已提供。建立“客群痛点→可支持的产品事实→传播主张→演示内容”映射，给主张分配 M1、M2…ID，并为运营、研发各写一个主张方向。不要编造新的功能或效果。continue。'),
   round_('审查主张并定稿', '检查自己的每个主张是否既有客群依据又有产品依据，是否跨越了事实边界。定稿 message_map、audience_variants、fact_references。输出主题而非完整活动排期，不等待 J 或 L。通过 done，否则 revise。'),
 ]),
 'L': agent('渠道策略', '使用 I 的客群资料与 J 的规范，为已规定的三个渠道确定用途与触达方式；不改渠道集合。', ('I', 'J'),
   ['channel_roles', 'audience_channel_map', 'touch_limits'], [
   round_('分配渠道用途', 'I、J 的最终产物已提供。为官网 WEB-1、邮件 EMAIL-1、公众号 SOCIAL-1 定义用途、面向客群和触达方式，遵守品牌与渠道规则；不得创建新渠道或给出未经测量的转化率。continue。'),
   round_('检查覆盖并定稿', '检查两个客群和三个资产是否均有合理安排、规则是否冲突。定稿 channel_roles、audience_channel_map、touch_limits；不依赖 K 的具体传播主题，主题由 N 后续整合。通过 done，否则 revise。'),
 ]),
 'M': agent('渠道文案', '使用 K 的主题与 J 的规范连续产出三个固定渠道的文案，保持自己的已写内容用于一致性检查。', ('K', 'J'),
   ['assets', 'asset_fact_references', 'content_checks'], [
   round_('官网文案', 'K、J 的最终产物已提供。按主题生成 WEB-1：标题、正文、CTA；遵守官网长度与品牌规则，附每项功能表述的事实来源。此轮只完成官网初稿，continue。'),
   round_('邮件文案', '基于同一传播主题和自己已写的官网文案，生成 EMAIL-1：主题、正文、CTA。适配邮件用途，保留 WEB-1，不虚构促销、价格或效率数字。continue。'),
   round_('公众号文案', '基于同一主题生成 SOCIAL-1：标题、正文、CTA。适配公众号阅读方式，保留 WEB-1 与 EMAIL-1，避免三个渠道成为逐字重复的文本。continue。'),
   round_('跨渠道核查并定稿', '逐一审查自己的三个资产：事实和 CTA 是否一致，是否使用禁用承诺，是否符合各渠道长度要求，是否覆盖客群关切。定稿 assets、asset_fact_references、content_checks。未知的效果不补；通过 done，否则 revise。不要等待 N 的排期。'),
 ]),
 'N': agent('活动排期', '使用 K 的主题和 L 的渠道策略规划七天活动，只引用预先规定的资产 ID，不需要 M 的文案成稿。', ('K', 'L'),
   ['calendar', 'asset_requirements', 'measurement_plan'], [
   round_('制定排期', 'K、L 的最终产物已提供。为 Day-3 到 Day+3 建立活动表：day、channel、asset_id、audience、message_id、purpose。只能引用 WEB-1/EMAIL-1/SOCIAL-1，每渠道每天最多一次。指标只写需要测量什么，不预测数字。continue。'),
   round_('审查资源与定稿', '检查七天覆盖、每渠道触达上限、两个客群、主题与渠道用途、资产 ID 是否一致。定稿 calendar、asset_requirements、measurement_plan。M 的资产正文不作为输入，不等待 M。通过 done，否则 revise。'),
 ]),
 'O': agent('交付编辑', '使用 M 的文案与 N 的排期，把两条并行产出整合成用户可检查的发布包；不执行发布或发送。', ('M', 'N'),
   ['campaign_package', 'final_checks', 'open_issues'], [
   round_('整合发布包', 'M、N 的最终产物已提供。把每个排期条目与实际资产绑定，检查目标客群、主题、CTA 与长度规则；必要时在本 Agent 内修改文案或排期。输出一个七天发布包初稿，保持三个资产的 ID 与证据链。continue。'),
   round_('最终验收', '检查自己的发布包是否包含七天排期、三个完整渠道资产、统一 CTA、可追溯的功能事实及待确认项。删除无依据的效果或指标承诺。定稿 campaign_package、final_checks、open_issues；通过 done，否则 revise。长度由应用本地计数另行核验，不把本轮自评当作唯一质量判定。'),
 ]),
}

WORKFLOWS = {
 'procurement': {
   'title': '企业软件采购选型', 'agent_ids': list('ABCDEFG'), 'final_agent': 'G',
   'user_task': '为一家 300 人的软件公司评估三家企业知识库方案。第一年总费用不超过 12 万元，六周内上线；满足 SSO、权限、审计与导出要求。交付候选比较、选型建议、风险和采购前验证清单。只分析已准备的材料，不进行下单。',
   'documents': ['RFP-REQ', 'RFP-POLICY', 'VENDOR-A', 'VENDOR-B', 'VENDOR-C'],
   'edges': [('A','D'),('B','D'),('B','E'),('C','E'),('C','F'),('D','F'),('E','G'),('F','G')],
 },
 'campaign': {
   'title': '新品发布营销方案', 'agent_ids': list('HIJKLMNO'), 'final_agent': 'O',
   'user_task': '为示例企业知识库产品“知页”制作七天新品发布方案。目标客群为研发与运营负责人；交付官网、邮件、公众号三份文案和 Day-3 至 Day+3 排期，统一 CTA 为“预约产品演示”。只使用现成产品、访谈与品牌材料，不执行在线发布。',
   'documents': ['CAMPAIGN-BRIEF', 'PRODUCT-FACTS', 'AUDIENCE-OPS', 'AUDIENCE-ENG', 'BRAND-RULES', 'CHANNEL-RULES'],
   'edges': [('H','K'),('I','K'),('I','L'),('J','L'),('J','M'),('K','M'),('K','N'),('L','N'),('M','O'),('N','O')],
 },
}

# Downstream verification needs the original evidence as well as upstream
# summaries. These frozen local documents arrive with the first call, never
# as mid-task communication from another Agent.
INITIAL_EVIDENCE = {
 'D': ['RFP-REQ', 'VENDOR-A', 'VENDOR-B', 'VENDOR-C'],
 'E': ['RFP-POLICY', 'VENDOR-A', 'VENDOR-B', 'VENDOR-C'],
 'F': ['RFP-REQ', 'RFP-POLICY', 'VENDOR-A', 'VENDOR-B', 'VENDOR-C'],
 'G': ['RFP-REQ', 'RFP-POLICY', 'VENDOR-A', 'VENDOR-B', 'VENDOR-C'],
 'K': ['PRODUCT-FACTS', 'AUDIENCE-OPS', 'AUDIENCE-ENG'],
 'L': ['AUDIENCE-OPS', 'AUDIENCE-ENG', 'BRAND-RULES', 'CHANNEL-RULES'],
 'M': ['PRODUCT-FACTS', 'BRAND-RULES', 'CHANNEL-RULES'],
 'N': ['CHANNEL-RULES'],
 'O': ['PRODUCT-FACTS', 'AUDIENCE-OPS', 'AUDIENCE-ENG', 'BRAND-RULES', 'CHANNEL-RULES'],
}


def materialize():
    spec = {
       'status': 'proposed_applications_and_request_templates_not_executed',
       'example_input_provenance': 'fictional_demo_only_not_a_benchmark_or_production_trace',
       'common_system_prompt': COMMON_SYSTEM,
       'history_policy': 'fixed system; append user and actual assistant messages without editing or trimming prior messages',
       'execution_policy': 'register task DAG before start; preload all documents; admit each Agent after all own predecessors terminate; one outstanding call per Agent; next call immediately after local result handling',
       'tools_in_main_variant': [], 'local_checks': ['JSON schema', 'source references', 'character counts for final marketing assets'],
       'stopping': 'mandatory role-specific base steps; optional repairs driven by explicit issues; needs_review after unresolved input gaps or repair cap',
       'counts': 'base step counts are protocol definitions for this example, not measured invocation counts; supplier count and repairs can vary',
       'workflows': WORKFLOWS, 'agents': AGENTS,
       'original_evidence_in_first_call': INITIAL_EVIDENCE,
    }
    (ROOT/'application-spec.json').write_text(json.dumps(spec,ensure_ascii=False,indent=2)+'\n')
    (ROOT/'example-inputs.json').write_text(json.dumps({'provenance':'fictional_demonstration','documents':DOCS},ensure_ascii=False,indent=2)+'\n')
    previews = []
    for wf_id, wf in WORKFLOWS.items():
        for aid in wf['agent_ids']:
            a = AGENTS[aid]
            system = COMMON_SYSTEM + '\n你的角色：' + a['name'] + '。' + a['role_instruction'] + '\n最终 artifact 字段：' + ', '.join(a['artifact_fields'])
            messages = [{'role':'system','content':system}]
            rounds = []
            for index, step in enumerate(a['base_rounds'],1):
                if index == 1:
                    prefix = '用户原始任务：'+wf['user_task']+'\n本 Agent 已登记的直接前驱：'+(', '.join(a['predecessors']) or '无')+'\n'
                    prefix += '输入材料清单（全部已在本地备齐）：'+', '.join(wf['documents'])+'\n'
                    if wf_id=='campaign':
                        prefix += DOCS['CAMPAIGN-BRIEF']+'\n'
                    prefix += '\n'.join(f'前驱 {p} 的不可变最终产物：<<{p}.final 实际 artifact；占位符>>' for p in a['predecessors'])+'\n'
                    if aid in INITIAL_EVIDENCE:
                        prefix += '本 Agent 从第一轮即可使用的原始证据（不是前驱摘要的替代品）：\n'
                        prefix += '\n\n'.join(DOCS[d] for d in INITIAL_EVIDENCE[aid])+'\n'
                else:
                    prefix = ''
                body = prefix + step['prompt']
                if step['documents_appended']:
                    body += '\n\n本轮读取的已备齐材料：\n'+'\n\n'.join(DOCS[d] for d in step['documents_appended'])
                messages.append({'role':'user','content':body})
                rounds.append({'round':index,'title':step['title'],'messages':[dict(m) for m in messages]})
                messages.append({'role':'assistant','content':f'<<{aid}.{index} 实际模型回复；占位符，不是模拟输出>>'})
            repair_messages = [dict(m) for m in messages]+[{'role':'user','content':REPAIR}]
            previews.append({'workflow':wf_id,'agent':aid,'name':a['name'],'predecessors':a['predecessors'],
                             'base_requests':rounds,'conditional_repair_request':repair_messages})
    (ROOT/'REQUEST_BLUEPRINTS.json').write_text(json.dumps({'preview_only':True,'not_executable_until_placeholders_are_filled':True,'agents':previews},ensure_ascii=False,indent=2)+'\n')
    lines = ['# 两个业务场景的 Agent 与逐轮请求','',
      '状态：应用设计与请求模板已具体化；没有调用模型。示例企业、供应商、产品、报价和访谈均为虚构，仅用于说明请求，不能用作真实实验输入或典型性证据。正式运行须换成真实授权材料并冻结版本。','',
      '图只画 Agent 依赖；全部资料在启动前就绪。每个 Agent 的前驱产物只在第一轮输入，内部不等待其他 Agent。下一轮请求携带同一固定 system、所有此前 user 消息和实际 assistant 回复，再追加当前 user 消息。','',
      '下面“轮”指一次实际模型请求，不是一次回答中的思维步骤。每个列出的基础步骤都有明确输入或产物；第三方应用并未验证这些具体轮次。是否需要如此分轮仍需质量核验及与合并调用比较。','',
      '## 固定 system prompt','', '```text', COMMON_SYSTEM.strip(), '```','',
      '每个 Agent 在这段固定 system 后追加下面的角色说明和 artifact 字段，随后保持不变。请求中不启用 tools。','',
      '## 请求消息的累计方式','',
      '```text','第1轮：[system_a, user_1]','第2轮：[system_a, user_1, actual_assistant_1, user_2]',
      '第3轮：[system_a, user_1, actual_assistant_1, user_2, actual_assistant_2, user_3]','```','',
      '完整展开后的 messages 见 [REQUEST_BLUEPRINTS.json](REQUEST_BLUEPRINTS.json)。其中前驱产物和 assistant 回复用明确占位符标记；它们不是模型结果或真实 trace。token 前缀和 KV 命中须在真实后端验证。','']
    for wf_id,wf in WORKFLOWS.items():
        lines += ['## '+wf['title'],'','用户提交：','', '```text', wf['user_task'], '```','',
                  '依赖：`'+', '.join(f'{s}→{t}' for s,t in wf['edges'])+'`。','',
                  '示例附件：`'+'`, `'.join(wf['documents'])+'`；[完整示例输入](example-inputs.json)。','']
        for aid in wf['agent_ids']:
            a=AGENTS[aid]
            lines += ['### Agent '+aid+'：'+a['name'],'',
                      '直接前驱：'+('、'.join(a['predecessors']) or '无')+'。',
                      '固定角色说明：'+a['role_instruction'],
                      '最终 artifact：`'+'`, `'.join(a['artifact_fields'])+'`。','']
            if aid in INITIAL_EVIDENCE:
                lines += ['第一轮另附原始证据：`'+'`, `'.join(INITIAL_EVIDENCE[aid])+'`，便于直接核对而非只信前驱摘要。','']
            for index,step in enumerate(a['base_rounds'],1):
                lines += ['**第'+str(index)+'轮：'+step['title']+'**','', '```text', step['prompt'], '```','']
                if step['documents_appended']:
                    lines += ['此轮附上已准备的文档：`'+'`, `'.join(step['documents_appended'])+'`。','']
            lines += ['完成上述步骤后，仅当其最终检查返回可修复 issues 时追加修订请求；不固定填充额外轮次。','']
    lines += ['## 所有 Agent 的条件修订请求','', '```text',REPAIR,'```','',
      '原 Agent 保留完整历史继续执行，最多追加两次修订；上限是防止失控，未解决时记录 needs_review 和问题，不伪装成功。正常任务计时包含检查、修订和队列。','',
      '## 连续与并行的边界','',
      '采购：A/B/C 可并行；D 只等 A/B，E 只等 B/C；F 只等 C/D，G 等 E/F。营销：H/I/J 可并行；K 等 H/I，L 等 I/J；M 等 J/K，N 等 K/L，O 等 M/N。M 与 N 没有相互等待；N 使用预先规定的资产 ID，不需要 M 的文案内容，O 完成最终绑定。','',
      '供应商数量、客群文件数量和问题驱动的修订会改变实际调用次数。没有固定每个 Agent 均三轮，也没有人为延时、随机填充或外部 Agent 逐轮反馈。图允许并行；实际服务重叠、工具占比、完整 prompt token 历史和缓存驻留仍需重新采集。','',
      '本地检查器只验证 JSON、来源引用和文案字符数，不是额外 LLM Agent；失败反馈追加到本 Agent 内部修订轮。若需要人工确认，当前任务以 needs_review 结束，不停在任务中等待人回复。','']
    (ROOT/'PROMPTS.md').write_text('\n'.join(lines)+'\n')
    print(f'Materialized {len(AGENTS)} Agents and {sum(len(a["base_rounds"]) for a in AGENTS.values())} base request templates; no LLM calls.')


if __name__=='__main__':
    materialize()
