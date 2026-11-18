You are Claude Opus 5.5. Solve this in the repository /home/comp/zhanzhao/MoonKVSim. You may edit files, add tests, and run simulations. Do not git commit, do not push, do not change git config. Do not switch models. If the session cannot run commands, stop and say so.

The user asked, in Chinese, to hand you this task and to produce a very complete Evaluation section. The defect they just identified: the paper has only internal ablations (restart, All-DRAM, DRAM, Static-HBM, AegisKV). There is no external baseline. A EuroSys/OSDI/SOSP reviewer will challenge that, because the only positive result is DRAM checkpoint-and-replay versus restart, which Related Work already credits to prior systems. Later PAPER-READY reviews do not close this hole. Those reviews were told not to demand new experiments once sentences matched artifacts.

Read the current manuscript before designing anything. system_design.tex and motivation.tex have been edited since earlier reviews. The design now includes a Router that places the checkpoint at a retry target chosen from load, free memory, and copy-path contention. The simulator in python/moonkvsim/aegiskv/current/runtime.py does not necessarily implement that sentence. Do not rewrite System Design or Motivation except to correct a sentence that your new evidence would make false. Do not clobber in-progress design prose.

## What to deliver

A revised Evaluation that a reviewer can read as complete experimental support for the paper's actual claim, plus the minimum code, tests, and new runs that make the external-baseline comparison real. Update abstract, introduction, related work, and conclusion only so they stay consistent with the new evidence. Rebuild paper/main.pdf.

Every number in the paper must come from an artifact you ran or from an already sealed artifact you re-checked. Do not invent numbers. Do not drop adverse or null results. Do not search for a load, budget, or fault that makes AegisKV win. Predeclare the campaign in a PROTOCOL.json before any run in that directory, and refuse to start if an existing protocol differs.

## External baselines

Specify them as modeled policies on this same runtime. Do not label any of them a reproduction of DéjàVu, LUMEN, or GhostServe. The serving setup is data-parallel workers, not DéjàVu's pipeline of generative replicas, and this simulator has no draft-assisted progressive recovery. Say that in the paper.

Implement these as new opt-in policies. Existing policies none, all_dram, dram, static_hbm, and aegiskv must stay byte-identical when the new knobs are off. Add a test that says so. Use python3.11. System python3.8 cannot import this package.

1. fixed_checkpoint. Complete DRAM checkpoints for every eligible Agent, same checkpoint chunk Z, no slack threshold, no exposure ordering, no Top-K HBM, no quota growth. Placement and retry use the same rule you implement for the external policies, and that rule must not read slack, E, or G. This is the modeled fixed checkpoint-and-replay baseline. It is not All-DRAM: All-DRAM still ranks by exposure. It is not DéjàVu and not LUMEN Fixed-Checkpointing.

2. load_aware_checkpoint. Same complete-DRAM, no-slack protection as fixed_checkpoint, but the checkpoint holder and the failure retry target are chosen from current queue length, whether the worker is busy, and remaining host DRAM, and the holder must sit outside the execution worker's failure domain. No draft speculation, no progressive token recovery, no change to the foreground FCFS scheduler. Call it a modeled load-aware checkpoint and retry policy. It is not LUMEN. If the current AegisKV path already selects peers that way, do not pretend this baseline is AegisKV; keep AegisKV's selection (slack, Top-K, quota) on its existing path, and let this baseline checkpoint everyone under the load-aware rule.

3. tail_shadow. A lightweight partial copy: only the latest committed checkpoint chunk of at most Z tokens, not a full-prefix checkpoint and not Top-K HBM. Same placement rule as fixed_checkpoint. Call it a modeled tail shadow. It is not GhostServe. Do not add GhostServe mechanisms you cannot point to in benchmark/AegisKV/experiments/evaluation-20260924/LITERATURE_AND_DESIGN.md or the local paper text.

Write the three rules into the protocol in enough detail that a reader can see they were not fit to the outcomes.

## Runs

New directory: benchmark/AegisKV/experiments/evaluation-20260924/external-baseline-v1/. Do not modify sealed walltime-primary-v3 artifacts or mechanism-decision-v1 artifacts.

