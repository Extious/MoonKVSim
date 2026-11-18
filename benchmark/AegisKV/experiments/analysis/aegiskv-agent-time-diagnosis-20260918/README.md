# Figure 3(a) error diagnosis

Frozen workflow-held-out predictions were grouped for diagnosis. No paper figures, inputs, or trained predictions were changed. Duration and progress bins are post-hoc labels, not proposed model inputs.

## Direct observations

| Actual duration | Agents | Median per-agent NMAE | Median per-agent MAE (s) | Snapshot share |
|---|---:|---:|---:|---:|
| <30s | 167 | 649.7% | 137.0 | 1.35% |
| 30-120s | 573 | 138.8% | 104.0 | 13.06% |
| 120-600s | 741 | 32.5% | 76.2 | 45.18% |
| >=600s | 207 | 45.2% | 459.1 | 40.40% |

At the final request of each agent, actual remaining time has median 13.366 s, while predicted remaining time has median 154.143 s. 98.46% of these predictions overestimate remaining time. These are population medians, not one paired example.

All roles in the extracted data are Subagent. Initial features contain model, prompt length and zero progress but no task semantics. In the second-largest eligible identical-entry-feature group (26 agents in 4 workflows, opus-4-8, prompt length 42,944), observed durations range from 14.797 to 1,737.810 s. This illustrates information aliasing, not an irreducible-error estimate for all agents.

The 10% of agents with the most requests contribute 40.13% of training snapshots. The plot gives each agent one weight. The implementation minimizes squared error on log1p remaining time, not equal-agent normalized absolute error.

The P90 baseline uses all training agents with the same raw role. Because the raw role is constant, it collapses to a global duration prior. It is not a validated role-specific recent-history runtime predictor.

## Interpretation and limits

Weak task/stage information, snapshot weighting and loss/metric mismatch are plausible contributors. No ablation has yet established their separate causal contributions or that a richer predictor will satisfy the desired Insight. The normalized metric amplifies short-agent errors, but their absolute errors are also large. API-interval gaps cannot be attributed specifically to tools from this trace.

Sources: diagnosis.json (input hashes), additional.json, analyze_agent_duration_insight.py, and provenance/aegis_gbdt.py.
