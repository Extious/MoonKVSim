# Consolidated full-paper review

The canonical deliverable is `../../paper/main.pdf`: **14 total pages; technical content ends on page 12**, where references begin. The four-file LaTeX directory compiles independently. All six chapters, an abstract, citations and the AI-assistance disclosure are present.

The latest Motivation and Design work is integrated: four-path measured DPC reuse in Motivation; shared DRAM/SSD, tier-local rent, native sparse candidates, layer overlap and safe checkpoint/fallback semantics in Design. All six new Design figures remain in the main paper. The full expanded English source/PDF is preserved in `../../Archived/extended-dram-storage-paper-20260920/paper/`.

The evaluation package contains ten analytical plots. Five primary assets appear as Figures 10–12; five auxiliary plots remain in the Chinese companion and experiment package. Removing repeated illustrations did not remove the prediction regression: the main text retains the 4.558 s versus 3.621 s LRU counterexample. The 36 base scenarios have 17 improvements and 19 ties; they are not independent runs or a production distribution.

## Checks performed

- Inspected all 14 actual rendered pages and grayscale pages covering every main-paper figure; no text/legend clipping or unreadable encoding observed. Minimum figure type at the actual LaTeX insertion width is **10.032 bp**. Exact per-figure dimensions and hashes are in `font-check.json`.
- Independent compilation from copied `paper/` inputs passes. The final LaTeX log has no overfull boxes, undefined citations/references or errors. Routine class spacing/underfull warnings are not performance findings.
- Analytical model checks, exact capacity-release timing, feasible-oracle comparisons, own-policy healthy mates, campaign weighting, incomplete mates and completion ledger checks pass.
- Temporary synthetic fixtures exercise the future measured-data interface: negative estimates retained, partial confidence bounds drawn, paired differences separately labeled, and modified raw sources rejected. These fixtures are not hardware results and were not published.
- All 23 Chinese-companion images resolve. Current main-PDF assets, source files, script/configuration hashes and review provenance are recorded in `REVIEW.json`.

## Limits

The new evaluation has **zero physical system runs**. Its static allocator does not evaluate the complete rental/sparse/overlap controller. Existing Motivation measurements retain their narrower scope; DPC results are not cold-NVMe measurements. The experiment specification is `../../experiments/eurosys27/PROTOCOL.md`; the stable plotting/data contract is `../../experiments/eurosys27/DATA_CONTRACT.md`. Correctness, strong-baseline end-to-end WCT and healthy overhead remain the decisive missing evidence. This is a complete research draft, not proof of a high acceptance probability. No paper was submitted.