Clone workload, arrivals, profiles, predictor, and the five fault identities from walltime-primary-v3 (Qwen3-8B and Qwen3-32B, loads 0.3, 0.65, 0.9, F0 plus five faults). Parent F0 fault_index is -1, not null.

Run the three new policies on that full matrix: 2 models × 3 loads × 6 (F0+5) × 3 policies = 108 jobs. The host has 128 cores and about 2 TB RAM; load is low. A previous 8B ρ=0.9 run took about 420 seconds. Use AEGISKV_WORKERS around 12 to 16. Resume cleanly: skip runs that already have COMPLETE.json, and raise if a directory is incomplete rather than overwriting it.

Before citing sealed primary numbers next to these new runs, replay one sealed primary job (Qwen3-8B, load 0.9, policy dram, one F0) with the unmodified policy and require the same workflow WCT. If it does not match, re-run none, all_dram, dram, and aegiskv inside this campaign for every cell you compare, and compare only within the campaign. Record the smoke result in the protocol directory.

Primary host DRAM cap stays 256 GiB. Do not turn this into the 8 GiB binding campaign. compute_dma_slowdown stays 0 on this campaign, and the paper must keep saying that this comparison does not charge backup traffic. The binding-budget result already in the paper stays as a separate cell; do not replace it with these runs.

## Paper

Rewrite Evaluation so it contains, in this order, and so each claim is one a reviewer can check:

- The question, split into the prior-system question (complete or partial checkpoint-and-replay versus restart, under a placement rule that does not use workflow slack) and the AegisKV question (slack selection, Top-K×L, quota, beyond that checkpoint baseline).
- Why the five old arms are internal ablations and why the three new arms are external modeled policies, including the mechanisms you did not port.
- The methodology that is still true: uncalibrated AIConfigurator A100-SXM profiles, FCFS, one active invocation per worker, constructed FanOutQA, hashed-text predictor versus the older service-proxy campaigns, paired F0/F1, target versus agent versus all-workflow endpoints, dependent workflows, no confidence intervals.
- Results for the new policies, with the same endpoints as the primary. Keep negative and null cells. If fixed checkpointing matches All-DRAM, say they match and report the protected-set difference. If load-aware routing changes workers and makes some workflows slower, report that.
- The existing primary, HBM, quota, native-selector, and binding-budget results, corrected rather than deleted. Do not restore any false sentence that earlier reviews removed. In particular: Peer DRAM does not bind in the primary; on 8B the Peer-HBM quota does bind and grows to 192–256 MiB; Static-HBM and AegisKV workflow completion match on the sealed pairs; the slack threshold omits at most two of All-DRAM's 498 checkpointed Agents in the primary and none in the binding cell; the 0.902 s healthy-mean gap is not equal to the 2.435 s DMA integral; pD−H for the oracle is negative on the all-workflow mean at every p, while the S3 and N4 targets favor the predictor arm at every p; only N4 is a missed checkpoint under the oracle.

Related Work may name the modeled policies and must still say they are not reproductions and that the paper does not claim a lower recovery time than DéjàVu, LUMEN, or GhostServe unless a sentence is explicitly about the modeled policy.

Abstract, introduction, and conclusion must not say AegisKV outperforms those systems. They may say what the new runs show relative to fixed checkpointing, load-aware checkpointing, and the tail shadow.

## Finish

From the repo root, rebuild with:

cd benchmark/AegisKV/paper && latexmk -pdf -interaction=nonstopmode -halt-on-error -outdir=../exports/latex-build main.tex && cp ../exports/latex-build/main.pdf main.pdf

If latexmk says the file is up to date, rerun with -g. Confirm with python3.11 and pymupdf that the new baseline names are in the PDF.

Write benchmark/AegisKV/experiments/evaluation-20260924/external-baseline-v1/PAPER_NUMBERS.md mapping every new number you put in the paper to a file and a field. Write STATUS.json when the campaign and the PDF are done.

In your final message, state the model identity, the smoke-test result, whether any existing policy path changed, the three baseline definitions, and the result in one paragraph. Do not describe a result you did not run.
