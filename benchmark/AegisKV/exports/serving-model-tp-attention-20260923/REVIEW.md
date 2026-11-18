# TP attention detail: generated preview review

Selected image: `serving-model-tp-attention.png`, 1536 x 1024 pixels, landscape 3:2. Built-in imagegen made three edits in this revision: the initial addition, an unsuccessful matrix/connection correction, and a constrained correction based on the initial image. Prompts and rejected candidates are retained here.

## Content checked in the actual selected image

- All ten original workflow dependency edges remain: six in Workflow 1, four in Workflow 2. B1 and B2 are explicitly identified as turns of Agent B.
- Ready B2/E1 requests map to Worker 0; C1/F1 requests map to Worker 1. Both workers serve agents from both workflows.
- Exactly two ranks exist per worker. Both ranks contain the same assigned agents, with a separate Q glyph, K bar, and V bar for each agent. This is not request parallelism disguised as TP.
- The diagram explicitly declares an illustrative MHA layer with 8 Q/KV heads and TP=2. Rank 0 owns Q/KV heads 0–3; Rank 1 owns heads 4–7. Equal visible token coverage for each agent is explicitly distinguished from different head ownership. This example does not claim the same nonoverlapping layout for MQA, replicated GQA, MLA, or context parallelism.
- Both B cache pairs show a retained prefix and appended suffix. The bars are schematic tensors, not exact byte sizes, token counts, or measured proportions. Each bar represents all rank-local heads.
- All FOUR local attention operations and all FOUR output projections are contained within their individual ranks. Each has a visible local-input path.
- Each worker has its own all-reduce AFTER the two output projections. p0 and p1 denote corresponding per-request/token projected contributions, whose sum y becomes available on both ranks. There is no historical-KV gather or cross-worker collective.
- The dashed accepted-output return originates separately at BOTH full-worker boundaries, joins the external collector, and returns to Accepted histories. It is not sourced from an intermediate attention-layer activation.

## Rejected-generation findings

`candidate-v1.png` had ambiguous K/V row geometry, head axes spanning different agents, missing explicit attention inputs, and a missing Worker 1 return connector. `candidate-v2.png` improved some cache labels but incorrectly merged two ranks' local attention and projection operations into a worker-wide path; it must not be used. The selected version restores independent rank computation and uses explicitly labeled tensor bars instead of unreliable head-row grids.

## Export and placement review

The selected native generated image was inspected. Diagnostic renders at 84.68 mm and 178 mm widths were made using PyMuPDF; `review/column-144dpi.png` and `review/wide-gray-144dpi.png` were actually opened. Full-resolution viewing makes the added head and collective details readable. At the current manuscript's 84.68 mm single-column width the text is too small. A 178 mm grayscale view is more readable, but does not establish compliance with the manuscript's 10 pt requirement; raster glyphs have no reliable extractable font metadata. Blue/amber tones are similar in grayscale, while their boundary remains visible; formal monochrome typesetting should label those regions directly or strengthen the redundant encoding.

This is the requested image-generation layout preview, not a paper-ready editable vector export. `review/column-placement-raster.pdf` is only a diagnostic raster-in-PDF wrapper and must not be described as vector source. The current native manuscript figure and compiled paper were not replaced with this study.

Sources: teacher attachment paragraphs on workflow mapping and TP-local KV; the current conversation's MHA/TP clarification; NVIDIA Megatron's primary explanation at https://research.nvidia.com/labs/adlr/MegatronLM/. No measurements or performance claims are represented.
