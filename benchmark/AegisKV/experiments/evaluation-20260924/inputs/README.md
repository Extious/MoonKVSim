# Evaluation inputs, verified 2026-09-24

## FanOutQA task DAGs

`fanoutqa-bundle.json` binds the frozen 160-workflow, 1,304-invocation
Evidence-Provided FanOutQA dev workload by SHA-256. `fanoutqa-agent-tasks.jsonl`
stores a compact per-invocation mapping to exact prompt IDs in the original
128 MiB JSONL, plus recovered output IDs. The public original 310-task dev
source was freshly retrieved at revision
`989f4c40d9deea1ecb0897d7a17a9c0fe20d5c33` and its SHA-256 matches the original
preparation manifest. The source file is retained in `source/`.

Human questions, decomposition/depends_on edges, evidence revisions and answers
are source data. The evidence-provided prompts and final aggregation node are
constructed serving inputs, not recorded Agent execution. All 26,760,371 prompt
token IDs are preserved; all 17,936 output token IDs were recovered by encoding
the original answers with the pinned Qwen3 tokenizer and checked against the
frozen output counts. No token ID is invented, clipped or padded.

Each source subquestion/final span maps to one Agent task with one invocation.
The old normalizer's `fanout-root` agent label was shared by separate aggregation
tasks in 17 workflows; merging those tasks would change dependencies. This
adapter retains all 2,061 explicit edges and does not claim within-Agent
multi-invocation history from this corpus. Source timestamps are modeled values
and are not imported as service time, arrivals, labels or duration priors.

`fanoutqa-native-40960-selection.json` records the predetermined whole-workflow
context guard. It keeps 74 workflows/598 calls and excludes 86 complete workflows.
Of the excluded calls, 205 exceed 40,960 themselves and 501 otherwise-valid calls
remain excluded with their workflow; no branch is removed in isolation.

| Cohort | Workflows | Calls | Context p50 | Context p95 | Context max |
|---|---:|---:|---:|---:|---:|
| Frozen full source | 160 | 1,304 | 16,438 | 55,274 | 86,214 |
| Whole-workflow native guard | 74 | 598 | 10,205 | 33,208 | 40,150 |

Context includes prompt plus fixed output, with nearest-rank quantiles. Outputs
are short: p50=5, p95=58, max=420 tokens. The 80% total-token failure trigger may
therefore occur during prefill; it must not be described as uniformly sampled
decode failure.

`fanoutqa-workflow-split.json` uses only workflow identity:
`int(sha256(workflow_id.encode()).hexdigest(), 16) % 5 == 0` selects training;
all other IDs select evaluation. Source order is retained. The resulting counts
are 28/132 full train/evaluation workflows and 12/62 native train/evaluation
workflows (95/503 native calls). The long-context evaluation set has 70 workflows.
The imbalance from exactly 20% is retained rather than changing the rule.

Qwen3-8B revision `b968826d9c46dd6066d109eabc6255188de91218` and Qwen3-32B revision
`9216db5781bf21249d130ec9da846c4624c16137` have byte-identical pinned tokenizer
files in the retained equivalence audit. The adapter permits this mapping only.
It does not transfer service time or imply tokenizer equivalence to other models.
Contexts above 40,960 require an explicitly labeled context-extension shape
study; this conversion is not a model quality validation.

```python
from pathlib import Path
import json
from moonkvsim.aegiskv.evaluation_workload import load_fanoutqa_agents

p = Path("benchmark/AegisKV/experiments/evaluation-20260924/inputs")
split = json.loads((p / "fanoutqa-workflow-split.json").read_text())
agents = load_fanoutqa_agents(
    p / "fanoutqa-bundle.json",
    workflow_ids=split["native_eval_ids"],
    max_context_tokens=40960,
    target_model="Qwen/Qwen3-32B",
    prior_ns=10_000_000_000,  # Explicit fallback; supply train-only priors in a study.
)
```

The loader verifies bound source hashes, refuses duplicate workflows, rejects an
unverified model tokenizer, and fails if any selected workflow exceeds context.
Load once and cache per-workflow tuples when running many configurations.

