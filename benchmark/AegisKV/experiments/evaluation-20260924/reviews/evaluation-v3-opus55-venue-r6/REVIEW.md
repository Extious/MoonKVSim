I'll locate the prior review, the edited paper sections, and the `walltime-primary-v3/run-metrics.csv` artifact, then verify each claim against the data.
Now the abstract, introduction (contributions), and conclusion.
The prose has been edited in all five places. Now I'll check the artifact `run-metrics.csv` to verify the quota and HBM numbers.
The sandbox failed at setup (an intermittent issue seen in earlier reviews); I'll read the CSV directly instead.
The CSV is wide (about 180 rows). I'll retry the read-only shell to parse specific columns; if the sandbox keeps failing I'll fall back to Grep.
Sandbox failed again; retrying the identical read-only command once more since earlier reviews found this failure intermittent.
The retry worked. Now I'll recompute every quota and replica-HBM number from the 180 runs in one read-only pass, including the fault runs, the 32B rows, and the Static-HBM rows.
Intermittent sandbox failure; retrying the identical read-only command.
Sandbox failed three times in a row; I'll try once more and in parallel pull the relevant rows with Grep as a fallback.
The quota diagnostic's audit records two adaptive-run quota decreases (32 MiB to 24 MiB at 11.3 s). I'll check which runs they come from and how the audit summarizes them.
Peer DRAM peaks at 31.2 GiB of 256 GiB across all 180 runs, so "never binds" holds. A few 32B runs log one `dram_reselections` event; I'll confirm that counter isn't capacity-driven.
I'm Claude Opus 5.5. I made no edits and ran no simulations; every value below comes from read-only scripts over the artifacts.

**1. PAPER-READY.**

All five edited passages now match `walltime-primary-v3/run-metrics.csv`. I found no remaining false mechanism or endpoint claim in the Evaluation or the contribution bullets.

- **The 8B quota binds.** The healthy AegisKV runs log 4, 4 and 9 increases, reaching 201,326,592, 201,326,592 and 268,435,456 bytes. The quota grows only after an HBM admission is deferred (`policy.py` line 31, `stable >= stable_windows and deferred`), so "does bind" describes the mechanism correctly. All 18 8B runs end at 192 or 256 MiB.
- **HBM copies.** Healthy per-rank replica peaks are 176.4, 187.2 and 220.4 MiB, against 121.2 MiB for Static-HBM.
- **Totals.** The 72 HBM-policy runs have 98 increases (all in 8B AegisKV), no decreases and no pressure events. On 32B, AegisKV stays at 128 MiB and matches Static-HBM in every saved metric; only a logging flag differs.
- **Completion time.** Static-HBM and AegisKV are identical in all 2,232 pairs (1,860 faulted, 372 healthy). DRAM and AegisKV differ by more than 10 ms in only one workflow, the 3.41 s rerouting case the paper already discloses. So "neither mechanism materially changes workflow completion" holds.
- **Peer DRAM** peaks at 31.2 GiB out of 256 GiB across all 180 runs, so "never binds" holds.
- **DMA sentence.** It still says "the mean is not equal to that charge." The new clause, that the charge first separates the two arms and queueing amplifies it, is supported: with the coefficient at zero, healthy completion time is identical across policies.

**Two optional scope fixes (not blocking):**

1. **Resources paragraph.** "Holds up to 220.4 MiB of copies" is the healthy maximum. One faulted run (`Qwen3-8B-load0.9-aegiskv-F1-0`) reaches 253.1 MiB. The paragraph opens with "In the six healthy runs," so the number is scoped, but putting "healthy" next to it would prevent a misreading.
2. **Conclusion.** "Its decrease path, and sparse Top-K selection, do not run in these replays." This is true for the primary matrix and the binding-budget cell. However, the 72-run quota diagnostic's `INDEPENDENT_ACCOUNTING_AUDIT.json` logs the quota shrinking from 32 MiB to 24 MiB under pressure. That happens at 11.3 s, after the target workflow finished at 7.67 s, and no endpoint changes. Read broadly, the sentence understates what was exercised rather than overclaiming. Suggested replacement: "Its decrease path fires only in the near-capacity diagnostic, after the target workflow has finished, and no workflow replay tests native sparse Top-K selection."