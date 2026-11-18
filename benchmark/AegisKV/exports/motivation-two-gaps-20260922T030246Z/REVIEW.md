# Motivation: two literature-grounded gaps

User request: assess Motivation and Challenges, organize it around fault-tolerant serving without multi-agent workflow priorities and workflow-aware KV management without a worker-failure recovery objective, and connect it smoothly to Background.

The prior section discussed timing differences and generic resource costs before identifying the literature gaps. The rewrite starts from Background's tier capacity/access tradeoff, poses the finite-budget protection question, and uses four paragraph headings: Limitation 1 / Challenge 1 / Limitation 2 / Challenge 2. Workflow evidence supports the first gap. The second distinguishes normal reuse priorities from failure-surviving state and recovery placement, using KVFlow's documented suffix-eviction rule as a concrete example. Experimental setup details already available in Appendix A are no longer repeated in full.

Scope checks: LUMEN's load-aware checkpoint/routing/capacity mechanisms are acknowledged. TOPAS's workflow/JCT, prefix-residency, movement and preemption reasoning are acknowledged. The argument concerns the named systems' decisions, not an exhaustive claim that all fault tolerance or agent systems lack these properties. Existing plots illustrate cost/timing; they are not empirical comparisons against these systems.

Primary sources checked in this turn:
- https://arxiv.org/html/2606.17787v1 (Sections 4.1–4.2)
- https://arxiv.org/html/2507.07400v1 (Section 3.1; varying suffixes have highest eviction priority)
- https://arxiv.org/html/2608.25523v1 (Introduction and workflow scheduling objective)
- https://proceedings.mlsys.org/paper_files/paper/2026/hash/d99e8e80a6c41e148db686918dd7eab3-Abstract-Conference.html

Validation: Background, figure source blocks/assets, other chapters, Appendix A and the bibliography key set are unchanged. The Chinese section mirrors the English rewrite; its citation sequence was matched against the compiled LaTeX bibcite mapping. The manuscript builds to 22 pages without overfull boxes, undefined references, duplicate labels or LaTeX errors. Actual pages 3–5 were visually reviewed for the Background transition, paragraph flow, figure position and section transition. See VALIDATION.json and diffs.
