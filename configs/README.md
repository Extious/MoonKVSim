# Simulator configuration

This directory holds only MoonKVSim library inputs:

- `resolved/qwen3-8b/` — source-derived Qwen3-8B KV layouts.
- `aiconfigurator/` — AIConfigurator residual-threshold and related profile
  inputs. They are not a formal E2 predictor binding.

AegisKV experiment layers (`requests.json`, `failure.json`, `engine.json`)
live under `benchmark/AegisKV/experiments/configs/`. Vanilla real-trace
harness fixtures used by simulator tests live under
`tests/fixtures/vanilla-e2/`.