## Weka real Agent episodes

The original public Claude Code proxy trace was rehashed in this audit:
1,847,151,435 bytes, SHA-256
`29b6a19e751ff5230771519aab755f80a0f43a4ba9cf96b72d3a6a437ec99276`, matching pinned
Hugging Face revision `23f152f6f0f9399a85901b89a6458def0ef16729`.
Its 393 sessions contain 98,827 calls. It exposes workflow-local 64-token hash
blocks, not exact Qwen tokens; cross-Agent dependencies in the existing
normalization are time inferred. It is not a source-observed fixed Agent-task DAG.

The existing clock-consistent complete-subagent extraction contains 1,688
episodes, 41,854 calls and 174 source workflows. `weka-episode-index.jsonl` and
`weka-episode-audit.json` bind that source and preserve all signed inter-call gaps
and model sequences. There are 509 episodes with overlapping requests and 333
with source-model switches. Never clamp negative gaps, silently serialize these
calls, or assume their KV histories are compatible across model changes.
Gaps include observed tools/application/scheduling time, not measured tool time.
These inputs support a real single-Agent/Tracker diagnostic; using them as full
workflow WCT evidence would require stronger dependency information.

## Other public application families

`source/nvidia-odr-availability.json` records a fresh complete GitHub tree audit
of NVIDIA/TensorRT-LLM revision `4871aae1131fbe319bece48695e7aad23dacc762`.
The trace replay README and tech blog are retained with SHA-256. The tree
contains replay/collection code and one Coder JSON example; the 100 Open Deep
Research trace files are not published in that checked tree or linked document
set. The public methodology is useful, but its reported 100 tasks cannot be
counted as available inputs. The single Coder example is insufficient for an
independent application-family distribution. No ODR data is synthesized here.

## Local model cost evidence

The existing `configs/aiconfigurator/qwen3-8b-l40s-native-40960/` files are a
calibration shape plan/reducer specification, not a completed calibration.
The old Qwen3-8B FanOutQA times are an uncalibrated linear token model; the old
Qwen3-32B times are an explicitly uncalibrated TP4 roofline model. Neither is a
calibrated simulator merely because exact token IDs are available.

Under `experiments/data/`, `recompute-aiconfigurator-a100` contains static HYBRID
and SOL shape estimates for Qwen3-8B/30B-A3B. The various
`reuse-aiconfigurator-*` folders contain pinned model configs, SDK versions,
query shapes, operator estimates and provenance; the current H100 family covers
Qwen3-14B, Llama-3.1-70B, Qwen3-235B-A22B and DeepSeek-V3.2. These are static
performance estimates with declared extrapolation, not end-to-end calibration.
Existing Qwen2.5-7B-Instruct-1M physical recovery measurements use a different
model/runtime and do not calibrate Qwen3-8B/32B or native sparse recovery.
The current evaluation's separate duration profile builder owns any new profile.

## Native sparse selector diagnostic

`native-heldout-selector-manifest.json` and
`native-heldout-selector-windows.npz` bind 288 model/document/layer incidence
arrays from existing native NOSA-8B, NSA-8B and MiniCPM4.1-8B recordings.
Each array is a boolean `[768 query positions, 508 physical 64-token blocks]`
matrix spanning absolute queries `[31744,32512)`, with selections deduplicated
across the two KV groups. Native sink/local selections remain present.

The three models use identical first 32,704 input IDs on three PG19 documents.
NOSA's `cis_pooling` requires total length strictly below 32,768; the preserved
32,704-token run meets that bound. For all 96 NOSA layer/document arrays, native
packed masks over the entire extracted range were reconstructed from selected
indices and matched exactly. NSA/MiniCPM capture metadata verifies the selected
indices were passed to their native sparse kernels. Recorded weights/configs,
observer checks and source hashes are retained by the separate analysis audit.

The causal Top-K study is in `../native-topk/`; its README defines held-out
windows, checkpoint decay/hysteresis, counter initialization, same-byte baselines
and the three-document statistical unit. It reports block coverage and logical
raw-KV byte footprints, not GPU transfers, recovery correctness, latency or WCT.
