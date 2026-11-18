# Isolated prospective profile metadata patch

Ready for review; **not applied to live source**. This directory contains a
five-file patch, its isolated source tree, and prepare-only verification.
No DES run was executed. The recovery-domain correction is outside this patch.

`prospective-metadata.patch` changes only:

- `evaluation_profile.py`: a pure `profile_manifest_fields` helper reporting
  the actual table, provider, bounded interpolation, profile scale, and every
  configured DMA slowdown level. It preserves unknown evidence tags as unknown
  and returns detached JSON-compatible metadata.
- Three campaign runners: merge those fields before the final MANIFEST write
  and, for post-hoc, before SEAL hashes that file. Existing generic manifest
  defaults and runtime behavior remain unchanged.
- `tests/aegiskv/test_evaluation_profile_metadata.py`: ten focused cases for
  zero/mixed DMA settings, complete config inspection, table evidence tags,
  deterministic serialization, independent return values, unchanged timing,
  and invalid/missing inputs.

Validation: **14 tests passed** including the four existing profile tests;
Ruff clean; `git apply --check` passed. `PREPARATION_CHECK.json` records actual
prepare/verify calls for the 126/32/10 matrices, with `CurrentRuntime.run`
replaced by an exception guard. The helper is copied into all three source
snapshots; final post-hoc MANIFEST matches SEAL. No summary or COMPLETE marker
exists in these prepare-only outputs. All 150 copied live files still match
`BASELINE.json`.

Job conditions match v1. The 126 sensitivity jobs explicitly gain the current
default `config.slack_mode=dag`; all other serialized job values are identical.
The 32 capacity and ten diagnostic jobs are byte-value identical. Profile files
are byte-identical and decoded workloads are identical. Exact raw config
differences are recorded in `VALIDATION.json`; these checks do not describe
corrected-domain simulation results or provide additional statistical samples.

The first integration attempt stopped before freezing because its prior path
was outside the isolated root. The harness now copies the pinned priors into
the isolated tree. `ATTEMPT1.txt` and the empty first-attempt output preserve
that setup correction. No campaign parameter changed.

After the parent authorizes live edits, from the repository root:

```bash
git apply --check benchmark/AegisKV/experiments/evaluation-20260924/reviews/metadata-patch-draft/prospective-metadata.patch
git apply benchmark/AegisKV/experiments/evaluation-20260924/reviews/metadata-patch-draft/prospective-metadata.patch
PYTHONPATH=python .venv/bin/python -m pytest -q tests/aegiskv/test_evaluation_profile.py tests/aegiskv/test_evaluation_profile_metadata.py
```

Recheck the recorded before-hashes if live callers changed during external
review. Apply only the five-file patch; **do not copy the whole isolated tree**,
which intentionally retains the older runtime used for metadata preparation.
Existing frozen manifests/seals/results retain their appended timing errata.
