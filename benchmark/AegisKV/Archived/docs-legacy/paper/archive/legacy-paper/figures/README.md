# Figure provenance and evidence boundary

## Active submission figures

- `motivation-real-cc-three-panel-submission.pdf` and `.png` are the active
  Motivation figure.  Their paper-specific, reproducible renderer is
  `../scripts/render_motivation_real_cc_submission.py`, and
  `motivation-real-cc-three-panel-submission.manifest.json` binds every input,
  output, statistic, evidence boundary, and PDF typography check.  This is only
  a two-row re-layout of the previously active three-panel Figure 1.  It
  consumes the frozen SGLSim-derived Real CC workflow-gap CSV, the frozen
  five-target counterfactual CSV, and the existing editable workflow Draw.io/PDF;
  it does not read the raw trace, execute AIConfigurator, run SGLSim, or create
  a new experiment.  Panels (a) and (b) are trace observation/reconstruction;
  panel (c) remains a frozen trace-plus-AIConfigurator counterfactual, not a
  Claude, physical-PP, failure-to-ready, or paired failure measurement.
- `system-overview-submission.drawio` is the active editable System Overview.
  Its native vector and raster exports are
  `system-overview-submission.drawio.pdf` and
  `system-overview-submission.drawio.png`.  These three files form the active
  submission asset set; the older overview/design exports below are retained
  only for provenance.

## Historical components and excluded candidates

- `real-cc-parallel-subagent-duration.pdf`,
  `real-cc-workflow-8ab0a089.pdf`, and
  `real-cc-failure-position-counterfactual.pdf` are the three frozen components
  of the historical active Motivation Figure 1.  They remain provenance inputs
  to the submission re-layout above, but are no longer the paper-level layout.
- `motivation-workflow-slack-real-cc.drawio` and
  `motivation-workflow-slack-real-cc.pdf` are an excluded design candidate.
  They are not active, are not an input to the submission Motivation figure,
  and must not be cited or included by the paper.
- `system-overview.pdf`/`.png` is the previous three-layer overview exported
  from `../../figures/aegiskv-paper-system-design-v2.drawio`; it is no longer
  the active submission overview.
- `system-design-v2.pdf`/`.png` is an audit copy of that previous export;
  `system-design.pdf`/`.png` is an older legacy export.
- `protection-coverage-comparison.pdf` and `.png`: legacy policy-comparison export retained for audit only; the Motivation section no longer cites it.
- `commit-recovery-protocol.pdf` and `.png`: legacy protocol export retained for audit only; the v2 paper uses compatibility-checked group commit, failure-time `FreezeAndPin`, durable-boundary adoption, and continuation/output fencing instead.
- `system-architecture.pdf`: page 2 of the more detailed `../../figures/aegiskv-master-vllm-mooncake.drawio`; it includes formulas and the analytical/correctness/empirical evidence split, so it is useful as a design appendix but too dense for the main paper.
- `real-cc-parallel-subagent-duration.pdf` and `.png`: workflow-level CDF of the maximum slowest-minus-fastest duration gap across strictly overlapping Real CC fan-outs.
- `real-cc-failure-position-counterfactual.pdf` and `.png`: frozen five-target counterfactual for workflow `8ab0a089...` at the common active time 349.5 s, with observed fan-in Slack subtracted from configuration-predicted prefix recomputation; not an end-to-end replay result.
- `real-cc-workflow-57f2a77e.pdf` and `.drawio.png`: native Draw.io export of a selected three-way fan-out excerpt reconstructed from the Real CC trace; it is not the complete 977-request workflow.
- `motivation-recovery-scaling.pdf` and `.png`: one-column overlay of full-prefix recomputation for three AIConfigurator model/parallel configurations.  It uses the public SGLSim predictor interface in SILICON database mode and marks an illustrative operator-declared budget; it is neither hardware measurement nor full failure-to-ready time.
- `motivation-recovery-frontier-gap.pdf` and `.drawio.png`: neutral Motivation schematic from `../../figures/motivation-recovery-frontier-gap.drawio`; it contains no AegisKV mechanism or system comparison.
- `motivation-failure-position.png` and `motivation-workflow-dag.png`: legacy synthetic Motivation assets not cited by the paper and not valid Real CC evidence.
- `motivation-gpu-availability.png`: the simulated GPU-availability input trace.
- `preliminary-wct-kv-reuse.png`: preliminary simulated WCT CDF and retry-token reuse result; it must not be used as evidence for the complete optimizer without reproduction.

The main-text Draw.io drawings intentionally omit internal figure titles; the
LaTeX caption is the single source of the figure title.  All active exports
must be regenerated after their Draw.io or renderer sources change; the paper
intentionally fails if a required main-text PDF is absent.
Captions separate direct trace statistics, trace counterfactuals, modeled path
isolation, and complete-system claims. A final EuroSys result must use paired,
traceable measurements with sample counts, confidence intervals, versioned
configs, and an explicit real-runtime/simulator/analytical evidence label.
