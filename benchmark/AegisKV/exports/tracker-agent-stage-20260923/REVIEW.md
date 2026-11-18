# Tracker: Agent execution-stage timing

- Scope: rewrite only the Tracker subsection of the active manuscript, with Chinese source comments for every prose paragraph; update the scoped AGENTS.md contract.
- Claim: an Agent task comprises multiple invocations. Track invocation identity and compatible history consumers, but predict remaining execution-stage duration directly without requiring a fixed future invocation count.
- Timing scope: the runtime exposes stage dependencies. Split at inter-Agent dependency boundaries; an uninterrupted Agent task is one stage. Active-stage targets begin at the current observation, while unstarted-stage duration begins after predecessor completion. Edge-represented dependency waiting is excluded.
- Accounting: count remaining stage work once, map each invocation to stage slack, and treat path slack as shared. Predicting aggregate future work does not establish unseen KV consumers or guaranteed reuse benefit.
- Evidence boundary: this is a manuscript design change. It does not implement or retrain a predictor or establish prediction/recovery accuracy.
- Verification: 13 scoped checks pass (checks.json). Source outside Tracker, Background/Motivation, manuscript wrapper and figure assets match their before hashes. The canonical build succeeds with no errors, undefined references or overfull boxes. Existing bibliography/accessibility/spacing warnings remain outside this edit.
- Visual review: inspected final exported PDF pages 3 and 4 at the paper layout; text and equation are legible, no clipping or collisions. Main PDF remains 8 pages. No new figure was introduced.
- Before/after source and PDF hashes, the before snapshot, build log and page previews are stored in this review directory.
