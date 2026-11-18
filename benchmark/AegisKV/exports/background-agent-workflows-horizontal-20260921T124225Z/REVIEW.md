# Horizontal Background workflow revision

User correction: left-to-right workflows, more parallel agents and explicitly unfolded requests instead of loops.

The two examples are stacked across the full paper width. Each has four agent lanes, each containing LLM 1 → tool → LLM 2 → tool → LLM 3. Code branches prepare API/UI changes, tests and documentation from a shared specification; their outputs are merged before integration testing. Research branches cover technical performance, costs, safety and supply. Task assignment and result aggregation edges all move forward. Coordinator phases use a neutral style distinct from individual blue LLM request boxes. Call indices are local to each agent; no synchronization, execution durations, KV transfers or measured results are implied.

The first native export exposed tight event labels and a long role label. Shorter actions and additional vertical padding resolve this in the final export. Final native PNG/PDF, paper page 3 and grayscale were visually reviewed at the intended 177.8 mm width (99.34 mm height); minimum figure text is 10.32 pt. Adjacent manuscript pages 2 and 4 retain readable text and figure placement. Build completed successfully, 22 pages. Existing unrelated underfull boxes, vspace and bibliography warnings remain outside this revision; no whole-paper submission-readiness claim is made.

Background prose, caption, accessibility description and Chinese companion now match the new workflow. Figure numbering remains unchanged. Motivation text, all 20 other figure PDFs and main/abstract/system-design sources are unchanged from the before snapshot. Native Draw.io XML and generator are retained in sources; canonical paper/main.pdf was updated.

Reproduce by running the generator with --output sources/agent-workflow-examples.drawio, then the official Draw.io CLI with FONTCONFIG_FILE=sources/fonts.conf. Exports use -x -f png/pdf/svg -e -b 0, PNG scale 2, PDF --crop. Build through experiments/scripts/paper/build_paper.sh. See review/VALIDATION.json and review/fonts.json for dimensions and final hashes.
