# Replacing analytical curves with measured data

The current analytical inputs live at `../data/eurosys27/theory/`. The ten figure filenames and insertion widths are stable. Numerical arrays are read from CSV; figure geometry, typography, markers and panel composition are in `scripts/eurosys27/plot.py`. Do not edit coordinates by hand or rename synthetic values as measured.

## Long-table schema

Each plotted table has these exact columns:

| Column | Meaning |
|---|---|
| figure | Filename stem, e.g. `capacity-frontier` |
| panel | `budget`, `cdf`, `bandwidth`, `error`, `lag`, `load`, `fault`, `reuse`, `occupancy`, `copied`, `counterexample`, `scaling` |
| series | Stable policy/condition name; `AegisKV model` for theory, `AegisKV` for measurements |
| x | Finite numerical x coordinate in the declared axis unit |
| y | Finite observed estimate / ECDF ordinate / timeline value |
| lower, upper | Both empty, or lower/upper ordered endpoints of a declared interval; never fake analytical confidence bounds |
| unit | `s`, `ms`, `GiB`, or `fraction`, matching the figure specification |
| evidence | Exactly `analytical` or `measured`, uniformly within one rendered batch |
| scenario_id | Config ID, or measured cohort/timeline ID |
| source_id | Provenance key; measured manifest must connect it to raw logs |
| independent_runs | `0` for theory; number of independently launched campaigns for measured summaries |

The renderer uses the full finite range, including negative results; there is no clipping to an assumed success range. Do not use missing rows to hide timeouts or failed cells. They belong in the run ledger and in the completion/censoring companion metric even when an ordinary latency estimate cannot be drawn.

`measured-template/` provides headers for each table and raw `workflows.csv`, `predictions.csv`, and `correctness.csv`. Empty templates cannot be plotted as results. Axis units and metric definitions are fixed: e.g. `healthy-io` is I/O response time in ms, not TTFT or token delay. A new metric needs an explicitly registered spec.

## Provenance manifest

Analytical manifests are generated automatically; the renderer checks the current model/configuration hashes and asks for table regeneration if either changed. For measurements, create `manifest.json` beside the tables:

```json
{
  "schema_version": 1,
  "evidence": "measured",
  "statistical_unit": "independently launched paired campaign",
  "aggregation_command": "python summarize.py --raw raw/ --bootstrap-seed 20260920",
  "uncertainty": "paired campaign bootstrap, 95%, 10000 draws",
  "raw_sources": [
    {"id": "campaign-v1", "path": "raw/workflows.csv", "sha256": "ACTUAL_SHA256"}
  ],
  "tables": {"capacity-frontier.csv": "ACTUAL_SHA256"}
}
```

Use actual paths/digests, not the strings above. Relative paths resolve from the table directory. A raw hash proves file identity, not correctness of the physical experiment; the event logs and parity checks provide that evidence. The renderer checks table hashes, raw hashes, evidence labels, finite values, interval ordering and run counts. It cannot certify that a mislabeled raw file came from hardware.

## Pairing and aggregation

For each campaign/policy/workflow, match its healthy and fault run by ID. Compute `penalty = faulty_wct - healthy_wct`. Do not subtract every policy from the LRU healthy time. For a policy contrast compute `baseline_penalty - aegiskv_penalty` within the same campaign and workflow, then aggregate within campaign before bootstrapping campaigns. Confidence intervals for a difference must resample these pairs; subtracting the endpoints of unrelated intervals is incorrect.

For the ECDF, specify whether workflows or campaigns have equal weight; maintain all zero and negative values and the full tail. For timeouts, keep a status column and predeclared observation horizon; report completion and a restricted-time analysis separately. A figure row is not an independent experiment.

`aggregate_workflows.py` implements paired complete-case **mean penalty** and paired differences by campaign, with a timeout/completion ledger. It deliberately refuses incomplete policy/condition pairs. It does not claim its complete-case estimate substitutes for restricted-time/censoring analysis.

