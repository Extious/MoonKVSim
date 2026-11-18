# Capacity / zero-Slack ablation results

All 32 runs and 64 workflow pairs passed the frozen runner checks. Additional input/config/variant and cross-snapshot checks are recorded in INDEPENDENT_VARIANT_AUDIT.json.

**No WCT benefit of DAG Slack is observed in this cohort.** AegisKV and zero-Slack have identical individual workflow completion times for every F0/F1 run at all four capacities. The interventions are active: copied bytes, checkpoint commits, reselections and byte-time integrals differ.

| DRAM per host | Current healthy backup (GiB) | Zero-Slack healthy backup (GiB) | Reduction (%) |
| ---: | ---: | ---: | ---: |
|2|70.292094|73.727164|4.6592|
|4|91.903213|96.317263|4.5828|
|8|91.093703|95.507753|4.6217|
|256|91.093703|95.507753|4.6217|

Backup bytes are completed checkpoint + completed hot placement + canceled-copy transferred bytes, modeled counters rather than new hardware measurement. Completed checkpoint bytes alone are a different metric and must not be relabeled all traffic.

At 2 GiB every variant has checkpoint 0 at the target fault and 1.802310283 s target penalty. At 4/8/256 GiB, DRAM and All-DRAM yield 0.060982205 s; Current and zero-Slack yield 0.059538334 s. No adverse/null result was removed.

Zero-Slack affects the Slack input to both DRAM exposure and HBM gain. It is a no-DAG-Slack control, not an isolation of O1 while holding O2 Slack fixed. All-DRAM remains its separately named selection baseline.

There is one fixed failure identity and four dependent workflows, with modeled profile costs, static training priors and zero baseline DMA slowdown. Equal healthy WCT is not measured zero runtime overhead or real predictor-accuracy evidence.
