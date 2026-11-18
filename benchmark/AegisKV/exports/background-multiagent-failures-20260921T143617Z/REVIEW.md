# Background revision

Scope: multi-agent KV reuse and failure-driven reconstruction. English LaTeX and the Chinese companion are synchronized. Checkpoint and storage-tier explanations follow under their own paragraph heading. All figure blocks and protected manuscript files are unchanged.

Source checks:
- SGLang, Section 3: common-prefix KV reuse across calls and forked programs. https://proceedings.neurips.cc/paper_files/paper/2024/file/724be4472168f31ba1c9ac630f15dec8-Paper-Conference.pdf
- LUMEN: failures at scale remove both KV and serving capacity. https://arxiv.org/abs/2606.17787
- GhostServe: long-running agent applications, growing context, and failure reconstruction. https://proceedings.mlsys.org/paper_files/paper/2026/hash/d99e8e80a6c41e148db686918dd7eab3-Abstract-Conference.html
- DejaVu: state streaming/replication for recovery without full restart. https://proceedings.mlr.press/v235/strati24a.html

No frequency statistic or physical result was added. Illustrative coding/research histories explain the mechanism; shared-prefix examples are conditional on identical initial tokens and compatible model/position semantics. Existing citations and Markdown numbering were verified against the rebuilt aux. Canonical PDF: 22 pages. Pages 2 and 3 were rendered and visually inspected.
