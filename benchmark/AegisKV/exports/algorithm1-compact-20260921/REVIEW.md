# Algorithm 1 presentation revision

The user found the algorithm too verbose. Algorithm 1 now uses twelve short pseudocode lines with assignments, a bounded candidate loop, explicit comparisons, early returns and a reservation check. Explanations of MakeRoom, capacity relief, version checking and completion handling stay in the surrounding prose. The Chinese companion contains matching pseudocode.

The policy is unchanged: select the lowest-cost examined feasible complete plan; optional placement requires an improvement beyond epsilon, while required relief may accept positive cost; stale versions or failed reservations cause replanning. The Connector retains the copy/commit/redirect/drain/release protocol. This is a presentation change, not a new algorithm experiment.

The algorithm remains at the original body font size. Its rendered height falls from 269.74 to 162.15 pt, a 39.9% reduction. The full page and cropped algorithm were inspected after compilation. Canonical output is `paper/main.pdf`, page 8. The build has no undefined references or overfull boxes. No figure assets or experimental data were changed. The full prior Design review remains in `../design-section-ready-20260921/REVIEW.md`.
