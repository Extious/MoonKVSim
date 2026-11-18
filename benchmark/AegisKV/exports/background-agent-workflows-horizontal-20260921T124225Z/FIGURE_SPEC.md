# Background agent examples: horizontal revision

Two stacked, full-width schematic workflows. Each flows left to right: coordinator planning, four parallel agent lanes, coordinator aggregation. Every lane shows three sequential LLM requests interleaved with two tool calls. No loop/back edge. Code branches implement API/UI, prepare tests and update documentation from a shared plan; integrated testing occurs after their outputs join. Research branches cover performance, cost, safety and supply. Numbered calls are local to each lane, not global synchronized rounds.

Evidence: constructed execution examples, no measured durations, no KV data-flow arrows, no general claim that workflows always have four agents or three requests. Each lane maintains its own conversation, extended by the tool results used by the next request. Only coordinator results cross agent boundaries.

Style: existing paper Libertine, blue LLM requests, ochre tools, subdued lane containers; labels retain meaning in grayscale. Target width 177.8 mm, minimum font 10 pt. Preserve current Figure 1 label and other figures/data. Native Draw.io export plus placed-page visual review.
