# Background and Motivation rewrite

The user requested a complete chapter rewrite after discussing AKLM's Limitation/Challenge organization. This revision rewrites the English chapter and only Section 2 of the Chinese companion. It keeps the current paper template, all three figure blocks and their assets, labels, citations, and other chapters unchanged.

## Argument

1. Establish the execution hierarchy with the existing code-generation and deep-research examples: request, agent, workflow, dependencies, and WCT.
2. Explain the causal path from tool waits and conversation growth to reusable KV, worker failure, checkpoint retrieval/replay, and capacity/transfer tradeoffs.
3. Credit hierarchical caching, checkpointing, application/workflow awareness and load-aware recovery. The limitations concern incomplete decision criteria, not a claim that all previous systems ignore applications.
4. Limitation 1 leads to Challenge 1: connect recovery costs to workflow completion under uncertain remaining progress and potentially shared recovery resources.
5. Limitation 2 leads to Challenge 2: distinguish retaining reusable state from faster access, and consider normal reuse, capacity and movement costs together.
6. Keep numbered Observations and concrete placement mechanisms in Design.

## Evidence preserved

- CC/Weka: 393 filtered sessions, 121 retained workflows / 286 groups, temporal fan-in proxy allowing Main activity during parallel branches. ECDF is the per-workflow maximum duration gap, not fault-time slack or verified result dependencies.
- Figure 3: same model, hardware type and execution configuration as Figure 2(c). Reconstruction timings are physical measurements; WCT increments are separate single-branch, fixed-execution counterfactuals at an assumed all-branch join.
- Figure 2(c): common C=M+1 KV-ready endpoint, one new token, instrumented SGLang/MInference/DCA path. HBM is resident-state reference, not Peer recovery. DRAM/storage restoration is serialized. Three timings for HBM/DRAM, one per length for full prefill/storage. Storage remains the measured shared-filesystem path, not an identified SSD.
- No new performance claims, physical experiments, or integrated-policy benefits were introduced. Existing protocol and raw-result provenance remain intact.

## Verification

Canonical build completed with 22 pages. No undefined references/citations, duplicate labels, or overfull boxes. Existing acmart vspace warnings remain outside the rewritten chapter. All 49 protected files match their original SHA-256 values. All three LaTeX figure blocks are byte-for-byte preserved; the Chinese text outside Section 2 is unchanged. Final-size rendered pages 2–5 were visually inspected: chapter text, Figure 1, Figure 2's aligned row, Figure 3, and the transition to Design are readable without clipping or overlapping text. The revised text occupies pages 2–4; Design starts on page 5.

See review/VALIDATION.json, the two source diffs, build.log, rendered pages, and main-reviewed.pdf. This is a manuscript revision and layout check; it does not establish new empirical validation of AegisKV.
