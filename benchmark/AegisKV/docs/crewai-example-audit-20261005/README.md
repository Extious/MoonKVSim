# CrewAI 官方实例的源码依赖核对

核对时间：2026-10-05。证据是官方公开源码，不是实际执行 trace；本次没有运行模型、联网工具或故障实验。依据最新要求，仅保留文字核对记录，不交付不满足条件的实例图；源码配置不能证明实际请求轮数、历史前缀、GPU 执行并发或工具耗时。

## 营销策略

官方代码：<https://github.com/crewAIInc/crewAI-examples/blob/main/crews/marketing_strategy/src/marketing_posts/crew.py>

3 个 Agent：研究员、策略员、创作者。5 个任务依次为 research、project_understanding、marketing_strategy、campaign_idea、copy_creation；后两组各由同一 Agent 执行。代码使用 Process.sequential，所有任务均未开启 async_execution。按相邻同 Agent 任务归纳，执行结构为 A→B→C；任务展开是 A→B(项目理解)→B(策略)→C(创意)→C(文案)。copy_creation.context 直接取策略和创意产物，属于任务级数据输入关系，并不带来并行。Agent 使用 SerperDevTool/ScrapeWebsiteTool；多轮与工具时间需要实测。同一 Agent 对象承担两项任务不证明完整对话历史或兼容 token 前缀自动延续。

## 会议准备

官方主程序：<https://github.com/crewAIInc/crewAI-examples/blob/main/crews/prep-for-a-meeting/main.py>

任务配置：<https://github.com/crewAIInc/crewAI-examples/blob/main/crews/prep-for-a-meeting/tasks.py>

Agent 配置：<https://github.com/crewAIInc/crewAI-examples/blob/main/crews/prep-for-a-meeting/agents.py>

4 个 Agent、4 个任务。A 调研参与者/公司、B 分析行业，均 async_execution=True；C 等 A/B 产物构建讨论策略；D.context 为 A/B/C，直接读取三者。声明的产物边为 A→C、B→C、A→D、B→D、C→D，固定拓扑。D 的额外 A/B 边是原始资料输入，即使执行顺序已由 C 传递，也保留其语义。Python 输入参与者/会议背景/目标，没有额外问题分析 Agent。各 Agent 配备 ExaSearchTool，联网工具短耗时未验证，四个 Agent 全部多轮也未验证。这个实例原型满足固定任务图与两个并行分支的配置要求，但仍是较简单的局部汇合。

## 写书 Flow

官方主程序：<https://github.com/crewAIInc/crewAI-examples/blob/main/flows/write_a_book_with_flows/src/write_a_book_with_flows/main.py>

章节 Crew：<https://github.com/crewAIInc/crewAI-examples/blob/main/flows/write_a_book_with_flows/src/write_a_book_with_flows/crews/write_book_chapter_crew/write_book_chapter_crew.py>

大纲 Crew：<https://github.com/crewAIInc/crewAI-examples/blob/main/flows/write_a_book_with_flows/src/write_a_book_with_flows/crews/outline_book_crew/outline_crew.py>

大纲 Crew 内为研究员→大纲作者；模型输出 chapters 后，主程序每章创建新的 WriteBookChapterCrew，内部为研究员→章节作者。最后 join_and_save_chapter 是 Python 字符串拼接与文件保存，不是 Agent。章节组数 n 来自运行中的模型输出，总 Agent 实例数为 2+2n。3 个 Flow 方法固定，不代表展开后的 Agent 图在执行前固定。

原代码在 async write_single_chapter 中直接调用同步 crew.kickoff()，函数内没有 await，再用 asyncio.create_task/gather 包装。与 CrewAI 0.152.0 的同步 kickoff 组合时，这些协程没有模型等待期间的让出点，因此不应将其标为已验证并行。需要采用对应版本的异步 Crew API并实际记录请求时间重叠。

版本边界：该实例 pyproject 声明 crewai[tools]>=0.152.0，未锁定上界；本次对同步 kickoff 的分析使用官方 0.152.0 实现，不声称测试所有允许安装的版本：<https://github.com/crewAIInc/crewAI/blob/0.152.0/src/crewai/crew.py>。研究员使用 SerperDevTool，章节作者未设置工具；长输出本身不等于多次模型调用。

## 对 AegisKV 的适配结论

三者均不能未经修改与实测就宣称满足全部要求。会议准备是固定/并行方面最接近的原型；营销策略提供通用业务职责；写书提供多产物组织思路，但分支数动态且原异步实现需修正。若以这些原型扩展固定多轮 DAG，须将扩展拓扑标为项目设计，单独核对各 Agent 的历史、模型实际请求数、工具时间和应用质量。本次未修改现有应用候选、实验或论文。
