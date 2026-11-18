# Adapter analysis data

Evidence: uncalibrated analytical recovery and synthetic queue simulation. No physical experiment or measured timing input.

See [figure, assumptions, statistical units, and interpretation](../../../../../output/pdf/aegiskv-adapter-analysis-20260919/README.md).

Configuration is in config.json. Each recovery CSV row is an analytical configuration, not an independent workload. Each queue-runs.csv row is one complete synthetic arrival-stream run at one load and one capacity. The same seed is paired across capacities. summary.json records model checks and key values.

Generator: experiments/scripts/paper/render_adapter_analysis.py, run from the repository root. The figure's MANIFEST.json hashes configuration, generator, and CSV files.
