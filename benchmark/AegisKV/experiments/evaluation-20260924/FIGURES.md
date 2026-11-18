# AegisKV corrected Evaluation figures

The paper uses four figures and one co-primary latency table. Simulated WCT and offline native selection have distinct evidence classes. All 483 current simulation conditions are complete and audited; recovery plots use the common corrected runtime. Historical v1 plots remain in their original directories. Final manuscript render review is separate from these figure previews.

## Primary target-workflow delay

![Primary target workflow delay](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/evaluation-20260924/formal-core-v2-corrected/endpoints/figures/primary-target-wct.png)

[PDF](formal-core-v2-corrected/endpoints/figures/primary-target-wct.pdf) · [SVG](formal-core-v2-corrected/endpoints/figures/primary-target-wct.svg) · [data](formal-core-v2-corrected/endpoints/per-identity.csv) · [Agent latency table](reviews/coprimary-v2-crosscheck/AGENT_LATENCY_TABLE.md)

Each marker is one fixed failure identity at one model/load/policy condition, subtracting that policy's own healthy WCT for the same target workflow. S/N identify sink/non-sink targets. Horizontal offsets separate policies; there is no confidence interval. The interrupted Agent's latency is a separate co-primary endpoint and appears in a manuscript table.

Editable plot: [plot_primary_endpoints.py](../scripts/current_design/plot_primary_endpoints.py). Endpoint extraction: [analyze_primary_endpoints.py](../scripts/current_design/analyze_primary_endpoints.py). All-workflow aggregate and HBM-increment views remain supplementary.

## Constructed multi-call interventions

![Target workflow delay](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/evaluation-20260924/structural-campaign-v2-main/figures/structural-target-wct.png)

[PDF](structural-campaign-v2-main/figures/structural-target-wct.pdf) · [SVG](structural-campaign-v2-main/figures/structural-target-wct.svg) · [data](structural-campaign-v2-main/figures/wct-endpoints-per-run.csv) · [editable source](structural-campaign-v2-main/analysis_sources/plot_structural_campaign.py) · [review](structural-campaign-v2-main/figures/FIGURE_REVIEW.json)

135 conditions: five constructed scenarios, three token/length seeds, three policies, and healthy/prefill/decode interventions. Points retain every seed; gray segments join matched seeds, colored spans show ranges, and horizontal marks show means. These are not population confidence intervals. All eight workflows are also shown separately because the target and cohort conclusions can have opposite signs.

[All-workflow mean PDF](structural-campaign-v2-main/figures/structural-all-workflow-wct.pdf) · [recovery decomposition PDF](structural-campaign-v2-main/figures/structural-recovery-breakdown.pdf) · [seed-level adverse cases](structural-campaign-v2-main/PAPER_NUMBERS_V2.md)

## Resource sensitivity

![Resource sensitivity](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/evaluation-20260924/sensitivity-campaign-v2-corrected/figures/sensitivity-resources.png)

[PDF](sensitivity-campaign-v2-corrected/figures/sensitivity-resources.pdf) · [SVG](sensitivity-campaign-v2-corrected/figures/sensitivity-resources.svg) · [data](sensitivity-campaign-v2-corrected/figures/figure-data.csv) · [editable source](sensitivity-campaign-v2-corrected/figures/plot_corrected_sensitivity.py) · [review](sensitivity-campaign-v2-corrected/figures/FIGURE_REVIEW.json)

126 conditions on four complete held-out workflows, with one fault selected by input length before outcomes. Every point subtracts its own-condition F0; shared center conditions are not new repetitions. The main figure varies H2D, DRAM and HBM; [the supplementary controls](sensitivity-campaign-v2-corrected/figures/sensitivity-controls.pdf) preserve predictor/TTL/DMA/detection/tolerance/checkpoint results. Z64 changes forward partition as well as checkpoint interval. Healthy DMA cost and target/cohort break-even are in [the numeric report](reviews/PAPER_NUMBERS_V2.md).

## Native selection, independent of WCT

![Native coverage](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/evaluation-20260924/native-topk-warm/figures/native-topk-warm-coverage.png)

[PDF](native-topk-warm/figures/native-topk-warm-coverage.pdf) · [SVG](native-topk-warm/figures/native-topk-warm-coverage.svg) · [results](native-topk-warm/RESULTS.md) · [K16/K64 comparator numbers](reviews/native-topk-operating-point/RESULTS.md)

Three models each replay three PG19 documents with continuous history counters and immediate logical publication. K is a per-layer block budget; the plotted distinct-history denominator differs from repeated query–block events. Ranges are document ranges. The future oracle uses the same budget. These observations do not measure runtime cache hits or native-sparse WCT, and the K16 result does not support a few-miss premise.
