# Primary figure captions and final-size review

Both figures use a native **178 mm** canvas and **10.3 pt Linux Libertine**
labels. Insert at full text width; shrinking them into an 84.7 mm column would
halve the intended type size. Heights are 78 mm and 62 mm, respectively.
Editable PDF/SVG, PNG and the unchanged `plot_profile_campaign.py` are retained.

## `core-workflow-delay`

**Suggested caption.** Primary workflow replay with Qwen3-8B and Qwen3-32B at
three nominal arrival loads. For each policy and fixed failure scenario, we
first average the 62 same-ID workflow differences, failure WCT minus that
policy's healthy WCT. Each marker averages these five scenario means; whiskers
show their minimum and maximum, not confidence intervals. Negative differences
remain included. Policy markers are horizontally offset within each load for
readability. Workflows sharing a run are dependent, and the five prespecified
fault identities are descriptive scenarios rather than random failure samples.

The underlying table has **150 scenario-mean values**: 2 models × 3 loads ×
5 policies × 5 faults. These become 30 mean/range markers, not 150 independent
repeats. The same healthy run is reused across its five fault comparisons.
All-DRAM and DRAM have identical aggregate means here, but two workflow records
at 32B/load 0.9/fault 4 differ by opposite 4.113432720 s amounts. Static-HBM and
AegisKV have identical individual workflow completion records throughout.
The companion numeric audit records these limits and all negative outcomes.

## `core-hbm-increment`

**Suggested caption.** Incremental HBM effect on the fault-target workflow.
Each circle is DRAM WCT minus AegisKV WCT for the same Agent, invocation and
logical failure-token position; positive values favor AegisKV. All 30 pairs
also match the actual fault time and failed worker, and their target-workflow
healthy baselines are identical. Black segments show the mean of the five
fixed failure scenarios at each model/load condition; no confidence interval
is shown. Points are horizontally offset only for readability. Zero and
negative effects are retained, including an 8B/load 0.65 effect of
−0.002577 ms, which is visually close to zero at this scale.

This table contains **30 same-target differences**: 2 models × 3 loads ×
5 faults. It uses target-workflow WCT, unlike the 62-workflow average above.
The 8B range is −0.002577 to 1.441955 ms; the 32B range is 0 to 0.140321 ms.
A positive target effect does not establish a positive all-workflow effect.
These are profile-informed CPU simulation results, not native sparse model
execution or calibrated hardware latency.

## Checks and limits

The two tables together contain 180 numeric values, validated directly against
180 raw run summaries and 9,300 same-ID workflow pairs in
`INDEPENDENT_NUMERIC_AUDIT.json`. All 525 negative workflow differences, five
negative scenario means, and one negative target-HBM difference are retained.

Actual original PNGs and PDF-derived color/grayscale images were opened.
At 178 mm, the minimum extracted font is 10.3000003 pt; neither PDF has text
outside its page. The one-line legend and all axis labels are clear, and
marker shapes/offsets distinguish policies in grayscale. Near-zero effects
and very similar policy means are not visually separable at the full range;
the exact numbers above and in the audit preserve their meaning. No data or
axis was changed to magnify a favorable result.

`FIGURE_REVIEW.json` records the actual viewed files and hashes.
This subtask reviewed the standalone exports; the parent separately reported
viewing manuscript page 10. Final manuscript placement after later edits
remains the parent task's review.
