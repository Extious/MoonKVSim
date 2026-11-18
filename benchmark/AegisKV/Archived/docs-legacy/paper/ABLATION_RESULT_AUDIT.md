> **Historical record — superseded for the revised paper.** This file describes
> the September 5 legacy-model campaign. Its results are excluded from the
> Mooncake-aligned manuscript. See `MOONCAKE_ALIGNMENT.md`, `COMPLETION_REPORT.md`
> and `data/aligned-statistics.json` for the revised study.

# Accepted ablation results

Checked 2026-09-05 after the independent 40-run acceptance became VALID.

Acceptance SHA-256: `c95043025c6d62be92f9fd0e3448cc45976017fca9efd337ceb444b7c7ba9065`.
Aggregate SHA-256: `158d577879603529ff42f2cdafcededd36fc28193d26c9d4658905cc147dfe1e`.

A separate arithmetic pass reconstructed all 20 seed/arm focus differences,
all 160-workflow mean differences per arm, conserving token fractions, and
physical protection-byte totals from the accepted per-run records. All match
the reported statistics (whole means round once to integer nanoseconds).

All effects below are ablation minus full after each arm's own F0 subtraction.
Positive favors full. Independent units are five paired admission seeds.

| Arm | Focus mean, s | 95% interval, s | Whole-workload mean, s | 95% interval, s | Seeds favoring full |
| --- | ---: | --- | ---: | --- | ---: |
| no_slack | 6.818496 | [-14.297893, 27.934885] | -0.072578 | [-0.184707, 0.039550] | 4/5 |
| lru_eviction | 7.376892 | [1.953367, 12.800416] | -0.111288 | [-0.425094, 0.202517] | 5/5 |
| no_aimd | 5.511293 | [-8.676441, 19.699027] | -0.132410 | [-0.559416, 0.294596] | 3/5 |

LRU replaces both retention scoring and its safe-tail lifecycle; this is a
retention-subsystem effect, not an isolated score effect. Its focus interval
excludes zero in this exploratory, unadjusted comparison. All whole-workload
intervals cross zero. Slack and AIMD increments remain uncertain.

| Arm | Mean F1 protection, GiB/run | Mean selected Peer+Store fraction, % |
| --- | ---: | ---: |
| full | 4723.585529 | 52.015307 |
| no_slack | 4952.408843 | 49.708189 |
| lru_eviction | 6192.002498 | 49.745993 |
| no_aimd | 4247.952539 | 52.015307 |

Full and no-AIMD have identical selected total coverage in each seed, but
the Peer/Store ownership can differ. Equal coverage is not equal routing,
batch composition, recovery timing, or a causal proof about AIMD.

Figure 6 now includes the accepted complete sensitivity study and the
accepted ablation evidence. The final composite and manuscript passed visual
and provenance review; see `COMPLETION_REPORT.md`.
