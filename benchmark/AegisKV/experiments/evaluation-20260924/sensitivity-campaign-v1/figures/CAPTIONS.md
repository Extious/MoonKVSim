# Sensitivity figure captions and selection

Both figures use the prespecified target workflow's **F1 WCT minus its own
condition/policy F0 WCT**, in seconds. They do not average the four workflows or
represent a population of failure times. There is one fixed length-selected
fault identity; no error bars or confidence intervals are drawn. All four
workflow outcomes, including 31 negative collateral deltas, remain in the CSVs.

PDF, PNG, editable SVG and `plot_sensitivity_campaign.py` are retained.
Insert at **178 mm / 7.007874 inches** to preserve the verified Linux Libertine
10.3 pt labels. These are full-text-width figures and must not be scaled into a
single 84.7 mm column. Resource height is 2.60 inches; control height is 4.65.
The resource figure is the compact primary candidate. The complete controls
figure can remain an external diagnostic if manuscript space is limited.

## Resource sensitivity

**Suggested caption.** Resource sensitivity of one fixed prefill failure.
Four complete FanOutQA heldout workflows execute once, with Qwen3-8B TP1/DP8
profile-informed timing and fixed training priors. The target is the
longest-prompt Agent in the third workflow, interrupted at 80% total-token
progress. Each point is the target workflow's F1 completion time minus its own
condition/policy F0. Panels vary H2D bandwidth, Peer DRAM per host, and replica
HBM cap per rank. Other settings, including L=11 and K=16, stay fixed; initial
HBM quota is min(128 MiB, cap). The vertical axis is logarithmic (0.01--3 s).
H2D bandwidth and DRAM capacity use log2 horizontal axes. HBM capacity uses
a symlog axis, linear from 0 to 32 MiB and log2 above 32 MiB. This is one
prespecified fault intervention, not independent sampling of failure times.

The DRAM sweep is demonstrably capacity-binding: at 0.25 and 1 GiB, peak single
host use is 0.24614 and 0.98455 GiB, the target has no surviving checkpoint at
failure, and both backup policies return to the restart penalty of 1.80231 s.
At the 256 GiB center, DRAM/AegisKV penalties are 0.060982/0.059538 s; the
additional HBM reduction is only **1.444 ms**. With HBM cap 0 or 32 MiB, AegisKV
equals DRAM for this outcome. Near-coincident curves are intentionally retained.
Peak use/reselections are recorded; there is no complete master-denial counter.

## Prediction and protocol controls

**Suggested caption.** Sensitivity to online prediction scale, delayed
prediction replies, modeled DMA/compute interference, detection delay,
protection tolerance, and checkpoint interval. The workload, target failure,
and own-policy F0 subtraction match the resource figure. The delay pair has its
own TTL=100 ms control and compares 0.1 versus 200 ms replies; other panels use
the central configuration. At Z=64 the runtime also splits prefill forwards
into at most 64 tokens, while Z=1024 retains the 256-token compute chunk.
Thus the interval panel changes compute chunking and checkpoint/decay cadence
together. All control panels share a logarithmic vertical axis (0.01--30 s);
no population inference
is made from this single failure identity.

Prediction multipliers 0.5/1/2, the TTL pair and tested tolerance levels do not
change the target penalty here. All 52 replies in the 200 ms condition exceed
the 100 ms TTL, versus zero at 0.1 ms; accepted publication does not mean the
reply was valid for Slack. These unchanged outcomes are not evidence that
predictions are accurate or that staleness never matters.

The modeled slowdown intervention slightly reduces F1-minus-F0 penalty because
the subtraction includes a separately slowed healthy run. This is not a claim
that adding interference speeds up recovery. Absolute F0/F1 WCT and slowdown
counters remain in the underlying tables. The large Z=64 restart penalty must
be read with its compute-chunk coupling, not attributed solely to backup traffic.

## Provenance and review

The 126 jobs and sources are sealed in the parent directory. This figure rechecks
each of its 84 plotted values against the raw F0/F1 target workflow summaries;
reused central points are explicit aliases of the same run. The campaign uses
the EOS-fix1 snapshot and dense model profiles, and does not execute GPUs or
claim integrated physical calibration. Actual PNG and native-width PDF color/
grayscale exports are recorded in `FIGURE_REVIEW.json`; final compiled-paper
placement remains the parent task's last check.
