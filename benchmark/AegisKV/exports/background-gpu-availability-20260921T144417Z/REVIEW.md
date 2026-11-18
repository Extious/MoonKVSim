# GPU-server availability figure

Question: does a real GPU-infrastructure outage calendar illustrate recurring loss of available servers? Evidence: original public production-training node-event records, not serving recovery or synthetic GPU failures.

Source: stepfun-ai/InfiniteHBD-Trace commit 7aacdc8c3d2352c5b784bc0ea31756e1620daed1. Downloaded README, Apache-2.0 license, event JSON and category counts are preserved with hashes in experiments/data/background-infinitehbd/SOURCE.json. The release reports a 400-server cohort. The paper describes 8-GPU nodes, but this plot directly reports servers, not device health or idle GPU capacity.

All 1,168 events pair into 584 records by node plus complete fault category; 231 distinct nodes have events. Fourteen pairs have zero recorded duration and remain in paired-events.csv, contributing no duration. One node has overlapping faults with different categories; two interval boundaries merge after per-node union. There are 568 positive node-union intervals. Starts and ends use [start,end); simultaneous events are applied together. A direct interval-membership check independently verifies every step.

The plot uses the entire unchanged released event_time axis from day 0 to 348.9798. The first event is at day 3.8955; no calendar origin is inferred. The README's nominal 348-day duration is not used to truncate late events. Availability is explicitly 400 minus nodes within active recorded fault intervals. This requires the documented fixed cohort and counts no unrecorded prior outage. All cause categories, including tests, changes and unknowns, are retained; it is not a hardware-crash-only sample. Minimum available: 365; maximum concurrently unavailable: 35; time-weighted available: 390.7407. These are derived record counts, not 584 independent experiments.

Native canvas: 84.7 mm by 46.99 mm, vector PDF/SVG, Libertine approximately 10.05 pt. Entire trace retained without smoothing or cherry-picked window. A cropped line-plot ordinate (360–403, explicitly ticked) resolves variation; no area fill or zero-based bar is implied. Color, grayscale, and actual manuscript pages 3–4 inspected. No overlaps/clipping found. Current Figure 2; later figures and all Markdown numeric references updated against the compiled aux, with a new reference 32. The old companion's wording was preserved except new figure text and numeric renumbering. Build has no undefined references, duplicate labels, or overfull boxes.

No GPU computation. Existing Design, Evaluation, and figure assets unchanged. Existing live-editor auxiliary products in paper/ changed during compilation and were left intact.

Reproduce: python benchmark/AegisKV/experiments/scripts/paper/render_gpu_availability.py --output <review-directory> --publish
