# Frozen profile-campaign replay

`scripts/current_design/run_frozen_profile_campaign.py` runs the frozen
`evaluation_campaign.run` implementation in a physical temporary package tree.
It does not replace core code with the current EOS-fix runtime and does not
modify the original campaign, snapshots, manifests or completed results.

Usage from the repository root:

```sh
.venv/bin/python benchmark/AegisKV/experiments/scripts/current_design/run_frozen_profile_campaign.py \
  --campaign benchmark/AegisKV/experiments/evaluation-20260924/formal-core-v1 \
  --verify-only
```

To replay a selected prefix of the frozen job order, use a nonexistent output
directory outside the original campaign:

```sh
.venv/bin/python benchmark/AegisKV/experiments/scripts/current_design/run_frozen_profile_campaign.py \
  --campaign benchmark/AegisKV/experiments/evaluation-20260924/profile-smoke-v3 \
  --out /tmp/my-new-frozen-replay --workers 1 --limit 1
```

The full sealed PLAN is copied unchanged; a limited replay remains PARTIAL.
Without `--limit`, all planned jobs execute in the new directory. Existing
output directories are rejected, including partially executed replays. This is
a fresh replay tool, not an in-place resume command for active old outputs.

## Source and dependency boundary

Before execution, the script checks every declared frozen source hash, both
PLAN/PRIORS seals, profile hashes, and workload compressed/content hashes.
The isolated runner then repeats its own ROOT-relative source checks. Every
`current/`, `simulation/`, `evaluation_*.py` and common hash module must come from
the original snapshot. Missing core modules fail rather than falling back to
the editable live installation.

The original campaign did not freeze every parent package initializer or the
FanOutQA modules imported transitively by `evaluation_workload`. The tool copies
missing non-core Python support from the current tree, separately saves it in
`replay_support/`, and hashes it in `REPLAY_MANIFEST.json`. For this replay,
117 support files were retained; 48 of them and 23 frozen modules were actually
imported. The import report identifies every loaded package source and records
installed external package versions. A namespace guard prevents any MoonKVSim
module from escaping the isolated tree, including through editable-install hooks.

This preserves the original simulator/evaluation implementation while explicitly
disclosing dependency supplements; it does not retroactively claim that the
original campaign froze those ancillary dependencies or its entire environment.
No tokenizer, dataset normalizer, training preparation, or new model profile is
executed during replay: jobs consume the frozen workload/profile/priors files.

## Validation

`reviews/frozen-smoke-v3-replay/` contains one replayed `none-F0` job from the
six-job smoke matrix. Its complete summary is byte-identical to the original:

`141a1784240a232bc090f0bff06197e553aae2998107de50ba515de554c2ca3c`

The result retains design version
`checkpoint-decay-hysteresis-incremental-g-20260924`, rather than the live
`eosfix1` version. The remaining five jobs were not executed. Both smoke-v3 and
formal-core-v1 passed verification-only import checks; no additional formal
180-job execution was started.

Seven tests pass, covering read-only verification, source corruption, a missing
frozen runtime despite an available live runtime, forbidden core supplements,
and existing/nested/dangling-symlink output rejection. Ruff passes. Replayed results, control
artifacts, launcher/bootstrap sources, actual import hashes and the exact
reference-summary comparison are retained in the new replay directory.
