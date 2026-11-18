# Single-column, unequal-length agent workflows

The user requested one-column placement and less rigid alignment because agents can make different numbers of requests. Figure 1 now uses a standard figure at columnwidth, with stacked code-generation and deep-research panels. Both preserve four parallel agents, forward task/result edges and explicitly unfolded request/tool sequences.

Code branches contain 4/3/3/2 LLM requests; research branches contain 4/2/3/2. Request positions and endpoints are staggered; no global round boundary is drawn. Compact R1/R2 labels and short concrete tool names replace the wide repeated per-call descriptions. The coordinator merges generated code/test/doc artifacts before integration testing; the research coordinator synthesizes returned evidence. These are constructed examples, with no timing scale or claims about measured call-count frequencies.

Native Draw.io PNG/PDF, grayscale at the actual 84.67 mm column width, and manuscript pages 2 and 3 were visually inspected. Figure 1 appears at the top of page 2 right column beside the Background explanation. The figure height is 96.59 mm and its minimum text is 10.105 pt. Labels fit and all workflow paths move forward. Compilation succeeded, 22 pages; this is a scoped figure review, not a whole-paper submission audit.

Caption, accessibility description and Chinese companion match the variable request counts and single-column placement. Motivation text and all 23 protected other figure/TeX assets are unchanged from the before snapshot. Editable source, generator, fontconfig, native exports and before snapshots are retained here; paper/main.pdf is the canonical output.

Reproduce using sources/build_background_agent_examples.py --output sources/agent-workflow-examples.drawio, the official drawio-cli with FONTCONFIG_FILE=sources/fonts.conf (-x -f png/pdf/svg -e -b 0; PNG -s 2; PDF --crop), and experiments/scripts/paper/build_paper.sh. See review/VALIDATION.json for call counts, checks and source/PDF hashes.
