# Inline Connector — 2026-09-21

Removed the standalone Connector subsection and its unreferenced label from English and Chinese. Overview explains transfer execution/feedback, and Master's online loop retains completion events and availability of the previous recovery point during checkpoint copying. Design now has six subsections ending with Adapter.

Removed only `connector-number` from the editable Overview. All other Draw.io cells, including both Connector boxes and the bidirectional Master link, are identical to the previous version. Text and captions now use callouts 1–4.

Regenerated native Draw.io PDF/PNG, inspected the PNG and final manuscript pages 4, 8 and 9. The single-column figure retains approximately 10.14 pt minimum text. Canonical `paper/main.pdf` rebuilt successfully at 20 pages with no overfull boxes, unresolved references/citations, duplicate labels or LaTeX errors. The three algorithms are unchanged. Other manuscript inputs and figure assets remain byte-identical; checks and final PDF hash are in `CHECKS.json`.

Source generator: `experiments/scripts/paper/build_connector_overview.py`. Editable source: `sources/system-overview.drawio`. Native exports use the installed Draw.io wrapper and `sources/fonts.conf`. The previous sources and deliverables are preserved in `before/`.
