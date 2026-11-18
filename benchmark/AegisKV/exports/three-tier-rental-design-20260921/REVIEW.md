# Three-tier renewable-credit design revision

2026-09-21. The user requested an integrated Peer HBM / DRAM / Shared storage rental algorithm, partial Peer layers/blocks, patent-derived Adapter behavior, and a closed online KV Master loop, with the result written into the paper.

## Delivered manuscript

- Canonical PDF: `../../paper/main.pdf` (23 pages); English Design: `../../paper/system_design.tex`; synchronized Chinese companion: `../../paper/paper_draft.md`.
- Seven Design subsections remain. KV Master has three parts: tier-conditional/prefix value, per-request L/K, and online renewal/admission/eviction. Algorithm 1 is Tracker, Algorithm 2 is the rental event loop, Algorithm 3 is guarded AIMD.
- The single-column three-band Overview retains black component numbers and symmetric DP boards. It now shows rental/value management and AIMD. Figure 10 adds a constructed shared-credit ledger. All other existing figure bytes are preserved, including all Evaluation figures and the historical negative rental result.
- Abstract, Introduction, the rental Evaluation subsection, ablation descriptions, Related Work, the Chinese companion, and current experiment specifications now identify the same proposed policy. The paper directory still contains exactly four root TeX files and no scripts, logs, raw data, or drawing sources.

## Algorithm decisions and boundaries

1. Complete coverage remains in DRAM or Shared storage; Peer is an additional, backed, per-request L/K hot replica. A storage-full DRAM demotion includes lower-tier relief and valid fallback. Peer release need not repeat D2H when immutable complete backing already exists.
2. Credit reflects normal reuse and Slack-exposed recovery cost, conditioned on actual available tiers, routing, and engine cache hits. Legal prefix increments use a fixed known endpoint and distribute value through the prefix instead of assigning the whole request's value to its newest block. Required auxiliary state determines legal group boundaries. Physical replicas are counted once while distinct Agent contributions accumulate.
3. Each pool has its own rent clock rho; L only denotes Peer layer depth. Per-Agent current grant and paid rent are separate. Actual deduplicated use renews only that Agent. A value refresh keeps paid amounts. All committed copies age, including protected copies outside the safe victim queue. Prospective incoming groups pay the admission trial charge and install residual shares when committed.
4. Bounded search examines alternative legal victims instead of stopping at the first failed minimum-credit victim. Pools never compare incompatible rent keys. Optional plans must pass a current whole-plan WCT/copy-interference test. Required capacity relief bypasses optional admission's positive-credit gate, never physical leases. Finite work can reject feasible improvements; no optimality or classical competitive bound is claimed.
5. Arrival/reuse, checkpoint, final request snapshot, value change, handoff, pressure, failure, commit and abort feed one event loop. A short round offers its final partial block with valid-length/copy-on-write semantics before engine references are released. Accepted transfers hold physical source leases. Existing committed objects can attach by metadata without recopying or renewing unchanged shares.
6. Trial rejection does not advance a committed clock. Prepared capacity handoff first establishes required complete backing/fallback and rechecks generations/leases; it then advances the relevant clock and withdraws victims. Drainage precedes reuse of physical bytes. Failure before handoff discards the trial; failure after a committed handoff does not roll back real victims or rent.
7. Adapter retains pressure-driven multiplicative decrease, stable-window additive increase and a physical ceiling. The cap can be one half of the managed pool. Initial quota/count are zero; positive deferred demand permits growth from zero. The window is configurable, Z stays fixed, and Adapter chooses neither objects, rent, L nor K. Logical Peer pins can yield to quota shrink, but physical leases cannot.

## Source grounding

