# What the analytical figures compute

These figures are **declared model scenarios**, not empirical measurements, calibrated end-to-end simulation, or evidence that the DRAM/storage controller is implemented. Their purpose is to make the planned graphs and their scientific questions concrete before collecting measurements. All values come from `config.json` and `scripts/eurosys27/theory.py`; none is a hand-entered performance improvement.

## A. Static allocation and common-failure restoration

Four checkpoint groups contain 4/8/12/16 GiB. Each group belongs to one branch; the model has no shared-prefix deduplication and no partial-group admission. Remaining branch durations are 12/10/5/1 s. Size scale ∈ {0.5,1,2}; slack scale ∈ {0,0.3,1,3}; storage bandwidth ∈ {1,4,12} GiB/s. Their Cartesian product is 36 configurations, not experimental repeats. A constant shift makes all scaled remaining durations positive without changing their gaps. The base DRAM budget is 16 GiB and scales with size; storage is 160 GiB, sufficient for the largest 80 GiB state in this grid.

A common source failure makes all four requests recover together. The same deterministic target assignment (`request ID mod 2`) and scheduling rule apply to every policy. Each request submits 0.25 GiB chunks in chunk-major round-robin order. Dependencies are:

```
DRAM reader or storage reader -> shared NIC -> target H2D -> complete prefix -> tail replay
```

DRAM and storage readers are distinct shared resources. The NIC is common to both. Each target has its own H2D engine and compute engine. A ready operation starts at the later of its dependency completion and resource availability; globally choose the earliest feasible ready start, then stable submission ID. Resources are occupied non-preemptively for each bounded chunk. The floor is 0.25 s and replay is 0.4 s. Storage/NIC/H2D stages overlap across chunks; replay starts only after the whole request's prefix arrives. There is **no modeled layer-wise compute/transfer overlap**. A physically tuned baseline may therefore leave less room for tier-selection gains.

Rates: DRAM 20, storage 4, NIC 12, H2D 20 GiB/s. These are **assumptions**, not measurements of A100, NVMe, or the shared filesystem. The optional recompute path consumes 8 s/GiB in bounded chunks, also an assumption. The primary result figures do not compare against that assumed recompute speed, avoiding an easy but uncalibrated headline gain.

For branch residual durations d_i and recovery completion times r_i:

```
failure penalty F(P) = max_i(d_i + r_i(P)) - max_i(d_i).
```

This is an exact residual fork/join makespan in the declared scenario. It is not a general multi-workflow serving model. The healthy remaining work itself does not contend with other branches in this model, while recovery transport and tail replay do. It excludes foreground GPU batches, real model kernels, TP collectives, storage cache effects, controller execution cost, and spontaneous route changes.

Normal next-use identity has normalized weights 0.15/0.35/0.60/0.85. Within the exclusive next-use episode, the one selected request restores on an otherwise idle path, yielding U(P). The score is:

```
J(P) = 0.02 U(P) + 0.05 F(P).
```

The remainder is a no-event episode in a 60 s horizon. These probabilities are illustrative, not production failure rates. No migration cost is charged for this pre-failure **static placement** comparison; the dynamic manuscript objective includes migration. Thus the curve labeled “AegisKV model” does not execute Algorithm 1's transitions, profile uncertainty, rejection or hysteresis.

- LRU takes groups in reverse ID order (the declared recency history).
- Reuse-only takes descending next-use weight. It coincides with LRU here; no equivalence is asserted outside this scenario.
- AegisKV model repeatedly admits the feasible group with greatest positive marginal J reduction per GiB, re-evaluating all remaining candidates after each choice.
- No dependencies replaces estimated branch durations by equal values, leaving queues and bytes unchanged.
- No reuse value sets the normal-use weight to zero.
- Feasible oracle enumerates all 16 subsets of the same four groups within the same byte budget, then minimizes J. It cannot choose partial objects or change the scheduler. It is not an online/global optimality claim.
- All DRAM relaxes capacity. It is a reference, not a fair equal-resource policy, and is not asserted to lower-bound every mixed-tier schedule.

