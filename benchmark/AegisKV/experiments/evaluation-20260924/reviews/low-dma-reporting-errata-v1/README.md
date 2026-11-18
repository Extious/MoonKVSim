# Low-DMA reporting correction and offline dose check

This sidecar preserves the sealed original package. No DES was rerun,
no model was tuned and no original numeric artifact was edited.

The start-of-compute slowdown is binary: if any active flow uses a
worker's H2D/D2H resource, that event is charged ceil(base duration ×
coefficient). Average payload bytes/s is traffic accounting, not this dose.
The host-rate window is common across hosts within one run; its endpoints
are that run's first release and last completion, so it is not common
across runs and includes idle time.

For the 12 fully logged healthy runs, offline profile/flow reconstruction
matches all 624 request completions and each retained total slowdown exactly.
Each run has 2,850 compute events. DRAM and AegisKV have 2,246 exposed
starts at coefficients 0.002/0.005 and 2,245 at 0.01/0.02:
78.81%/78.77% of event starts, representing 75.41%/75.30% of base compute
duration. Restart has zero exposed starts. This verifies the finite
healthy cases only; F1 recovery schedules and older incompletely logged
parameter points do not receive reconstructed fractions.

Every table below uses a cohort **sum**. Target objectives remain separate
in corrected-break-even.csv. The accumulated compute-event extra time
is a different quantity from workflow cost, because workers overlap.

| coefficient | policy (service proxy) | healthy cost H (s) | absolute F1 gain A (s) | feasible break-even p |
|---:|---|---:|---:|---|
| 0 | dram | 0.000000000 | 0.864579681 | 0 (p>0 improves) |
| 0 | aegiskv | 0.000000000 | 0.866023552 | 0 (p>0 improves) |
| 0.002 | dram | 0.044713945 | 0.814469473 | 0.052042 |
| 0.002 | aegiskv | 0.044713945 | 0.815913344 | 0.051955 |
| 0.005 | dram | 0.111784459 | 0.739304611 | 0.131343 |
| 0.005 | aegiskv | 0.111784459 | 0.740748482 | 0.131120 |
| 0.01 | dram | 0.223568513 | 0.614029988 | 0.266916 |
| 0.01 | aegiskv | 0.223568513 | 0.615473859 | 0.266457 |
| 0.02 | dram | 0.447136718 | 0.363480642 | 0.551600 |
| 0.02 | aegiskv | 0.447136718 | 0.364924513 | 0.550619 |
| 0.05 | dram | 1.117841231 | -0.388167291 | none |
| 0.05 | aegiskv | 1.117841231 | -0.386723420 | none |
| 0.1 | dram | 2.235682069 | -0.740372019 | none |
| 0.1 | aegiskv | 2.235682069 | -0.738928148 | none |

For this exact two-scenario mixture, net advantage is p(H+A)−H.
At c=0.05/0.1 the absolute faulted cohort gain is negative, so no
probability in [0,1] improves the objective; algebraic roots above one
are retained only in the CSV and are not described as probabilities.
This remains one input-selected longest-prompt fault, four dependent
workflows, and an uncalibrated binary sensitivity. It is not a measured
failure probability, population estimate or physical DMA calibration.