The current paper was read before editing. Patent inputs were the archived final-version DOCX (its composite normal-reuse/Slack value and HBMQuotaAIMD section), its README distinguishing the old patent from revision 3, the annotated Figures 2/3, and the standalone Algorithm 3 Draw.io. The existing `python/moonkvsim/aegiskv/hbm_quota_aimd.py` was inspected for original pressure/stability semantics. The new proposal intentionally does not restore the old patent's independent HBM-only completeness semantics.

The three referenced historical task reads were attempted, but the exposed task-reading tool returned unavailable. No unavailable task content was treated as verified source; the provided conversation and live repository documents supplied the context.

Cost/size caching background was checked against [Young's original paper](https://arxiv.org/abs/cs/0205033) and [Cao and Irani's original GreedyDual-Size paper](https://www.usenix.org/legacy/publications/library/proceedings/usits97/full_papers/cao/cao.pdf). They support the historical cost/size and renewal/aging principles, not a guarantee for this dynamic tiered extension.

## Checks actually performed

- `SEMANTIC_CHECKS.json`: 41 finite specification checks, including 180 finite-grid rent-conservation/lazy-settlement cases. They cover Agent-local renewal, duplicate-use suppression, value decrease/increase without refund, prefix telescoping, high-Slack normal reuse, shared physical bytes, conditional Peer benefit, common-join nonadditivity, partial/unpersisted checkpoint rejection, stale metadata generation, leases, whole demotion, final-copy fallback, alternative victims, residual incoming credit, and AIMD ceiling/debt behavior.
- These are constructed arithmetic/reference-state checks. They do **not** implement the full planner, predict actual GPU timing, test concurrent production code, establish AIMD stability, or measure WCT/CPU overhead.
- `DOCUMENT_CHECKS.json`: seven Design subsections, three Master parts, three algorithms, eight Design figures, exactly four TeX inputs, all figure paths present, and no overfull boxes or unresolved/multiply-defined references in the final build. Background/Motivation bytes and 36 unchanged existing figure files were preserved; the only replaced old figure pair is Overview.
- Native Draw.io PNG/PDF exports were inspected. An initial wrapped title and long footer in the ledger diagram were shortened at source and re-exported; type size was not reduced. At 84.7 mm column width, extracted minimum text sizes are 10.09 pt for Overview and 10.18 pt for the ledger.
- Actual rendered manuscript pages were inspected for the new Insights paragraph, Overview, prefix value, layer/block figures, credit formula/ledger, Algorithms 2/3, Adapter/Connector transition, and revised negative-result discussion. Updated diagram placements were also inspected in grayscale. Body and pseudocode retain the manuscript's 10 pt size.

## Evidence preserved

The 462.96/506.39 historical comparison and its original figure remain. Its diagnosis adds the failed hit-renewal-only variant (512.67), value-refresh variant (477.86), and refresh-plus-two-victims variant (466.76). The latter remains 0.82% worse than direct in the base case and beats direct in only 9 of 36 constructed sensitivity cells, with greater key-maintenance work. These are explicitly isolated models, not measurements of the newly written controller.

The remaining research work is integrated implementation and matched direct-versus-rental evaluation with real or calibrated resource profiles, prefix/multi-Agent sharing, finite-tier transitions, controller budgets and fault injection. This delivery completes the requested algorithm specification and manuscript revision; it does not establish end-to-end performance.

## Reproduction and provenance

From the repository root:

```sh
.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/check_three_tier_rental.py
.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/build_rental_design.py
sh benchmark/AegisKV/experiments/scripts/paper/build_paper.sh
```

After generating diagram XML, export it with the installed native Draw.io wrapper (`--crop -x -f pdf -e -b 1`; PNG additionally `-s 2`) and publish the PDF/PNG pairs before compiling. Editable sources are in `sources/`; the numerical ledger input is `data/credit-example.json`; native exports are in `figures/`; actual paper renders are in `review/`. The pre-edit package is in `before/` with `before-manifest.json`. `delivery-manifest.json` and `DOCUMENT_CHECKS.json` bind the delivered sources and PDF to their SHA-256 values.
