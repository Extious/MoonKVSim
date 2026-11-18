# Background multi-agent examples

Added a full-width Figure 1 with (a) code generation and (b) deep research. Each subagent has its own conversation and an LLM/tool/next-call sequence. Code passes a patch to testing with a conditional revision loop; research forks into technical/cost investigations and joins their evidence. The examples are schematic and contain no measured duration, frequency, GPU placement or KV-transfer claim.

Native source: sources/agent-workflow-examples.drawio. Generator: experiments/scripts/paper/build_background_agent_examples.py. Native Draw.io PDF/PNG/SVG retain the source; paper assets are figures/agent-workflow-examples.pdf and figures/preview/agent-workflow-examples.png. sources/fonts.conf exposes the manuscript's installed Libertine fonts to the native exporter.

The first export fell back to DejaVu Sans and wrapped several labels. The corrected native export uses Libertine via fontconfig; the coordinator boxes were enlarged for two lines. Source text size is unchanged. Code/testing was revised from independent branches to a sequential patch dependency. Inspected the final native PNG, color/grayscale exports at 177.8 mm, and paper pages 2--4. Minimum figure text is 10.52 pt at insertion width. Chromium exports vector Type 3 font subsets, recorded in fonts.json; those subset labels do not identify the font family.

English and Chinese Background now explain both examples. Existing figure references advance by one: prior Motivation 1/2 become 2/3. All existing figure assets, Motivation data/captions/body and unrelated TeX sources are unchanged. Rebuilt canonical main.pdf; the final log reports no undefined references/citations or overfull boxes. It contains 22 pages. This is a figure/Background revision, not a full-paper submission review.

Re-export using the installed Draw.io CLI with FONTCONFIG_FILE set to sources/fonts.conf, -x -f pdf --crop -e -b 0 (or -f png -s 2), then run the repository build_paper.sh. See FIGURE_SPEC.md for primary sources and inspected style references; review/VALIDATION.json for scope and hashes; before/ for the preceding manuscript.
