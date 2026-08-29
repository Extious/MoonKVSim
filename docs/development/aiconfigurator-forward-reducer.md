# AIConfigurator physical-forward offline reducer

`scripts/physical/reduce_aiconfigurator_forward_calibration.py` consumes one
successfully published raw forward bundle and creates a new no-clobber reduced
bundle. It does not execute vLLM, AIConfigurator, CUDA, Slurm, or MoonKVSim.

The reducer rejects a bundle unless all source files are regular files covered
by both `SHA256SUMS` and `manifest.json`, `PUBLICATION_COMPLETE.json` is valid,
the source/model/GPU checks passed, the raw and scheduler-metadata streams have
the exact planned order, and the frozen split matches the pre-measurement
algorithm. JSON scalar types are checked exactly (a Boolean cannot substitute
for an integer). The reducer holds the initially hash-verified source bytes as
an immutable snapshot, materializes copies from that snapshot, and aborts if
the published source bundle changes before output publication. Warm-ups are
validated but excluded from fitting and residuals.

The checked-in method is frozen in
`configs/physical/aiconfigurator/qwen3-8b-l40s-native-40960/reducer-config.json`:

- each train shape is reduced with an integer median;
- each held-out prediction uses the nearest train shape in the same phase under
  the predeclared normalized three-axis distance;
- train and held-out shape IDs must be disjoint;
- mixed measurements are published separately and are never fitted, decomposed,
  used to define phase-residual buckets, or used as prefill/decode evidence;
- the original numerical thresholds are copied byte-for-byte, then rebound to
  the fully materialized profile identity without changing their values.

Run it only after a successful numeric physical bundle exists:

```bash
uv run python scripts/physical/reduce_aiconfigurator_forward_calibration.py \
  --input-bundle benchmark/physical/aiconfigurator-vllm-forward/<job-id> \
  --output-root benchmark/physical/aiconfigurator-vllm-forward/<job-id>-reduced \
  --reducer-config \
    configs/physical/aiconfigurator/qwen3-8b-l40s-native-40960/reducer-config.json
```

`profile-selection.json` is emitted only when independent prefill and decode
coverage exists, both held-out thresholds pass, and the exact hardware/profile
binding is intact. Otherwise the reducer emits only
`profile-candidate.json` plus a fail-closed `PRELIMINARY_ONLY` report. For unit
fixtures, `--fixture-mode` is mandatory and unconditionally prevents formal
selection output.

The requested output leaf is never resolved through a symlink after the
initial check. Publication creates that exact leaf atomically, writes the
incomplete marker exclusively, verifies the complete checksum inventory, and
refuses any existing or concurrently populated destination. The database and
reduction-report schemas also reject self-authorizing databases and internally
inconsistent formal/preliminary or fixture status combinations.

Even a valid physical-forward selection is component-level E3 evidence for the
measured native-40,960 L40S profile and covered shape range. It is not E4
end-to-end validation, 128K/YaRN validation, an AegisKV result, or paper-ready
evidence.
