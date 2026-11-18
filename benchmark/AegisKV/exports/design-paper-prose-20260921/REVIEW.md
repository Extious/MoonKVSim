# Paper narrative revision — 2026-09-21

The user objected to the two Overview paragraphs that abruptly listed the failure contract and physical storage-object definitions. The revision replaces them with the purpose of the three-tier hierarchy, collaboration among the five modules, and the takeover path.

M and N are introduced with the recovery/transfer-overlap argument in the L/K subsection. Shared-object accounting is explained where prefix credit is allocated. Connector follows copying, publication and recovery, explaining why the old checkpoint remains usable during a transfer. Full fault-domain and object-format notes remain in the explicitly separate Chinese implementation supplement. DRAM's retention benefit when no storage copy exists remains explicit.

Both English and Chinese are synchronized. The English Design has 3,559 source words, compared with 3,620 before this revision; Overview has 234 rather than 293. These are source-word counts, not typeset body-only counts.

Validation:

- Canonical build completed and produced `paper/main.pdf`, 20 pages.
- No overfull boxes, undefined references/citations, duplicate labels or LaTeX errors in the checked build log.
- All three algorithm listings, eight Design figure blocks/captions and forty figure assets are byte-identical to the before snapshot. Other paper files are unchanged apart from the two prose sources and rebuilt PDF.
- Final PDF pages 4, 6, 8 and 9 were rendered and visually inspected, covering Overview, the M/N introduction, online algorithms and Connector. No clipping or overlapping text was observed.
- Numerical evidence, experiments and the historical adverse rental comparison were not changed. This is a narrative revision and compilation/layout check, not new experimental validation.

See `CHECKS.json` for structural checks, `delivery-manifest.json` for file hashes, `before/` for the previous sources/PDF and `review/` for page renders.
