# Image-generation concept review

Selected artifact: `serving-model-concept.png` (1448 × 1086, 4:3). Built-in imagegen was used twice: initial generation from `PROMPT.txt`, followed by the localized edit in `EDIT_PROMPT.txt`. This is a raster layout study requested by the user, not an editable vector figure or a replacement for the canonical manuscript asset.

## Fidelity and iteration

The teacher's original caption is the scope authority: runtime maintains dependencies and accepted histories; ready invocations map to workers; workers retain per-agent KV across iterative turns. The existing expanded assistant-authored caption was not used as a requirement to preserve every implementation detail.

The selected image preserves all ten requested DAG edges: A1→B1, A1→C1, B1→Tool, Tool→B2, B2→A2, C1→A2; D1→E1, D1→F1, E1→D2, F1→D2. B1/B2 are requests by the same Agent B, not different agents. The dispatch labels B2/E1 and C1/F1 match the B/E and C/F caches, so both workers mix workflows. Accepted token/tool history belongs to the runtime; KV belongs to workers. The B row is the only expanded retention example, with a reusable prefix and appended state. TP is a group-level label rather than repeated rank internals.

Version 1's dashed return path was not visibly attached to both workers. Version 2 adds two worker-boundary stubs and a common return collector ending at accepted histories. The same edit removes the small three-line compatibility annotation; conditional reuse remains part of the brief and manuscript text. No claim is made about fixed block counts, exact cache sizes, measured hits or recovery performance.

## Actual inspection and limits

Viewed the native generated images and rendered the selected image at the actual 84.68 mm column width, in color and grayscale (`review/`). The revised output connectors and required labels are visible; direct agent labels and the separate Reuse/Append braces support grayscale interpretation.

The downscaled study is about 63.51 mm tall, but several secondary labels and DAG-node labels are too small for the current paper's 10 pt figure-text target. Raster text cannot be certified through PDF text metadata. This study should therefore be judged for semantic hierarchy and composition, not treated as final typesetting. A later editable version should reallocate space toward node/request labels, reduce oversized header area, and use a single concise TP note while checking every label at actual placement size. No further generation was performed merely to claim final-paper compliance.

The original manuscript figure/source remains the canonical vector version. All conceptual images, prompts and this review live outside `paper/`.
