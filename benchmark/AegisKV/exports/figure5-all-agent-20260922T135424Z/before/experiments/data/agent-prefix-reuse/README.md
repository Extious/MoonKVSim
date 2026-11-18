# Agent-local prefix reuse for the Recovery-aware Router

This is an observational characterization of an existing trace, not a new
GPU experiment, a cache simulation, or a measurement of cache hits or WCT.

## Source and reproduction

Dataset: [SemiAnalysis CC Traces — Weka, with subagents](https://huggingface.co/datasets/semianalysisai/cc-traces-weka-062126).
The dataset README is preserved as `dataset-README.md`.

Original SGLSim artifacts are under:

```
/home/comp/zhanzhao/sglsim/AegisKV/doc/Archived/2026-08-06-pre-kvcache-centric/presentations/presentation/
  figures/data/measured/fig_real_trace_kv_reuse_scope.csv
  figures/png/fig_real_trace_kv_reuse_scope.png
  figures/scripts/render_real_trace_aegiskv_motivation.py
  experiments/sglsim_large/traces/cc-traces-weka-062126/traces.materialized.jsonl
```

The archived `traces.jsonl` symlink points to a missing temporary file;
the retained `traces.materialized.jsonl` is the input used for this audit.
`audit.json` records its SHA256, the script and CSV hashes, counts, and
whether the archived CSV was reproduced exactly. The original image,
analysis script, and CSV are copied here without changing their contents.

From the MoonKVSim repository root:

```sh
python3 benchmark/AegisKV/experiments/scripts/paper/analyze_agent_prefix_reuse.py
python3 benchmark/AegisKV/experiments/scripts/paper/render_agent_prefix_reuse.py
python3 benchmark/AegisKV/experiments/scripts/paper/render_draft_figures.py
sh benchmark/AegisKV/experiments/scripts/paper/build_paper.sh
```

The analysis first recomputes and checks `reuse-scope.csv`, then writes
`same-model-reuse-scope.csv` with an additional model-name equality filter.
The latter is the input for the manuscript figure. The archived script did
not check model equality; its percentages must not be silently relabeled
as model-compatible KV reuse.

## Definition

For every target request, eligible source requests must have completed
strictly before its arrival (`source.t + source.api_time < target.t`).
Sources and targets are compared only inside one workflow, because hash
IDs are trace-local. The new analysis also requires identical recorded
model names. The longest ordered input-prefix match is found separately
among (1) earlier requests of the same workflow-local Agent and (2) earlier
requests of other Agents in the workflow. Unordered token or block overlap
does not count. Generated output KV is not independently added to the
source prefix; only recorded source input-prefix blocks are available.

Each prefix block contributes 64 token proxies. The dataset's `in` field
is exactly this proxy count, rather than a tokenizer count. As documented
by the dataset, proxy counts can overestimate true prompt lengths. Within
each plotted group, counts are summed before division by summed target
input counts. These are token-weighted fractions, not the mean of request
fractions or equally weighted Agent/workflow averages.

The two plotted series **overlap and must not be added**. Additional
coverage from other Agents is computed separately for every request as
`max(0, other-agent prefix - same-agent prefix)` and then aggregated.
It is not the total other-Agent coverage and cannot be obtained by
subtracting the two aggregate bars.

The manuscript plots only `main_later` and `subagent_later`, labelled
`Main agent` and `Subagent`; the caption specifies follow-up requests.
These groups contain 56,405 and 40,332 requests, respectively. Initial
requests and the all-request aggregate remain in both unchanged CSVs,
but are not plotted. Agent IDs are instances within workflows, not
semantic roles shared across independent workflows.

## Scope of the conclusion

The figure supports treating same-Agent history as a useful locality
signal for normal dispatch, while preserving other-Agent prefix matching,
especially for the first request of a subagent. Model-name equality is a
necessary compatibility filter, not verification of weights, layout, or
physical residency. A real Router must query compatible live replicas and
consider queueing/load. There is no routing or eviction experiment here.
The figure does not establish optimal sticky routing, recovery-target
selection, failure protection benefits, or WCT improvement, and cannot
characterize same-role sharing across separate workflows.

No synthetic prompts, repeated workflows, failure injections, independent
hardware runs, or confidence intervals were added. The single-column
figure and its rendering manifest are in `exports/agent-prefix-reuse/`;
the Overleaf copy is `paper/figures/agent-prefix-reuse.pdf`.
