# Multi-agent examples for Background

Purpose: explain how a multi-agent application decomposes work, executes repeated LLM/tool calls with per-agent conversation state, and combines branch outputs.

Evidence: two constructed application examples, informed by AutoGen (https://arxiv.org/abs/2308.08155) and the orchestrator/subagent pattern in Anthropic research (https://www.anthropic.com/engineering/multi-agent-research-system). They are not measured executions or literal reproductions of either implementation.

Panels: (a) Add CSV export: Main plans, Code agent creates a patch, Test agent then checks the patch, and Main accepts or requests revision. Code-to-test is sequential; the research panel forks into independent investigations. (b) Compare battery technologies: Lead splits technical and cost questions, subagents gather evidence with tools, Lead synthesizes a cited report. A sample call/tool/call sequence and repeat edge make each agent's multi-request nature explicit. Each agent maintains its own conversation; this does not imply that prefixes never overlap. Arrows denote task/result or within-agent execution order, never KV transfers. Layout has no time scale or measured durations.

Style references inspected: current workflow.png for light fills and restrained routing, and system-overview.png for the manuscript's Libertine text. The examples borrow their typography and clear containers, not measured timing or system components. Two side-by-side top-down panels at the paper's full 505.89 TeX-point width. Minimum source text 23 px targets more than 10 pt after insertion. Colored LLM/tool boxes also have direct labels for grayscale.

Deliver native Draw.io source, native PDF/PNG/SVG, a paper PDF/preview, synchronized English and Chinese explanatory text, and the canonical main.pdf. Existing figure data and assets are preserved; adding the new first figure requires reference-number synchronization.
