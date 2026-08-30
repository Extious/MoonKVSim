# AegisKV E2 figure assets

This directory documents a deterministic, standard-library SVG **limited E2
preview**, generated under its `generated/` child from a completed AegisKV
GlobalDES matrix. It is not the full MOONKVSIM_PLAN figure contract: provenance
sidecars and the list below name key unavailable dimensions. The generator does
not execute CUDA, Slurm, Mooncake services, network I/O, sleeps, or wall-clock
measurements. Every figure is **E2 modeled/preliminary**, **not calibrated**,
and **not a physical experiment or paper-ready result**.

Generate a set from a matrix bundle:

```bash
uv run python scripts/generate_aegiskv_e2_figures.py \
  --results /path/to/results.jsonl \
  --manifest /path/to/manifest.json \
  --representative /path/to/representative-run.json \
  --output-dir benchmark/AegisKV/experiments/figures/generated
```

The CLI uses that `generated/` child as its default. Keeping this README in the
parent directory lets the strict artifact auditor require an exact generated
bundle without treating documentation as an untracked result.

Existing generated targets are rejected by default. `--overwrite` is an
explicit replacement authorization; it does not weaken any evidence gate. A
complete bundle is written to a sibling staging directory and then published as
a directory-level replacement, with the set manifest written last in staging.

The canonical inputs are:

- `results.jsonl`: every row includes `run_id`, canonical payload SHA-256,
  suite/variant/cell identity, full variant parameters, and the E2 payload;
- matrix manifest: hash-locks `results.jsonl` and indexes every
  `run_id`/payload-hash pair;
- `representative-run.json`: binds one matrix row and carries its failure,
  recovery, transfer, Peer-HBM, Store DRAM, and span-detail records.

For every SVG, a sibling `*.provenance.json` records the three input hashes,
the SVG hash, evidence boundary, and every point's `run_id` plus result hash.
Each sidecar also records the SHA-256 of the loaded renderer source; the set
manifest hash-locks that sidecar.
The same binding is embedded on each graphical mark as SVG `data-*`
attributes. Resource timelines plot event boundaries; their peak values are
not reconstructed from coarse interval samples. F3 is limited to the Peer
protection pool and is not the plan's full per-GPU HBM account stack. F4 is
limited to the committed Store pool and is not the full per-segment DRAM
account stack. The generated `manifest.json`
hash-locks all 14 SVGs, all 14 provenance sidecars, and the F12 exclusion
sidecar. JSON artifacts use sorted-key compact canonical serialization with one
trailing newline. Its `status=PASS` means only that this limited artifact set
passed its generation contract; it does not mean full-plan, calibrated,
physical, formal, or paper-ready completion.

The generated set is:

- F1 system architecture design schematic, not proof that named production
  runtime components were instantiated by the study harness;
- F2 diagnostic GPU-failure recovery timeline; when the simulator has no explicit resume
  event, the final marker is the affected request's completion and is labeled
  as such (the whole-run end is never substituted). The execution/data-path
  fence is the runtime's immediate failure-time transition; detection is
  derived from the frozen schedule's delay before reroute/recovery. D2D/Store
  bounds are aggregate across the representative run because transfer records
  have no span IDs; zero-duration local Peer activation is not called a load;
- F3 per-GPU Peer protection-pool event-boundary occupancy only; weights,
  runtime, primary/reusable KV, reserve, staging, fragmentation, free, and
  unavailable accounts are not present in this input schema;
- F4 per-segment committed Store-pool event-boundary occupancy only; pending,
  evicting, staging, allocator metadata, fragmentation, and free accounts are
  not present in this input schema;
- F5 KV migration Gantt of transfer start-to-end intervals only; the current
  representative schema lacks reserve/queue/slice phases, aligned resource
  utilization, allocation/slice identifiers, and commit/abort status. If there
  are more than 40 records, display selection is round-robin by path/cause
  stratum and the selected records are then ordered by virtual time. Scheduled
  records may include canceled future reservations;
- F6 minimum-seed/repeat-A matched Vanilla-to-unified-AegisKV WCT/goodput
  diagnostic for the same bucket and failure scenario. The bucket is the
  failure-focus cell, while WCT/goodput are whole-workload metrics; no
  cross-seed estimate or confidence interval is claimed;
- F7 runtime `recovery_ready` ECDF across repeat-A per-run means (not raw
  request latencies). The metric is failure to `SILENT_REPLAY_COMPLETE`, not
  request resume/completion, and groups use the dominant modeled token source;
- F8 minimum-seed/repeat-A protection-coverage and recomputation diagnostic,
  without cross-seed statistics or confidence intervals;
- F9 minimum-seed/repeat-A policy-ablation WCT diagnostic, without cross-seed
  statistics or confidence intervals;
- F10 separate one-at-a-time Peer-HBM-per-GPU and global-Store budget axes,
  showing raw repeat-A points across seeds with deterministic display jitter;
  no confidence interval or physical benefit is claimed;
- F11 separate DP-count and Store-bandwidth axes, showing raw repeat-A points
  across seeds with deterministic display jitter. Store-node count is not
  parameterized and no confidence interval is claimed;
- F13 matched resource-cost decomposition in separate units; staging peak and
  recompute GPU time are unavailable, so recomputation is reported as tokens
  avoided only. Network/copy cost validity remains blocked by transfer
  cancellation accounting;
- F14 event-boundary peak versus time-weighted mean per-resource occupancy;
  p95 occupancy is unavailable in the canonical E2 payload;
- F15 real multi-agent trace coverage for 8K/32K/64K/96K/128K model
  contexts. Here 128K means one model context, never workflow-total tokens.
  These are source-reported 64-token hash-block buckets, not
  target-tokenizer-equivalent token IDs. Point provenance binds the frozen
  workload artifact hash/fingerprint. Until rows expose
  `workload_manifest_sha256` directly, it records only the suite-provenance
  hash declared by the matrix manifest; the three-input figure generator does
  not resolve that file and therefore does not claim a verified indirect
  workload-manifest binding. This is five-bucket span counting only: DAG size,
  fan-in/fan-out, concurrency, broader context-distribution summaries, and
  per-context HBM/Store/recovery/WCT overlays are unavailable.

F12 simulator accuracy is deliberately absent. The generator emits only
`f12-simulator-accuracy.excluded.json`: observed-versus-predicted accuracy
requires E3/E4 calibration or physical evidence, which this simulation-only
delivery does not have.
