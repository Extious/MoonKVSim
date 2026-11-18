# Background explanation revision

User feedback: the teacher found the manuscript weak and Background uninformative. The prior readiness review checked evidence labels and figures but did not sufficiently test whether Background taught the execution and recovery process.

## Revision

Replaced only the Background prose and its Chinese companion. The four parts explain (1) request / tool / agent / workflow execution, (2) Prefill, Decode and reuse of sequence-specific KV, (3) memory-tier access and the distinction between retained state and sparse demand, and (4) worker failure, token replay, checkpoint restoration and remaining-tail replay. A coding-agent example connects the first two parts. Failure scope remains explicit in its operational context.

This is explanatory background, not a new observation, policy or experiment. Motivation bodies/captions and all four Motivation figure PDFs retain their prior contents. Introduction, Abstract, Design and references.bib are unchanged. The old Background and PDF are in before/; background.diff records the prose edit.

## Source checks

Existing bibliography entries were retained. Primary sources checked for the relevant explanations:

- Agent loop and delegated workflow: https://www.anthropic.com/engineering/multi-agent-research-system
- Cross-turn reuse, hierarchy and transfer overlap: https://www.usenix.org/conference/atc24/presentation/gao-bin-cost
- Distributed KV storage: https://www.usenix.org/conference/fast25/presentation/qin
- Sparse attention access: https://proceedings.neurips.cc/paper_files/paper/2024/hash/5dfbe6f5671e82c76841ba687a8a9ecb-Abstract-Conference.html
- KV streaming/checkpointing: https://proceedings.mlr.press/v235/strati24a.html
- Worker loss, retained token history and surviving capacity: https://arxiv.org/html/2606.17787v1

## Verification

Built the canonical paper/main.pdf with the repository build script. The final log has no undefined references/citations, LaTeX warnings or overfull boxes. Visually inspected rendered pages 2--4 for Background, Motivation figures and the transition to Design. The file contains 21 pages. Source/figure hashes outside the scoped prose edit were checked against before-hashes.json; after-hashes.json records the delivery. This is a scoped revision and rendered review, not certification of the full paper's submission readiness.
