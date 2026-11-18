# Recovery-aware Router integration

Updated on 2026-09-20 following the user's request to merge normal routing and the former separate recovery manager.

The Router selects the source DP, preassigns the retry/Peer DP at arrival, publishes this target to KV Master, and reroutes after confirmed failure. Binding does not reserve HBM or initiate unconditional backups. KV Master owns tiers, per-request depths and blocks; Adapter owns capacity; Connector executes transfers. The DP0/DP1 mapping is illustrative, not an optimized routing result.

## Current artifacts

- `system-overview.drawio`: native editable source, with a separate Paper annotations layer.
- `system-overview.drawio.png`: official Draw.io export with embedded XML.
- `system-overview.drawio.pdf`: native vector PDF, published as `../../paper/figures/system-overview.pdf`.
- `MANIFEST.json`: generator/source/export provenance.
- `REVIEW.json` and `review/`: scoped content checks and actual exported previews.

The generator is `../../experiments/scripts/paper/build_system_overview_router.py`. Earlier v11 generators remain historical sources; this generator writes outside the Overleaf directory.

## Regeneration

From the MoonKVSim repository root:

```sh
python3 benchmark/AegisKV/experiments/scripts/paper/build_system_overview_router.py
/home/comp/zhanzhao/.codex/skills/drawio/scripts/drawio-cli -x -f png -e -b 0 -o benchmark/AegisKV/exports/system-overview-router/system-overview.drawio.png benchmark/AegisKV/exports/system-overview-router/system-overview.drawio
/home/comp/zhanzhao/.codex/skills/drawio/scripts/drawio-cli -x -f pdf -e --crop -b 0 -o benchmark/AegisKV/exports/system-overview-router/system-overview.drawio.pdf benchmark/AegisKV/exports/system-overview-router/system-overview.drawio
cp benchmark/AegisKV/exports/system-overview-router/system-overview.drawio.pdf benchmark/AegisKV/paper/figures/system-overview.pdf
python3 benchmark/AegisKV/experiments/scripts/paper/render_draft_figures.py
sh benchmark/AegisKV/experiments/scripts/paper/build_paper.sh
```

## Checked scope

The overview retains three ownership bands, symmetric DP capabilities, independent Peer/DRAM paths, and proportional single-column placement (approximately 84.65 x 76.25 mm). Minimum diagram text remains approximately 4.97 pt at that width, the inherited limitation of the user-selected dense layout. It is not a 10-pt figure. Native color, grayscale, and manuscript placement were inspected.

Section 3.4 now explains normal dispatch, recovery binding, failure activation, state resolution and retry submission. Checkpoint publication details are in 3.5; engine/Connector resource execution requirements are in 3.6. Abstract, overview caption, descriptions, Markdown and cross-references use the same ownership.

The compiled manuscript has 11 pages. No LaTeX errors, undefined references/citations or overfull boxes remain. Background and Motivation and all other figure bytes are unchanged. This update changes paper/design artifacts; no new system implementation or recovery experiments were performed.
