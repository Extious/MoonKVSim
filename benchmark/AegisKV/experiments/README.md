# AegisKV experiments

This tree is the AegisKV paper experiment workspace. The three living inputs
are the only files under `configs/`:

- `configs/requests.json` — context window, frozen Weka workload, concurrency,
  and causal-replay arrival.
- `configs/failure.json` — first-release `GPU_FAILURE` only: fail-stop HBM
  loss, progress-based injection, detection/reroute, no repair.
- `configs/engine.json` — modeled hardware: Qwen3-8B, DP=8, 8x A100-40GB on
  one node, DRAM, and communication rates.

`scripts/` runs those configs through the MoonKVSim AegisKV library. New
publications install the three JSON files into `results/<group>/configs/` in
the same atomic rename as the matrix and bind their hashes in `manifest.json`.

`results/` holds one directory per published group plus `results/figures/`
for plotting scripts and paper-facing SVGs. `workloads/` is the frozen
117-span Weka subset referenced by `requests.json`.

The config directories attached to pre-layout releases are reconstructed
historical snapshots. Their values are checked against the result rows, but
their hashes are not retroactively part of the original manifests; the offline
auditor reports those as `reconstructed_unbound`. New releases must report
`manifest_bound`.

Run the current lock from the repository root (clean worktree required):

```bash
uv run python benchmark/AegisKV/experiments/scripts/run_aegiskv_e2_matrix.py \
  --suite core \
  --output-dir /tmp/aegiskv-e2-core

uv run python benchmark/AegisKV/experiments/results/figures/generate_aegiskv_e2_figures.py \
  --results /tmp/aegiskv-e2-core/results.jsonl \
  --manifest /tmp/aegiskv-e2-core/manifest.json \
  --representative /tmp/aegiskv-e2-core/representative-run.json \
  --output-dir benchmark/AegisKV/experiments/results/figures/generated
```

All outputs remain E2 modeled/preliminary and not calibrated.