`scenario-results.csv` preserves each configuration, selected group IDs, absolute penalty, and objective. `summary.json` computes counts/means and worst regret from those rows. Current summary: AegisKV model improves on LRU in 17 scenarios, ties in 19, and is worse in zero; means 9.51759 vs 10.89213 s. The largest scalar objective regret versus the feasible oracle is 0.203889 s. Report these as properties of this grid, not a predicted production improvement or acceptance argument.

## B. Sensitivities

**Capacity frontier.** Sweep 0..40 GiB in 4 GiB steps; keep the base 40 GiB state and all rates fixed. Whole-group placement creates steps. Both endpoints are explicit controls.

**Storage path.** Sweep assumed storage rate .5..20 GiB/s. All rates include no additional filesystem cold-miss startup cost. “Storage” does not mean all these rates are realizable on the actual deployment.

**Duration perturbation.** Multiply alternating branch duration estimates by `(1+error)` and `(1-error)`, clamp to 0.01 s, and vary error from −100% to +100%. Evaluate selected placements using true durations. This is a causal sensitivity of a planner, not an empirical error distribution or a GBDT accuracy claim. The oracle and LRU ignore those perturbed estimates.

**Checkpoint lag.** Enumerate the ideal uniform phase N=0..Z−1 for Z=64/256/1024; use 100 generated tokens/s and 2.5 ms/token replay. Add 100×lag acknowledged tokens to the replay tail and use the exact phase mean. The mean is valid because this illustration assumes linear replay cost and fixed restore state. Nonlinear measured costs require statewise evaluation before aggregation. It does not model actual checkpoint queues, where the phase law and commit lag can differ.

**Ablation.** Average equally over 12 size/slack configurations at 4 GiB/s storage. Separate failure WCT penalty from normal next-use restoration. No error bars are generated. An objective-optimal oracle is not necessarily best on each individual component.

## C. Separate queueing and protocol illustrations

`healthy-io.csv` is a separate M/D/1 queueing model with 10 ms deterministic service quanta and independent Poisson foreground/backup arrivals. With total utilization ρ < 1:

```
mean response = 0.010 * (1 + ρ / (2 * (1−ρ))) seconds.
```

It illustrates nonlinear delay near saturation; it is **not** a measured TTFT curve, a claim about an actual bandwidth limiter, or output of the restore event calendar. Storage fairness, burstiness, I/O size variation, and feedback change real behavior.

`safe-demotion.csv` is a prescribed accounting timeline: DRAM target drops from 24 to 16 GiB at 1 s; an 8 GiB copy runs at 2 GiB/s; copy ends at 5 s; commit/redirect/drain finishes at 5.5 s; only then does physical DRAM fall. The exact 5.5 s transition is retained in the table. This is not a state-machine implementation test.

`common-fault.csv` is an algebraic counterexample: two critical branches take 10 s each to recover; placing each in DRAM reduces its recovery to 2 s. With 0/1/2 branches protected, summed local penalties are 20/12/4 s, but workflow delay is 10/10/2 s. It disproves identifying the sum with WCT; it does not establish the proposed heuristic's advantage.

## D. Permitted and impermissible claims

The figures support mechanism hypotheses, counterexamples, and reproducible numerical statements about this specified model. They do not establish a hardware rate, benchmark accuracy, realistic failure frequency, fault-safe implementation, learned prediction quality, negligible healthy overhead, end-to-end WCT speedup, or generalization to executable agent workloads. The manuscript says so in the abstract, Evaluation, captions, and conclusion. Filling measured tables later requires changing those statements and running the physical controls in `PROTOCOL.md`.

## E. Controller scaling placeholder

`controller-scaling.csv` assumes two DAG passes for each of eight profile episodes and each candidate plan, at **0.2 microseconds per node visit**. For V nodes and K candidates, the plotted estimate is `2 V K × 8 × 0.2 / 1000` milliseconds. It excludes serialization, locks, profile lookup, edges beyond the node-visit abstraction, and candidate construction; it is not a controller benchmark or a lower bound. Its purpose is to reserve the exact decision-time axes for E9 and expose that unrestricted evaluation can become expensive. Replace the assumed time with measured per-event latency at the same V/K points; preserve the units and campaign uncertainty. This chart does not establish that bounded candidate screening is already implemented.

## Expanded Evaluation models (2026-09-21)

