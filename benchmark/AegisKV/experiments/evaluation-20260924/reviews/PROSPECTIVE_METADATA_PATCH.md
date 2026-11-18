# Prospective timing metadata patch proposal

**Proposal only. No live source, frozen source, manifest, seal or result is changed.**
The external candidate review is reading the current files. Apply a separately
reviewed patch only after that read finishes. Existing campaigns keep their
[appended timing errata](TIMING_METADATA_REVIEW.md); this proposal concerns new
`prepare` executions and their new output directories.

## Smallest safe change

Keep `current.__main__.manifest()` generic: it is also used by genuine
constant-ns/token mechanism runs, so changing its default `timing` to AIC would
create a new mislabeling. Override the fields at the three profile campaign
call sites, after all job configurations exist and before the final manifest
write and any seal creation.

| Live runner | Current location | Proposed insertion |
|---|---|---|
| `run_sensitivity_campaign.py` | `prepare`: `source = manifest(out)`, source snapshot/update, final `write_json(out / "MANIFEST.json", source)` | After existing `source.update(...)`, merge profile metadata from `GridDurationProfile(saved_profile)` and **every** `job["config"]`; keep final manifest/control hashes in their existing order. |
| `run_capacity_slack_ablation.py` | `prepare`: `source_manifest = shared.manifest(out)`, snapshot/update, final `shared.write_json(...)` | Merge profile metadata from `GridDurationProfile(out / parent["profile"])` and the 32 new job configs before the final write. Do not copy the parent campaign's generic timing description. |
| `run_slack_mechanism_diagnostic.py` | `prepare`: `source = manifest(out)`, snapshot/update, final manifest write followed by `SEAL.json` | Use the existing local `profile` object and all 10 job configs. Merge before writing MANIFEST, then compute the original three SEAL entries from those final files. |

The factory currently writes an intermediate manifest before the runner
overrides it. The authoritative sealed file is the runner's final write;
changing this factory lifecycle is unnecessary for this patch.

## Low-risk common helper

Recommended: one pure function in
`python/moonkvsim/aegiskv/evaluation_profile.py`, for example
`profile_manifest_fields(profile, configs) -> dict`. All three runners already
import `GridDurationProfile`, and each copies all `python/moonkvsim/**/*.py`
into its frozen tree. This location adds no unsnapshotted script dependency.
Avoid a new sibling script helper unless all snapshot lists are also updated.

Suggested contract:

```python
def profile_manifest_fields(profile: GridDurationProfile, configs) -> dict:
    # configs is the complete sequence of serialized job configurations.
    # Produce a new JSON-compatible mapping; do not mutate any input.
    levels = sorted({float(c["compute_dma_slowdown"]) for c in configs})
    # Reject empty/nonfinite/negative levels; Config already validates jobs.
    return {
        "timing": (
            f"{profile.data['timing_evidence']} via GridDurationProfile; "
            "bounded prefix/extend interpolation and per-token decode summation; "
            "shared weighted max-min fair byte-flow DES"
        ),
        "duration_profile": "GridDurationProfile",
        "duration_profile_metadata": {
            # Copy the pinned model, revision, TP, hardware, batch-size,
            # backend/database tags, interpolation and calibrated fields.
            # These describe the input table, not physical serving execution.
        },
        "foreground_dma_compute_interference": (
            "configured compute-event-start slowdown when same-worker/rank "
            "H2D or D2H is active; levels recorded below; not calibrated"
            if any(levels)
            else "disabled by compute_dma_slowdown=0; not measured zero overhead"
        ),
        "compute_dma_slowdown_values": levels,
    }
```

This is a proposed interface sketch, not a ready-to-apply implementation.
The metadata dictionary should copy explicit keys rather than the full table:
`model`, `revision`, `tp`, `hardware`, `batch_size`, `backend`,
`backend_version`, `database_mode`, `interpolation`, `calibrated`, and
`physical_execution`. Keep existing profile hashes and source/control sealing
unchanged. Do not infer calibration or actual vLLM execution from backend tags.
Do not change `evidence_class`, `paper_ready`, the profile values or runtime
configuration. Sensitivity's `prediction_multiplier` changes its predictor,
not the service profile, and must not be folded into timing metadata as a
service-cost scale.

Each caller then merges the returned fields, conceptually:

```python
source.update(profile_manifest_fields(profile, [job["config"] for job in jobs]))
```

Sensitivity and capacity may instantiate the helper's profile from the already
copied table. This is bounded JSON/grid validation during preparation, not DES
execution or a model run. Use a direct import of the helper in each runner;
do not depend on accidental exposure through `shared` module internals.

An even smaller textual patch could duplicate two `source.update` fields at
each site. That fixes the immediate error but leaves three independent copies
of the same condition-dependent DMA description. The pure helper above is the
preferred small shared change; no runtime/Tracker/policy edit is required.

## Minimal validation after approval to edit

1. Test the helper with a tiny existing grid fixture and slowdown sets `{0}`,
   `{0, .05, .1}`. Verify deterministic sorted levels, JSON serialization,
   profile tag propagation, no input mutation, and rejection of invalid input.
2. Add a lightweight preparation contract check for each runner: merged fields
   must be present **before** the final manifest is hashed; post-hoc SEAL must
   hash that final file. For sensitivity, the helper must see all jobs, not
   merely the center config. Existing profiles and job values must be unchanged.
3. Run focused metadata/profile tests and ruff. No DES or 126/32/10 rerun is
   needed to validate these descriptive fields. If testing `prepare` uses the
   actual workload, isolate it in a fresh temporary directory and label it
   unexecuted; never prepare over an existing campaign.

Expected descriptions: sensitivity lists `[0.0, 0.05, 0.1]`; capacity and
post-hoc list `[0.0]`; all three identify `GridDurationProfile` with the pinned
HYBRID table and `calibrated=false`. The old frozen runners and manifests must
not acquire these fields retroactively. Formal and structural already override
their timing descriptions; migrating those callers is outside this minimal fix.
The standalone current CLI also has its own metadata path and is outside the
three-runner scope of this proposal.

## Read-only inspection basis

The runtime selects its constant-token branch only when
`duration_profile is None`; otherwise `_duration` calls the supplied profile.
`_compute_delay` adds the configured fraction only when an H2D/D2H flow on the
current worker's rank is active at the compute-event start. Both facts were
checked directly in live code and in the preceding frozen-source review.
No reviewed reader or test requires the inherited generic timing string;
keeping it a string and adding structured fields preserves the current shape.

SHA-256 at proposal review (later live edits require a fresh diff check):

| File | SHA-256 |
|---|---|
| `evaluation_profile.py` | `d1a8c1919b9478c2119037f37db793cd38a386f66019df0df42944710b336f2b` |
| `current/__main__.py` | `1b1bf25408f69bd48a989a97dc5a0967cf4430f4da303f2cf635e58d26fdfacf` |
| `current/runtime.py` | `9afc8e74ec1e206cca9b05ae75ae1ffee757a2d0e3e4e76498dbc7addef0d98a` |
| `run_sensitivity_campaign.py` | `ec7539c74450279bf0676fb3db7910e9d995101712cfaa2d62556ee770a5dff1` |
| `run_capacity_slack_ablation.py` | `9f490e895a74689637912dc46982e4f071dde40fc3539883b7daf75062ba8137` |
| `run_slack_mechanism_diagnostic.py` | `98956019f4bbdabdeafb338c53b6300a40803609007ca7448870fcaff4053e5a` |
