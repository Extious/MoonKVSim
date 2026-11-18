# Background narrative reconstruction

Scope: reconstruct Background in the English TeX and Chinese companion. Borrow the problem-building sequence from the supplied AKLM/FAPCM manuscript, not its algorithm, claims or prose. Keep application-level WCT as the objective and avoid introducing AegisKV placement mechanisms as background facts.

The new narrative establishes Request / Agent / Workflow and WCT through the existing code-generation and research examples; connects prefix reuse, retained state, failure and checkpoint replay; explains finite-capacity / transfer trade-offs; and describes what existing mechanisms provide before identifying why individual request-level costs cannot alone rank workflow recovery value. Retaining token history preserves logical recoverability, while retaining a KV checkpoint avoids reconstructing already computed state. The two are explicitly distinguished. Sparse access receives only a short definition; access evidence and selection mechanisms remain in Design.

Citation checks used primary sources: CachedAttention (USENIX ATC 2024 official abstract), Mooncake (FAST 2025 official abstract), DejaVu (PMLR ICML 2024), Parrot (OSDI 2024), KVFlow (arXiv 2507.07400v1), and MInference (NeurIPS 2024). Existing local PDFs for LUMEN and GhostServe were read to verify the recovery coordination and checkpoint roles. No global claim that prior work lacks workflow information is introduced. The source claims are kept separate from the manuscript's reasoning about finite-budget workflow protection.

All figure blocks/assets retain their prior content and numbering, including the single-column Figure 1 with unequal agent request counts. The Motivation body is preserved except its opening bridge after moving the WCT definition into Background. Its measurements and conditional counterfactual evidence are unchanged. System Design, Introduction, Evaluation and bibliography are outside the edit scope. Before snapshots, protected hashes and exact diffs are included here.

Build and final rendered inspection are recorded in review/VALIDATION.json.

Primary URLs checked:
- https://www.usenix.org/conference/atc24/presentation/gao-bin-cost
- https://www.usenix.org/conference/fast25/presentation/qin
- https://proceedings.mlr.press/v235/strati24a.html
- https://www.usenix.org/conference/osdi24/presentation/lin-chaofan
- https://arxiv.org/abs/2507.07400
- https://proceedings.neurips.cc/paper_files/paper/2024/hash/5dfbe6f5671e82c76841ba687a8a9ecb-Abstract-Conference.html

Final result: build succeeded (22 pages). Pages 2-4 inspected, Figure 1 remains in the right column of page 2. No undefined references/citations or overfull hboxes in the final build log. No whole-paper readiness claim; the existing experimental evidence limits remain.
