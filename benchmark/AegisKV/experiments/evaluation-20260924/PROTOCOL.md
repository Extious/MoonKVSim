# AegisKV Evaluation: protocol and completion gates

Status: latest-design regression is complete (74 checks). The corrected primary,
structural, sensitivity, capacity/Slack and post-hoc matrices have completed
and audited 180, 135, 126, 32 and ten conditions respectively. Resuming the three
interrupted primary conditions preserved the prior 177 accepted results.
Completed counts come from audits and per-run markers, never from plan size.
The manuscript before Evaluation is frozen by `PRESERVED_MANUSCRIPT.json`.

The original pre-run decisions below retain their v1 artifact references.
Matched v2 replacements share
`checkpoint-decay-hysteresis-incremental-g-20260924-eosfix1-causal-domain1-queued-history1`.
The replacement ledger is `reviews/RECOVERY_DOMAIN_RERUN_PLAN.md`; retained
manifests bind each source, workload, configuration and timing profile.
The 135 main structural conditions were rerun; the eight larger scale controls
remain historical v1 evidence. Broad study questions below are a design plan,
not a claim that every suggested control has been executed. The post-hoc
Slack competition diagnostic has its own prospectively sealed protocol and is
not part of the original primary fault bank.

## Scope and evidence

This study evaluates the current `paper/system_design.tex` through MoonKVSim's
shared-resource discrete-event simulator. No result will be labelled a physical
deployment, production overhead, native attention implementation, or a faithful
reproduction of another system unless the corresponding evidence exists.
The previous `current-design-20260923` campaign is retained as historical
mechanism evidence, not pooled into this evaluation.

## Implementation contract

- Fixed task-level Agent DAG; causal, asynchronous, versioned Tracker predictions;
  invocation boundaries and Slack updates trigger protection reconsideration.
- Agent protection uses full Peer DRAM and `E=[T_reconstruct-s]+ > lambda`;
  finite-capacity protection priority descends in E.
- KV blocks are 64 tokens; a checkpoint is 256 tokens. Counts use deduplicated
  per-query block touches, checkpoint-only decay and hysteresis, all-layer saved
  count state, and explicit selector metadata.
- Peer HBM covers Top-K blocks in the first L layers. Admission uses
  `G=[T_D-s]+-[T_H-s]+`; shrink removes increasing-G replicas. Adapter quota
  counts pending and committed bytes and protects foreground reservations.
- Recovery preserves committed TP shard barriers and fixed-output token counts,
  preempts prefetch for actual misses, and overlaps hit computation with miss
  transfer. Asynchronous checkpoint lag is measured rather than capped at Z.

The `eosfix1` repair introduced cancellation of unused restoration at accepted
EOS, callback fences, and invalidation of incomplete local history before
subsequent calls. The original frozen core/structural v1 campaigns retain their source
versions; their completed dense cases do not exercise this sparse EOS boundary.
The separate reproduction and regression results remain in `reviews/`, and
the post-repair sensitivity campaign froze that version explicitly.
The later common v2 runtime selects from the entire causal query domain before
separating checkpoint and recomputed tail KV, and restores compatible committed
histories for queued continuations. It records those history restorations
separately from active interrupted recoveries. This does not validate recovery
across unmodeled tool/think idle gaps.

## Input decisions

The retained frozen FanOutQA subset contains 160 of the source's 310 development
questions and explicit dependencies. The historical selection used task-ID
SHA-256 order, revision-pinned evidence and a whole-task 128K context guard;
its selection and rejection records remain bound in the source manifest.
Its evidence-provided prompts are constructed replay inputs and gold source
answers provide the fixed outputs; they are not sampled Qwen generations.
Every source span is a distinct task; repeated normalized role names do not
create a multi-invocation Agent. Exact prompt IDs and output-ID provenance must
be preserved by the adapter. The original DAG runs once, without repeated-round
amplification or first-round clipping.

The native-context cohort retains 74 complete workflows at a 40,960-token
guard. The predeclared workflow-ID hash split yields 12 training workflows
(95 tasks) and 62 evaluation workflows (503 tasks). No branch is independently
removed, no prompt is shortened, and all excluded workflow IDs remain listed.
FanOutQA reserves a declared 512-token output limit, never the actual eventual
output length. The 40,960-token guard is checked against this reservation too.