The default `--metric penalty` writes a plotting CSV (by default `capacity-frontier.csv`). `--metric difference` writes a separate `paired-differences.json` report whose positive values mean improvement; it must not replace a table with an absolute-penalty axis. Both record the exact aggregation command and raw-file hash.

```bash
python3 benchmark/AegisKV/experiments/scripts/eurosys27/aggregate_workflows.py \
  --raw /absolute/path/to/workflows.csv --output /absolute/path/to/measured-tables
```

Set the raw table's `x` to the DRAM budget in GiB for this default figure. Independent campaigns with no estimable interval retain empty endpoints; available intervals at other points are still drawn.

## Rendering and publishing

```bash
python3 benchmark/AegisKV/experiments/scripts/eurosys27/plot.py \
  --mode measured --data /absolute/path/to/measured-tables \
  --output /absolute/path/to/measured-figures
```

PDF/PNG/SVG are regenerated at the same sizes; valid intervals are drawn automatically. Add `--publish` after reviewing the output to replace matching `paper/figures/*.pdf` and PNG previews. Do not invoke the analytical generator into a measured directory.

Keep only populated plotting CSVs in the table directory and put raw CSVs in a subdirectory or elsewhere. Empty templates are starting schemas, not registered results. The renderer rejects unknown panels, modified sources and mismatched units. Axis ranges expand for finite data; logarithmic controller-cost axes require strictly positive values.

Finally revise the paper's abstract, evaluation values, captions, conclusion, and Chinese companion from the measured aggregate report. Remove “Analytical scenarios” only through measured mode, and retain any remaining analytical panels with their own correct captions. Theory and measurements can coexist in a paper, but a single series must not splice them without a visible distinction.

## Expanded single-column workflow (2026-09-21)

`expanded.py` writes 33 tables to `experiments/data/eurosys27/expanded/` and a fixed `figure-specs.json`. Extra `category` supports horizontal grouped/stacked bars and the compact vertical per-system chart; the other long-form fields preserve the earlier contract. In the per-system chart, categories identify systems, the CSV `y` remains LRU minus workflow-value mean penalty, and no system is dropped or averaged with another. Analytical, observed trace and trace-driven model are separate per-table labels. Observed trace plots can retain their original evidence when measured performance plots replace other panels.

`prepare_measured_figures.py` accepts a folder of **already aggregated** `eval-*.csv` and a raw manifest. The raw manifest must provide `measurement_class: "physical"`, nonempty `aggregation_command`, `statistical_unit`, `sample_accounting`, and `raw_sources: [{"id": "campaign-set", "path": "path-to-raw-log", "sha256": "actual hash"}]`. Paths resolve relative to that manifest. Each row must have `evidence=measured`, `independent_runs>=1`, and a matching `source_id`. Raw files are copied and hash checked; supplied data is not relabeled automatically. Blank templates are skipped. Measured confidence intervals can extend beyond plotted means; both finite ordered endpoints must be provided together. The paired campaign aggregator remains available for WCT, while component/queue/correctness metrics require their specified aggregation.

The packager writes a matching per-subset visual spec; `plot_expanded.py --data ... --spec ... --out ...` draws it without changing canvas/fonts/legends. Publish only after checking the resulting numbers/captions and rendering. Units and metric identity must remain the same; a different metric gets a distinct registered spec. This tool packages provenance but cannot certify that a supplied log came from physical execution; the author retains that responsibility.

For bars, provide the complete set of defined categories/series within the selected panel. Omit unexecuted figure panels entirely or retain explicit missing cells in the raw experimental ledger; never fill missing results with zero or modeled values. Current analytical tables do not contain campaign-level confidence bounds. Distinct real-workflow outcomes need an appropriate measured denominator; do not leave a scenario CDF labeled as observed workflows without updating its semantic specification.