The expanded generator is `expanded.py`; 33 figures use `plot_expanded.py` and `figure-specs.json`. The old static model remains unchanged. Evidence and source hashes are per table. All model outcomes have zero physical runs and no artificial confidence intervals.

**Single failure.** At fixed placement, exact fork/join delay is max(d_i+R_i)−max(d_i). Ordered attribution restores the floor, reader, network, H2D and replay costs in this order, evaluating the whole join each time; differences telescope. Initially free stages use 10^12 GiB/s as numerical zero. The order allocates interactions; it is not a unique physical causal decomposition. Total storage bytes and pool occupation max(R_i) are independent cost metrics.

**Queue externality.** A FIFO pool with two targets handles one four-branch recovery at a time; service S=max(R_i). For n simultaneous workflows, mean penalty is D+(n−1)S/2. For arbitrary arrivals a_i, q_i=max(0,q_(i−1)+S−(a_i−a_(i−1))). Completion penalty is q_i+D; the pool releases at arrival+q_i+S. This isolates the consequence of serial admission. It does not implement the proposed concurrent router or healthy workload scheduling. The fluid I/O backlog example has normal arrival rate .7B, initial recovery bytes V, and Q(t)=max(0,V−.3Bt), B=4GiB/s. Backlog is not TTFT.

**Trace.** Start/end timestamps are parsed as naive recorded civil times and converted relative to 1970 with no host-timezone dependence; no unrecorded timezone/DST correction is invented. Compute-only, positive-duration intervals are unioned per original system/node. Minute-resolution ties are resolved by node ID. The conditional recovery model consumes starts; end times only describe outages. Original systems have separate pools. One assumed four-branch active workflow per node interruption is an exposure assumption. The evenly spaced control preserves each system's count and first/last timestamp; compression divides within-system offsets by 10/100/1000, leaving service durations fixed. The original timeline is factor1. A timestamp-resolution control spreads equal-minute node starts over 59 seconds in node-ID order; this changes only within-minute timing and is explicitly constructed, not observed. This does not model full cluster unavailability or modern GPU failure rate. Raw redistribution/source discrepancy and Reflex semantic limits are documented in `EXPERIMENT_MATRIX.md`.

**Layer model.** Eight layers, one normalized selected payload per layer, DRAM capacity two payloads, bounded transient workspace for current/next layer. SSD4ms/payload, H2D1ms/payload, compute3ms/layer; selected-density multiplies both I/O costs equally for all variants. Early residency is layers0/1; late is6/7. Stage resources are independent serial servers. Layer l prefetch cannot start before GPU completion of l−2; unknown demand waits until l−1. Serial mode waits for l−1 even with a correct forecast. A wrong prefetch spends an extra SSD read, then the true demand arrives after reveal; false reads are discarded before necessary payload consumption. The first round(8×accuracy) layers have correct predictions: this ordering is a declared constructed sensitivity, not an empirical predictor. All true demand/compute stays fixed. The model excludes real bandwidth sharing, TP barriers, allocator fragmentation, native selector-specific metadata and replay-tail demand change.

**Rental model.** Eight equal-byte slots, 24 objects, 512 opportunities. At step t, value(i)=1.5+.8sin(t/18+.63i)+.35[ floor(i/8)=floor(t/64) mod3 ]. Candidate=(7t) mod24; next-use=(11t+floor(t/64)) mod24. Candidate revisit is the common causal credit-renewal opportunity. Direct revaluation chooses minimum current value; rent chooses minimum expiration, previews rent advancement and requires incoming credit to beat it. Both accept only current replacement gain > movement cost(.1)+hysteresis(.2 by default). Rejecting a preview does not advance committed rent. Accepted moves cost .1; missed next-use costs that object's current value. Renewal restores the revisited object's current value credit. No-hysteresis sets the margin to0; no-renewal skips credit refresh. This stream/value setup is a synthetic isolated heuristic test, not the complete nonadditive DAG controller, a competitive proof, or wall-clock serving cost.

**Amortization.** For one mutually exclusive failure episode in a horizon, expected net saving is p_f×2.0083333−C_h under the base isolated-case benefit. C_h=.01/.05/.2s is an assumed aggregate healthy-cost term in the same objective units, not measured per-request TTFT. Trace recurrence and correlated workloads require a richer objective; the simple formula is not used to estimate production reliability.
