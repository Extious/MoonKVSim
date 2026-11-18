# Corrected post-hoc Slack mechanism: independent artifact review

Status: **PASS**, 2026-09-24 local date. This reviewer executed **zero simulations**.
Input: `../slack-mechanism-posthoc-v2-corrected`; authoritative machine-readable
evidence: `POSTHOC_SLACK_V2_INDEPENDENT_REVIEW.json`. Re-run with:

```sh
.venv/bin/python benchmark/AegisKV/experiments/evaluation-20260924/reviews/check_posthoc_slack_corrected.py --campaign benchmark/AegisKV/experiments/evaluation-20260924/slack-mechanism-posthoc-v2-corrected
```

The review independently checks 158 frozen source hashes; PLAN, protocol, workload,
profile, SEAL and all ten COMPLETE bindings; complete/exact replay/zero terminal
allocation/zero oracle reservation assertions; metadata-inclusive capacity
arithmetic; per-host occupancy and its integral recomputed from observed ledger
transitions. Source version is
`checkpoint-decay-hysteresis-incremental-g-20260924-eosfix1-causal-domain1-queued-history1`,
runtime SHA256 `de3a9ce7791218a74e8d50651c2ba1249b194e500eabc0fd9a91c52b978b8c5f`.
The new manifest correctly identifies GridDurationProfile and its AIC HYBRID
operator estimates; its profile metadata was matched directly to the frozen table.

The protocol/seal precedes execution according to the frozen control flow and local
filesystem timestamps. These timestamps are not independent external attestation.
Across the ten conditions, the only config differences are DRAM budget and
`slack_mode`; all HBM replicas are disabled, and compute/DMA interference is zero.

At 1.028336003 s in both tight zero-slack runs, A's committed CP1024 occupies
151,008,768 bytes. B's CP7936 plus pending next append occupies 1,208,177,280 bytes.
Their sum exceeds the 1,342,177,280-byte host budget by 17,008,768 bytes, and A is
retired. Retirement scanning is restricted to the interval preceding the failure,
including for F0; it does not accidentally count later capacity/EOS cleanup.

All five F1 runs fail the same A invocation at logical token1536 and wall time
6.255890594 s on worker0/host0. There are no other active co-victims, no displaced
queued Agents and no lost host DRAM. A new, independent Tracker initialized from
each frozen fault-entry frame reproduces every recorded guarded Slack and E score
without changing that frame: A's Slack is zero; B's is 80 s. The fault-entry
checkpoint remains A1280 under tight DAG versus only B8448 under tight zero.

| Condition | Corrected ΔWCT (ms) | Original v1 ΔWCT (ms) |
|---|---:|---:|
| 1.25 GiB DAG | 23.974643 | 24.045264 |
| 1.25 GiB zero | 134.793723 | 134.793723 |
| 4 GiB DAG | 23.974643 | 24.045264 |
| 4 GiB zero | 23.974643 | 24.045264 |
| Restart | 134.793723 | 134.793723 |

All F0 workflow/request endpoints, resource metrics and peak allocations are
unchanged. The tight DAG-versus-zero difference is now **110.819080 ms**. The
4 GiB contrast remains exactly null. The three checkpoint-backed F1 endpoints
decrease by 0.070621 ms under the corrected recovery model; there are no
`history_restores` in this single-call workload. This is not a correction factor
for other workloads or frozen versions.

The independently verified active recovery service-to-first-new-output interval
is 34.633161 ms for the DAG case, versus 145.452241 ms for tight zero/Restart.
Queueing is zero and detection takes 1 ms. In DAG, full restore completes at
6.262789374 s and first new output at 6.291523755 s. These are distinct milestones;
neither is EOS or workflow completion.

Both observer transparency cases passed byte checks on summary/config/failure
and on decompressed events/flows. Restart has no checkpoint DMA. The additional
tight DAG DRAM F1 case has 1,387 event rows (418,775 bytes) and 158 flow rows
(61,240 bytes). Its summary SHA256 is
`02937acdd944b1d0fc54fae32427ae2f6b50bd77d30fd8306405de3bd4c961c7`;
events SHA256 is `fd477dd6423042a6564a2dd1652eeed65521857707c2cbfa27e061de6fbc9434`;
flows SHA256 is `887f7716b14790315cf91cf3269c80790813353260cab41e18fcec8d7cc6e711`.
The base run used the same frozen source, and its separately hashed validation
extension preceded execution. There remain ten experiment samples plus two
validation executions. Observer journal instrumentation is expected to differ.

This is one constructed, manually parameterized post-hoc workflow and fixed
fault, with five dependent conditions. It supplies a modeled mechanism witness,
not a population estimate, hardware overhead measurement or predictor-accuracy
claim. The previous 32-run capacity/slack null remains preserved; this audit
rechecked its bound summaries and eight matched DAG/zero workflow equalities.
The FCFS batch-one model, synthetic metadata contents and replayed token outputs
retain their documented evidence limits. No original source, seal or result was
edited, and no old result is relabeled as a corrected-source result.
