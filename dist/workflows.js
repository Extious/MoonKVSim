// Public template structures; all context examples below are proposed, not captured traces.
window.WORKFLOWS = [
 {id:'coding',title:'程序求解',subtitle:'ChatDev · 通用问题解决',name:'先理解问题，再让不同能力协作。',description:'复用六个通用角色和十条显式依赖。信息搜集、技术实现与方案生成可以并行；逻辑分析只消费它需要的上游结果。',accent:'#2248ca',pale:'#edf2ff',source:'https://github.com/OpenBMB/ChatDev/blob/4fb2db0ea90375ce1059f44fe03ffbd191a7a169/yaml_instance/general_problem_solving_team.yaml',sourceName:'ChatDev · general_problem_solving_team.yaml',version:'4fb2db0',position:'主场景候选 01',
 nodes:[
 {id:'A',title:'需求分析',original:'Demand Analyze',x:30,y:176,pred:[],role:'识别任务目标、约束和所需分工，为固定团队生成任务说明。',context:'题目原文、输入输出格式、约束、公开示例。',output:'目标与约束清单；各角色的任务说明。',prompt:'阅读题目，明确输入输出与边界条件。将需要完成的工作交给已有角色，不新增 Agent。'},
 {id:'B',title:'信息搜集',original:'Information Searcher',x:285,y:58,pred:['A'],role:'搜集任务需要的事实和参考资料，整理来源，不替代技术实现。',context:'原始题目 + A 的信息需求；可用的本地文档索引。',output:'有来源的事实与实现参考。',prompt:'按任务说明查找所需接口、数据格式或算法参考；如果不需要额外信息，应直接说明。'},
 {id:'C',title:'技术实现',original:'Technician',x:285,y:176,pred:['A'],role:'完成可执行代码、脚本或技术方案。',context:'原始题目 + A 的技术任务；隔离的执行环境。',output:'候选实现与可用的验证结果。',prompt:'依据约束实现解法，检查公开示例和边界条件。记录验证结果，不读取隐藏答案。'},
 {id:'D',title:'方案生成',original:'Scheme Generater',x:285,y:314,pred:['A'],role:'提出可行思路和替代方案，说明各自适用条件。',context:'原始题目 + A 的方案需求。',output:'方案及选择理由。',prompt:'给出适合题目约束的方案与权衡；只完成分配的方案工作。'},
 {id:'E',title:'逻辑分析',original:'Reasoner',x:555,y:176,pred:['A','B','C'],role:'结合事实与实现进行推导、检查和判断。',context:'A 的分析要求 + B 的事实材料 + C 的实现结果。',output:'一致性检查、问题与推理结论。',prompt:'检查实现和题意是否一致，指出边界条件、推理漏洞和结论依据。'},
 {id:'F',title:'最终汇总',original:'Summary Department',x:825,y:176,pred:['B','C','D','E'],role:'整合各部门结果，形成面向用户的最终回答。',context:'B、C、D、E 的最终产物；任务本身。',output:'最终解答与必要说明。',prompt:'整合实现、参考、方案和逻辑检查，给出完整答案，不凭空增加结论。'}],
 edges:[
 ['A','B',[[190,198],[230,198],[230,94],[285,94]]],['A','C',[[190,212],[285,212]]],['A','D',[[190,226],[218,226],[218,350],[285,350]]],['A','E',[[110,176],[110,20],[635,20],[635,176]],true,[462,16]],
 ['B','E',[[445,104],[490,104],[490,190],[555,190]]],['B','F',[[445,82],[765,82],[765,190],[825,190]],true,[735,68]],
 ['C','E',[[445,212],[555,212]]],['C','F',[[445,232],[510,232],[510,414],[905,414],[905,248]],true,[698,403]],
 ['D','F',[[445,350],[785,350],[785,232],[825,232]]],['E','F',[[715,212],[825,212]]]],
 note:'图中呈现原模板的显式依赖。ChatDev 原执行器还有分层屏障；移植成按前驱就绪启动时，需披露调度策略变化。虚线不表示可选。',
 job:'dataset: APPS\njob_id: <题目 ID>\ninput: 题目 + 约束 + 公开示例\nenvironment: 固定的代码执行环境\noutput: 最终程序与解题说明',jobNote:'参数化 Job 示例，不是某条数据集原文。APPS 是编程题数据集，不是完整仓库修复环境。隐藏测试与参考解答仅供评测。',
 original:'六个 Agent 的分工和十条显式依赖来自公开 YAML。部分角色没有工具，不能保证所有 Agent 自然多轮。',adapt:'接入 APPS、预备执行环境和本地资料；必要时加入标准自反馈机制。移除网络或人工等待属于需要记录的改动。',verify:'任务正确率、自然调用轮数、执行工具耗时、实际并行区间、相邻调用的 token 前缀。'},
 {id:'finance',title:'投资评审',subtitle:'Agno · Investment Review',name:'先形成分析，再逐层完成评审。',description:'六个固定角色构成五个执行阶段。基本面与技术分析并行，风险、备忘录和决策依次消费前序结果。',accent:'#965016',pale:'#fff2e4',source:'https://github.com/agno-agi/investment-team/blob/5bb30f7d090c4b074e009578ee3dbd9209ad698d/workflows/investment_workflow.py',sourceName:'Agno · investment_workflow.py',version:'5bb30f7',position:'主场景候选 02',
 nodes:[
 {id:'A',title:'市场分析',original:'Market Analyst',x:20,y:180,pred:[],role:'梳理市场背景、行业状态和相关事件。',context:'公司、分析日期、当时可用的市场和新闻资料。',output:'市场背景与初步判断。',prompt:'基于指定日期之前可用的资料，分析公司所处市场和行业环境；标注信息来源。'},
 {id:'B',title:'基本面分析',original:'Financial Analyst',x:230,y:72,pred:['A'],role:'分析财务表现、估值和资产负债健康度。',context:'A 的市场评估 + 财报、比率、同行数据。',output:'基本面评估与主要依据。',prompt:'分析收入、利润、现金流和估值，核对关键数值。缺少同行数据时明确标记。'},
 {id:'C',title:'技术分析',original:'Technical Analyst',x:230,y:284,pred:['A'],role:'分析历史价格、成交量和趋势指标。',context:'A 的市场评估 + 截止分析日的价格与成交量序列。',output:'趋势、动量与技术信号。',prompt:'使用可用历史行情评估趋势与动量；不得使用分析日期之后的价格。'},
 {id:'D',title:'风险评估',original:'Risk Officer',x:440,y:180,pred:['B','C'],role:'综合两路分析识别主要风险和约束。',context:'B 和 C 的分析结果、相关历史资料与固定评审规则。',output:'风险评估及限制条件。',prompt:'核对两路分析中的冲突、下行风险和假设，形成风险说明。'},
 {id:'E',title:'投资备忘录',original:'Memo Writer',x:650,y:180,pred:['D'],role:'整理前序材料并撰写结构化备忘录。',context:'前序步骤的分析材料、风险结果和备忘录格式。',output:'结构化投资备忘录。',prompt:'按固定格式组织论据、风险与未知信息，保持关键数据和来源一致。'},
 {id:'F',title:'委员会决策',original:'Committee Chair',x:860,y:180,pred:['E'],role:'根据备忘录和委员会规则形成最终评审结论。',context:'投资备忘录、固定委员会规则和前序可用材料。',output:'最终决策、依据与条件。',prompt:'依照规则检查论据和风险是否充分，给出有依据的评审结论。'}],
 edges:[['A','B',[[180,202],[205,202],[205,108],[230,108]]],['A','C',[[180,230],[198,230],[198,320],[230,320]]],['B','D',[[390,108],[414,108],[414,202],[440,202]]],['C','D',[[390,320],[421,320],[421,230],[440,230]]],['D','E',[[600,216],[650,216]]],['E','F',[[810,216],[860,216]]]],
 note:'箭头表示执行前驱。后续角色可能同时读取更早步骤的累计材料；材料可见范围与执行边分别配置。此处未添加原模板不存在的分支。',
 job:'dataset: FinRpt + 经核对的补充快照\njob_id: <公司>_<分析日期>\ninput: 当时可用的财报、新闻与行情\noutput: 备忘录与评审结论',jobNote:'这是历史资料接入方案。FinRpt 与 Agno 模板不是原生配套；需检查行情窗口、同行指标等字段。中英译文不能计为两个独立 Job。',
 original:'固定五阶段、六角色和两路并行来自 Agno 官方应用。原版使用金融与搜索服务，也配置了历史和学习机制。',adapt:'将外部服务接入真实历史快照；隔离各 Job 的会话与学习状态，固定分析日期。逐项核对输入覆盖，不以模拟数值补缺。',verify:'资料完整性和时点一致性、工具往返时间、各 Agent 调用轮数，以及任务产物质量。'},
 {id:'editorial',title:'新闻编辑',subtitle:'GraphFlow · Parallel Editing',name:'同一份初稿，两种独立编辑视角。',description:'沿用公开写作编辑结构，使用多文档新闻作为任务材料。语法与风格编辑独立工作，再由最终编辑整合。',accent:'#08766b',pale:'#e9f7f3',source:'https://github.com/microsoft/autogen/blob/027ecf0a379bcc1d09956d46d12d44a3ad9cee14/python/docs/src/user-guide/agentchat-user-guide/graph-flow.ipynb',sourceName:'AutoGen · GraphFlow parallel editing',version:'027ecf0',position:'补充场景 03',
 nodes:[
 {id:'A',title:'内容起草',original:'Writer',x:100,y:180,pred:[],role:'基于给定材料形成新闻综合稿。',context:'一组原始报道 + 写作要求；不包含参考摘要。',output:'第一版新闻综合稿。',prompt:'综合这些报道，生成连贯且忠于材料的稿件。区分已知事实和材料中的不同说法。'},
 {id:'B',title:'语法编辑',original:'Grammar Editor',x:440,y:80,pred:['A'],role:'修正语法、指代、句法和用词错误。',context:'A 的初稿、原始报道和编辑要求。',output:'语法修订稿与必要修改说明。',prompt:'检查语法、指代和句法，修订表达错误，不引入材料之外的信息。'},
 {id:'C',title:'风格编辑',original:'Style Editor',x:440,y:280,pred:['A'],role:'改善结构、冗余、衔接和整体可读性。',context:'A 的初稿、原始报道和目标读者要求。',output:'风格修订稿与必要修改说明。',prompt:'改善结构与可读性，删去重复内容，保持事实和归属关系准确。'},
 {id:'D',title:'最终整合',original:'Final Reviewer',x:780,y:180,pred:['B','C'],role:'合并两路编辑结果，形成一致的最终稿。',context:'B、C 的修订结果 + 原始报道；明确配置材料可见范围。',output:'最终综合稿。',prompt:'整合语法与风格修改，消除冲突，核对最终内容是否忠于原始材料。'}],
 edges:[['A','B',[[260,202],[350,202],[350,116],[440,116]]],['A','C',[[260,230],[330,230],[330,316],[440,316]]],['B','D',[[600,116],[690,116],[690,202],[780,202]]],['C','D',[[600,316],[710,316],[710,230],[780,230]]]],
 note:'原公开示例的任务是短文写作，采用固定的双编辑汇合结构。这里提出移植为多文档新闻任务；没有把它称为已验证的生产流程。',
 job:'dataset: Multi-News\njob_id: <材料组 ID>\ninput: 多篇相关文章 + 写作要求\nreference: 人工摘要，仅供评测\noutput: 编辑后的综合稿',jobNote:'参数化 Job 示例。原始文章可直接成为上下文，因此该配置可以不访问网络；是否需要多轮仍由明确的执行配置决定。',
 original:'起草、并行语法/风格编辑、最终整合来自 AutoGen 官方示例。原例不包含工具，也未配置每个 Agent 多轮。',adapt:'全部移植到 Agno；将固定示例题目替换为新闻材料，明确消息可见范围。若加入自反馈修订，需要保留原生配置对照。',verify:'事实一致性、内容覆盖、编辑质量、调用轮数和前缀保留；不因结构简单就删除不显著结果。'}
];
window.SOURCES=[
 ['ChatDev 通用问题解决团队',WORKFLOWS[0].source,'六个角色与十条依赖；固定源码版本 4fb2db0。'],
 ['Agno 投资评审应用',WORKFLOWS[1].source,'五阶段、六个 Agent；固定源码版本 5bb30f7。'],
 ['AutoGen GraphFlow 示例',WORKFLOWS[2].source,'公开并行编辑结构；固定源码版本 027ecf0。'],
 ['APPS','https://github.com/hendrycks/apps','编程题、代码评测与数据集。'],
 ['FinRpt','https://huggingface.co/datasets/jinsong8/FinRpt','金融资料、中间提示词与生成结果；不是本项目运行 trace。'],
 ['Multi-News','https://github.com/Alex-Fabbri/Multi-News','多文档新闻摘要任务与公开数据。'],
 ['Agno 自定义 Workflow','https://docs.agno.com/workflows/workflow-patterns/fully-python-workflow','用 Python 控制依赖、数据传递与执行。'],
 ['Agno ReasoningTools','https://docs.agno.com/reasoning/reasoning-tools','模型驱动的 think / analyze 工具循环。'],
 ['Self-Refine','https://selfrefine.info/','已有的生成、反馈、修订方法；组合进模板是适配方案。']
];