`formal-core-v1/PLAN.json` freezes 180 runs: two models (Qwen3-8B TP1,
Qwen3-32B TP4), three training-work-derived arrival levels (0.3/0.65/0.9),
five policies, and one F0 plus five F1 identities per condition. The fault bank
uses five equally spaced workflow positions in original source order;
alternating targets are sink and middle source tasks. This covers a known
completion bottleneck as well as branches; it is not a random-time failure
sample. The two-workflow implementation pilot showed that faster recovery can
leave WCT unchanged on a hidden branch, motivating explicit topology coverage
before the formal matrix was frozen. No formal outcome selected these targets.

The length-based predictor uses current prompt work plus a training-only median
output length per role. Unstarted Agents use training role-duration priors;
guard is the training absolute-residual 90th percentile. These are controlled
modeled-service proxies, not real whole-Agent wall-time prediction validation.
L is chosen by the written bandwidth rule using median training context and a
uniform layer split of the offline profile; K=16 is predeclared. Model geometry,
operator-table sources and actual L/guard values are frozen with each campaign.

`structural-campaign-v1/` freezes 143 separate constructed runs, including
multi-call histories, long decode, skew/balanced DAGs and host failures, with
8/32/128 workflow controls. Its phase-relative prefill/decode targets are
distinct logical locations, not the same total-token-progress experiment.
These runs are not extra natural-trace samples. Native sparse traces form a
separate selection diagnostic, with three source documents per model.

Observed multi-call episodes may support separate Agent history/Tracker tests.
Time-inferred edges cannot support claims about a known cross-Agent DAG.
Qwen timing uses pinned AIConfigurator HYBRID operator estimates, bounded
prefix/extend interpolation and sequential decode steps. It is not a calibrated
end-to-end latency model. The foreground scheduler is FCFS with one invocation
per DP. Production throughput, continuous-batching behavior and zero physical
overhead remain unsupported by these campaigns.
Unavailable native selection traces must not be replaced by a fixture presented
as a native sparse model. Synthetic selector sensitivity is explicitly labelled.

## Study questions and controls

1. End-to-end recovery: whole-workflow completion time, faulted-workflow WCT,
   healthy collateral WCT, p50/p95/p99, makespan, and failure-to-first-new-token
   decomposition (detection, queue, service).
2. Resource trade-off: checkpoint traffic, actual completed/cancelled bytes,
   peak physical per-rank HBM and shared per-host DRAM, pending replicas,
   checkpoint lag, and additional H2D work.
3. Mechanism attribution: restart; full DRAM with identical checkpoint/routing;
   all-Agent DRAM; static HBM; no Slack; no HBM; no hysteresis/decay; constrained
   quotas; and admission alternatives where meaningfully supported.
4. Robustness: load and scale, failure stage and host/worker scope, finite DRAM,
   H2D/network speeds, prediction error/staleness, lambda, K/L, and quota control.
5. Healthy service: report configured compute/DMA interference separately from
   omitted costs. Zero modeled overhead cannot establish physical zero overhead.

All policies share original workflow identities/order, model cost, routing
rules except the explicitly ablated mechanism, hardware byte budgets, and the
same Agent/call/logical-progress failure. F0/F1 are paired for every policy.
The primary 80% logical trigger is supplemented by early/late progress, with
unreachable targets reported explicitly. Seeds describe the precise randomized
factor, not automatically independent workloads or repeated physical trials.
Effect intervals use the actual sampling unit; deterministic reruns are not
additional statistical samples. Negative outcomes, exclusions, failure cases,
and all planned cells remain visible in the artifact.

## Completion gates

- Latest design conformance tests and independent byte/time/barrier audit pass.
- Inputs, model costs, code and configs are hashed; every plotted number has a
  completed run and an unambiguous unit/denominator.
- A frozen experiment matrix and source snapshot precede formal runs. Smoke
  runs are labelled separately and do not silently become final samples.
- Editable Matplotlib sources, tables, PDF and PNG exports are retained;
  figures are checked at actual insertion width and in grayscale, with at
  least 10 pt final text for EuroSys.
- `paper/evaluation.tex` is included, canonical build passes, earlier chapter
  and figure hashes match, and the actual combined PDF is reviewed.
- Cursor Agent is invoked with `claude-opus-5-5-max`; review input hashes,
  raw outputs, findings and resolutions are retained. Model agreement is a
  review outcome, not a guarantee of acceptance. Any unresolved material
  objection keeps the overall goal incomplete.
