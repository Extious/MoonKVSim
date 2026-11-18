# Background serving figure: remove history panel

User correction (2026-09-23): the Agent histories part is unnecessary.

- Removed the history container and both labels from the native Draw.io generator.
- Runtime now directly submits to Router; dashed worker output paths return to the runtime boundary.
- Reduced the runtime and canvas height and shifted Router, workers and legend upward by 56 source units. Column width and typography are unchanged; figure size is 84.68 x 83.35 mm.
- Preserved workflow nodes/edges, per-rank K/V, no Tool labels, and Reused KV/New KV legend. Updated caption, Description and exporter checks.
- Inspected native color, grayscale and actual manuscript page 1. No clipping, dangling endpoints or label overlaps observed.
- Canonical manuscript compiled to 8 pages with no undefined references/citations or overfull boxes. Source checks and unchanged-input hashes are in checks.json and unchanged-inputs.json; before copies are under before/.
