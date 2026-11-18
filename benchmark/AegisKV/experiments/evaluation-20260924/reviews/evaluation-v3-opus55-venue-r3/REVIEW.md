I'll start by reading the previous review, the edited manuscript sections, and the mechanism-decision artifacts, then check each claim against the run summaries and event logs.
Now the manuscript text.
Now the 18 per-run summaries. Let me list the runs directory and check the event logs' presence.
The `events.jsonl.gz` logs exist this time. I'll inspect a summary's structure and the event log's record types before computing anything.
The sandbox backend failed on the event-log read (the same failure the previous review hit). The command only decompresses and counts records, so I'll retry it once.
The retry worked, so I can check the per-Agent counts the previous review could not. Next I'll find how the paper maps the S1/N2/S3/N4/S5 labels to fault IDs, and how it defines the \(pD-H\) rule.
Labels confirmed (S/N = sink/non-sink, numbered by fault index). Now I'll recompute every number in the section from the 18 summaries and the healthy event logs in one read-only pass.
The sandbox failed again on `git diff`; retrying the same read-only command.
No uncommitted diff, so the edits are either committed or the files are untracked. Checking the file status and recent history.
The primary replay (`walltime-primary-v3`) keeps event logs for its healthy runs, so I can test "does not change the protected set" directly across all six model/load cells.
I'm Claude Opus 5.5. I made no edits and ran no simulations. I recomputed every claim from `SUMMARY.json`, the 18 `summary.json` files and the three healthy `events.jsonl.gz` logs. To test contribution 3, I also read the six healthy DRAM and All-DRAM event logs in `walltime-primary-v3`.

**1. NOT PAPER-READY**

Every number you listed matches the artifacts:
- DRAM and All-DRAM checkpoint the same 498 of 503 Agents. The oracle's 391 are a strict subset of those, so it protects 107 fewer.
- The target penalties, absolute failure-case means and paired all-workflow penalties all match. So do the −16.576 to +12.249 s healthy spread, \(H=0.902\) s, and the largest reduction \(D=0.502\) s (on S1).
- On S1, S3 and S5 the penalty increases equal the queue increases to within 21 µs. On N2 the queue grows 0.020 s while the penalty grows 1.294 s. N4 is the only oracle fault with `checkpoint_tokens` 0.
- The largest service gap is 21.4 µs, so "within 22 µs" is true.
- The abstract, contribution 1, the section and the conclusion all describe Top-K HBM and the quota as specified and not exercised.

**2. Sentences that are still false**

- **Contribution 3:** "Under the evaluated predictor, Slack selection does not change the protected set, including in one binding-budget cell."
  - Artifact: in the primary replay's healthy runs, DRAM checkpoints 497 of All-DRAM's 498 Agents at 8B \(\rho=0.3\). It checkpoints 496 at 32B \(\rho=0.3\) and at 32B \(\rho=0.65\).
  - Replace with: "Under the evaluated predictor, Slack selection omits at most two of All-DRAM's 498 checkpointed Agents in the primary replay and none in one binding-budget cell."

- **Conclusion:** "…and \(pD-H\) does not favor the predictor arm at any failure probability."
  - Artifact: this holds only for the all-workflow mean. For the target workflow on S3 and N4, DRAM is faster when healthy (16.667 vs 22.690 s, and 17.685 vs 17.939 s) and also has the lower penalty. So \(pD-H>0\) for every \(p\) on those two faults.
  - Replace with: "…and on the all-workflow mean \(pD-H\) does not favor the predictor arm at any failure probability; on the S3 and N4 targets it favors that arm at every \(p\)."

- **Conclusion:** "Slack selection, as evaluated, does not improve workflow completion."
  - Artifact: the evaluated oracle arm lowers the healthy all-workflow mean by 0.902 s, and lowers the failure-case mean on all five faults.
  - Replace with: "With the evaluated predictor, Slack selection does not improve workflow completion; with oracle inputs it lowers the all-workflow mean and raises every target penalty."

- **Section (overstated rather than false):** "The missed checkpoint explains the target only on N4."
  - Artifact: N4's penalty rises 4.486 s under the oracle. Rebuilding accounts for 1.786 s of extra service. The queue adds 0.911 s, with the retry on worker 7 instead of worker 1. The remaining 1.789 s comes after recovery.
  - Replace with: "Only on N4 does a missed checkpoint contribute, adding 1.786 s of service to a 4.486 s increase; the rest, and the other target increases, follow retry placement and later routing."

**3. Decisive gap: text-fixable**

Contribution 3 is one of the paper's stated contributions, and the primary-replay artifacts contradict it. Fix it together with the two conclusion sentences above. For the narrow claim, I found nothing in this section that needs a new run.

On the noise floor, I agree it isn't required for differences between arms inside this deterministic cell, as long as the text only describes them. The per-workflow healthy spread is about 30 times the 0.902 s mean shift. Modeled DMA slowdown falls only 2.435 s, while summed healthy completion time falls 55.9 s. The text should therefore report the shift as an observed difference between arms, not attribute it to lower checkpoint overhead.