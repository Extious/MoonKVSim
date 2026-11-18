# System Overview: single-column placement

User request (2026-09-19): restore the earlier single-column System Overview.

Changed `paper/sections/system_overview.tex` from `figure*` / `textwidth` to `figure` / `columnwidth`. The vector figure, labels, caption and aspect ratio are unchanged. Figure 4 now appears on page 5, approximately 84.68 x 76.19 mm. Color and grayscale page renders were inspected for clipping, overlap and label preservation.

Minimum diagram text is approximately 4.97 pt. This is the known limitation of scaling this original dense diagram into one column, not a 10-pt readability result. The user explicitly selected this layout; no redraw was introduced.

The 12-page manuscript and independently compiled ZIP agree in text and rendered pixels. No LaTeX errors, unresolved citations/references or Overfull hboxes; nine original Underfull hboxes remain. Previous deliverables are retained in `before/`; current validation is `../../VALIDATION.json`.
