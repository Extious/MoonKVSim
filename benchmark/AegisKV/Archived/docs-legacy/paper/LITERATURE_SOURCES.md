# Verified primary literature

Checked 2026-09-05. Metadata and these narrow claims were verified against the
publisher's paper page. Detailed mechanism comparisons require the full paper.

| Key | Primary source | Supported use |
|---|---|---|
| zhu2024fanoutqa | https://aclanthology.org/2024.acl-short.2/ | Zhu, Hwang, Dugan, Callison-Burch; ACL 2024 short papers, pp. 18–37. Human-decomposed, multi-document QA over Wikipedia. Does not make our derived timings physical observations. |
| qin2025mooncake | https://www.usenix.org/conference/fast25/presentation/qin | FAST 2025, pp. 155–170. KV-centric disaggregation, global cache and SLO-aware scheduling. Broader than our proactive Store-only simulation control. |
| strati2024dejavu | https://proceedings.mlr.press/v235/strati24a.html | ICML 2024, PMLR 235, pp. 46745–46771. KV streaming supports disaggregation, swapping and fault-tolerant replication. |
| jayakody2026ghostserve | https://proceedings.mlsys.org/paper_files/paper/2026/hash/d99e8e80a6c41e148db686918dd7eab3-Abstract-Conference.html | MLSys 2026. Erasure-coded KV with host-memory parity and reconstruction after device failure. Not implemented in this study. |

Do not infer comparative speedups or transfer their physical validation to MoonKVSim.

Model citation checked on 2026-09-05: the official
[Qwen3-8B model card](https://huggingface.co/Qwen/Qwen3-8B) supplies the
recommended citation for [Qwen3 Technical Report](https://arxiv.org/abs/2505.09388),
Qwen Team, 2025, arXiv:2505.09388. The manuscript cites this for model origin;
the experiment's exact configuration and tokenizer identities are bound by the
local frozen manifest. The live model card does not substitute for verification
of the pinned revision, nor does its long-context guidance validate this
simulation's extended-context output quality.

The official GhostServe and RaidServe PDFs were also opened on 2026-09-05.
Both contain 15 pages. Their citation entries record that verified page count;
unverified proceedings page ranges were removed. The official BibTeX endpoints
could not be retrieved through this environment's available HTTP clients.

Additional publisher pages checked on the same date:

- Parrot (OSDI 2024): https://www.usenix.org/conference/osdi24/presentation/lin-chaofan — application dataflow and semantic variables.
- SGLang (NeurIPS 2024): https://proceedings.neurips.cc/paper_files/paper/2024/hash/724be4472168f31ba1c9ac630f15dec8-Abstract-Conference.html — structured programs and RadixAttention reuse.
- RaidServe (MLSys 2026): https://proceedings.mlsys.org/paper_files/paper/2026/hash/507b4aacefe5325908e24f042617b741-Abstract-Conference.html — TP resilience and coupled compute/memory rebalancing; outside this experiment's DP-only scope.
- Strata (OSDI 2026): https://www.usenix.org/conference/osdi26/presentation/xie-zhiqiang — hierarchical caching, transfer layout, delay hits and overlap.

Algorithm foundations checked on 2026-09-05:

- Landlord: https://www.cs.ucr.edu/~neal/Young02Online and the author's BibTeX
  listing https://www.cs.ucr.edu/~neal/bibtex?paper=Young02Online confirm
  *On-Line File Caching*, Algorithmica 33(3), 371-383 (2002),
  DOI 10.1007/s00453-001-0124-5. Cite the caching formulation, without extending
  its competitive guarantee to the coupled AegisKV model.
- CPM: the ACM publisher record at https://doi.org/10.1145/1460299.1460318
  confirms Kelley Jr. and Walker, *Critical-path planning and scheduling*,
  1959, pp. 160-173. The publisher's indexed record was readable; a subsequent
  direct DOI open failed transiently.
- AIMD: Raj Jain's author-maintained publication list
  https://research.engineering.wustl.edu/~jain/papers/index.html confirms
  D. Chiu and Raj Jain, June 1989, volume 17(1), pp. 1-14.
  The original 14-page paper is available at
  https://pbg.cs.illinois.edu/courses/cs598fa09/readings/cj89.pdf.
  Cite the feedback mechanism, without transferring its convergence result
  to the changing HBM quota and pinning model.

The SGLang proceedings page was rechecked during final bibliography review:
it explicitly lists DOI `10.52202/079017-2000`. Its linked official conference
PDF contains 27 pages, confirming both fields already present in the citation.
The BibTeX endpoint did not yield a usable response; no metadata was inferred
from that endpoint.

## September 6 figure and mechanism review

The revision also reads the actual local PDFs below. Their figures inform the
organization in `RELATED_FIGURE_REVIEW.md`; none of their artwork is copied.
Preprint versions are taken from those files, without inferring a later venue.

- KVFlow: arXiv:2507.07400v1, 12 PDF pages; `benchmark/AegisKV/docs/related_works/2025/KVFlow: Efficient Prefix Caching for Accelerating LLM-Based Multi-Agent Workflows.pdf`.
  SHA-256: `2dc3180f91c34df920a7547f14fe92988527a76a277d2d17ddf6b558205d2f89`.
- Pythia: arXiv:2604.25899v2, 15 PDF pages; `benchmark/AegisKV/docs/related_works/2026/Pythia: Exploiting Workflow Predictability for Efficient Agent-Native LLM Serving.pdf`.
  SHA-256: `7283a8f87a00338d64c315312d8f487a21876f462902020a4b3cfbb525d2ba89`.
- Cortex: arXiv:2510.14126v1, 3 PDF pages; `benchmark/AegisKV/docs/related_works/2025/Cortex: Workflow-Aware Resource Pooling and Scheduling for Agentic Serving.pdf`.
  SHA-256: `96285f7dfb2887d8e4ff92b669f9ff45aa9f18bb69751128c8cc11899ba53f68`.

## Sources added for the recovered Motivation

- SemiAnalysis CC/Weka trace and its hash-block input convention:
  https://huggingface.co/datasets/semianalysisai/cc-traces-weka-062126
- NVIDIA AIConfigurator project identity:
  https://github.com/ai-dynamo/aiconfigurator

The latter identifies the model family; the current repository version was not
used to regenerate the historical latency predictions. Those original outputs,
configuration and generator are preserved under `data/motivation-real-cc/`.
