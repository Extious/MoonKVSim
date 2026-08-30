# AegisKV GlobalDES Store-transport v1 preliminary report

## Evidence boundary

This is an **E2 modeled/preliminary**, **not calibrated** CPU metadata-only
simulation. It does not execute CUDA, model inference, a physical network,
Mooncake services, Slurm, sleeps, or wall-clock performance measurement. The
rates below are explicit assumptions, not measured hardware properties.

## Frozen matrix

- implementation commit: `a91a47e63341f961db1ceb4a1bcef2eaa980a2da`
- implementation tree: `78de905003113aade1d9471a014771ddca59b718`
- variants: `RDMA_GDR`, `RDMA_HOST_STAGED`, `TCP_HOST_STAGED`
- modeled rates: Store RDMA 25 GB/s, Host staging 16 GB/s, Store TCP 8 GB/s
- context buckets: 8K, 32K, 64K, 96K, 128K
- scenarios: `no_failure`, `GPU_FAILURE`
- independent seeds: 0 and 1
- deterministic repetitions: fresh A and B GlobalDES instances
- result rows: 120
- exact A/B pairs: 60
- shared logical failure schedules: 10
- only fault type: `GPU_FAILURE`

All three paths use explicit sliced fluid flows. Host-staged paths acquire and
release a per-GPU Host DRAM staging transaction and hold a source pin until the
flow reaches a terminal state. GDR cannot silently charge Host staging. Every
run finishes with zero live source pins and zero Host staging bytes.

Publication identity:

- matrix manifest fingerprint:
  `355f742cab8a8cc231c89f0f8f5a0e8b932138405553da612da0527311e2d48e`
- matrix manifest SHA-256:
  `77e207149da4b14c28419011b6ab07d86f4c533b1fe0f585450c8733fd341ca2`
- results SHA-256:
  `f6c9dc1e5397bded18bb7d9b945c06bfcae3e0b67e008d43e3e8783f991002f1`
- statistics SHA-256:
  `d3525b29b98f0450400113443e95a01c755e57b15219a497f692b5ca416a0e66`
- representative-run SHA-256:
  `2fe70108e2a4bda69c1aeaae3de4843834942b66ad5477528259f5eb9f751197`

## Preliminary result snapshot

The table reports two-seed repeat-A means for matched `GPU_FAILURE` cells. WCT
is the whole two-workflow completion time. Positive WCT delta means slower than
the same-bucket, same-seed GDR baseline. The network column is modeled
transferred-byte × service-time, not physical traffic or energy.

| Bucket | RDMA staged WCT delta | TCP staged WCT delta | RDMA network multiplier | TCP network multiplier |
|---|---:|---:|---:|---:|
| 8K | +0.0224% | +0.0542% | 1.473x | 2.791x |
| 32K | +0.0224% | +0.0262% | 1.482x | 2.825x |
| 64K | +0.0234% | +0.0652% | 1.469x | 2.773x |
| 96K | +0.0248% | +0.0480% | 1.480x | 2.839x |
| 128K | +0.0230% | +0.0705% | 1.491x | 2.858x |

The end-to-end deltas are small because this workload's whole-workload WCT is
dominated by modeled forward time, while the path-local resource cost changes
substantially. The result does **not** establish a general GDR/RDMA/TCP hardware
ordering. In particular, the TCP 32K seed range is -0.0146% to +0.0671%, so
even the sign is unstable in that cell. Recovery latency is unchanged in four
of five bucket means; the 128K difference is seed-dependent. No blanket
recovery-latency conclusion is supported.

Peak Host DRAM staging is 0 for GDR and 1.125 GiB for both Host-staged paths in
the 128K failure cells. That is a slice-buffer capacity charge, not a second KV
payload charge. All Host ledgers conserve capacity at every event boundary and
return `TRANSFER_STAGING` to zero.

## Figure F17

`figures/e2-transport-v1/f17-store-transport-sensitivity.svg` contains:

1. whole-workload WCT delta versus matched GDR;
2. modeled network byte-time multiplier versus matched GDR;
3. peak Host DRAM staging.

Whiskers are the seed-0/1 range. Repeat B is used only for byte-exact
determinism and is never treated as an independent sample. Every plotted point
embeds its run IDs and payload hashes.

- figure SHA-256:
  `8b3ce5980d12b6568d21880d39840b092fda79e0c3a49ddd0c3b261a451c847d`
- figure manifest SHA-256:
  `2946af900e7b36a98d64fd8798fcdba92e99b6ace8848b2dfb568f09e5c6d1aa`
- offline audit: PASS, 120 rows, 60 pairs, 1 figure,
  `physical_execution=false`, `slurm_used=false`

## Remaining limitations

- two seeds are insufficient for a stable inferential claim;
- rates are modeled assumptions and are not calibrated to a physical platform;
- Store-node count and TP/PP topology remain unparameterized;
- primary KV layout remains the declared Qwen3-8B TP1/PP1 source-derived layout;
- source hash-block coverage is not tokenizer-equivalent 128K evidence;
- F12 simulator accuracy remains intentionally unavailable;
- this focused matrix does not replace the v1 full ablation/sensitivity matrix
  or the v2 seven-system fluid core matrix.
