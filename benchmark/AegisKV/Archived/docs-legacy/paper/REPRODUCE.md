# Reproducing the revised study

> 当前算法 2/3 已修订为 revision 3。本文原有测试、构建/交付与实验数据是旧版记录；最新范围见 [修订说明](ALGORITHM_REVISION_V3.md) 和 [发布状态](REVISION_STATUS.json)。旧 PASS 不覆盖当前 PDF 或新算法的运行性能。

The current manuscript is `benchmark/AegisKV/paper/main.tex`. Figures and all
LaTeX sections are under `paper/figures/` and `paper/sections/`; tools are in
`benchmark/AegisKV/experiments/scripts/paper/`, data and build outputs in
`benchmark/AegisKV/experiments/results/paper/`, and this documentation in
`benchmark/AegisKV/docs/paper/`. All commands below use the repository root
unless explicitly stated otherwise.

The execution source is `output/paper-simulation-8b/20260906-alignment/source-v2`.
`SOURCE_SNAPSHOT.json` hashes its 383 execution inputs, including the actual
previously untracked code, configuration, workload and reference plans. The
mutable workspace and all older campaigns are separate. This is CPU-only
simulation; it neither executes Qwen inference nor requires GPUs.

## Environment and measured runs

`benchmark/AegisKV/experiments/results/paper/data/environment.json` records the execution/analysis environment: CPython
3.12.12, NumPy 2.5.2, Matplotlib 3.11.1, PyMuPDF 1.28.2 and pytest 8.4.2.
The snapshot includes `pyproject.toml` and `uv.lock`; `uv sync --frozen --extra
dev --extra paper` installs the locked project dependencies. PyMuPDF is a
separate PDF-review dependency. Use the recorded analysis versions when
reconstructing the delivered visual outputs.

From the frozen source, with its environment activated:

```bash
PYTHONPATH=python PYTHONDONTWRITEBYTECODE=1 python \
  benchmark/AegisKV/experiments/scripts/run_mooncake_aligned_paper.py \
  --output /absolute/path/to/a-new-campaign --jobs 4
```

Worker count affects wall time, not virtual simulation time. The delivered
campaign used 48 workers on a large-memory CPU host; one observed snapshot
occupied about 508 GiB across the parent and workers, with the largest worker
at 12.1 GiB. Use fewer workers when memory is limited. Keep substantial disk
space for compressed raw events; summary JSON is not a substitute for them.

The 170 measured cells cover six arms in the base setting, concurrency 8/32,
service composition beta 0.5/1, 5 GB/s bandwidth, and two sequential failures.
Each run executes all 160 tasks and 1,304 calls. Five admission seeds repeat
across settings; this is not 170 independent statistical samples.

Twenty logical plans are frozen under `reference/aligned-logical-plans-v1`.
Their import manifest binds the original unprotected reference executions,
which never invoke the protection gate corrected between v1 and v2. V1
measured outcomes are invalidated; none is reused. The fault's logical token
threshold is interpolated inside its crossing forward step, while protection
can read only buffers from completed steps.

After execution, independently reload and audit all raw artifacts:

```bash
AEGIS_SOURCE="$PWD"
PYTHONPATH="$AEGIS_SOURCE/python:$AEGIS_SOURCE/benchmark/AegisKV/experiments/scripts" \
  PYTHONDONTWRITEBYTECODE=1 python ../verification-v1/verify_mooncake_aligned_paper.py \
  --output /absolute/path/to/the-campaign --jobs 4 --phase verify
```

The separate verification adapter fixes one protocol reload comparison:
JSON arrays must compare with canonicalized Python tuples/lists. Its manifest
records the exact one-line diff and both script hashes. The original frozen
execution source and every measured output remain unchanged. The first failed
verification-start log is retained. This adapter is also needed when resuming
an existing campaign with the original frozen runner.

`ACCEPTANCE.json` must report all 170 runs. Analysis then runs from the active
workspace, with the delivered analysis script:

```bash
mkdir -p benchmark/AegisKV/experiments/results/paper/figures
.venv/bin/python benchmark/AegisKV/experiments/scripts/analyze_mooncake_aligned_paper.py \
  --campaign output/paper-simulation-8b/20260906-alignment/campaign-v2 \
  --paper benchmark/AegisKV/experiments/results/paper
.venv/bin/python benchmark/AegisKV/experiments/scripts/build_aligned_workload_figures.py
```

The result generator verifies acceptance and pairing before reconstructing
contrasts. The descriptive generator binds the frozen workload and copied
physical calibration file; those measurements never substitute for simulated
results. `benchmark/AegisKV/experiments/results/paper/data/aligned-statistics.json` includes the five seed observations,
absolute endpoints, physical fault targets/times, focus-workflow traces and
input hashes.

## Regression and native conformance

The exact commands and file hashes are recorded in `TEST_VALIDATION.json` at
the alignment output root. Targeted tests are:

```bash
PYTHONPATH=python python -m pytest -q \
  tests/aegiskv/test_mooncake_alignment.py \
  tests/aegiskv/test_formal_algorithm_audit.py \
  tests/aegiskv/test_slack_landlord.py tests/aegiskv/test_experiment_config.py \
  tests/aegiskv/test_recovery_harm.py tests/aegiskv/test_hbm_quota_aimd.py
```

The related regression covers `test_experiment.py`,
`test_experiment_hbm_authority.py`, `test_recovery_planner.py` and
`test_formal_algorithm_audit.py`. The two suites overlap; do not add their
counts to claim unique test coverage. The archival WEKA fixture used only by
regression tests is stored under `test-support/` with its own manifest. To
repeat those tests in a disposable extracted source tree, place that fixture
at `benchmark/AegisKV/experiments/workloads/weka-e2-two-workflow-shapes.jsonl`.
It is not an input to the paper's 160-workflow experiment. An earlier attempt
without this fixture is preserved as a failed setup log; the final run loads
the frozen Python code with the verified fixture present.

The native harness compiles the actual Mooncake Controller. In the source
bundle, `mooncake-reference/` contains the hash-verified dirty-reference files;
its Git HEAD alone is insufficient provenance.

```bash
PYTHONPATH=python python \
  benchmark/AegisKV/experiments/scripts/check_mooncake_controller_alignment.py \
  --mooncake-root /path/to/mooncake-reference --output-dir /new/native-check
```

The separate gate harness extracts and executes the reference finalizer's
exact Python method, with logging and storage-ID formatting stubs. It checks
six outcome/retry sequences. Neither harness validates full physical data
movement or calibrates hardware performance.

## Manuscript and editable figures

From the repository root:

```bash
sh benchmark/AegisKV/paper/build.sh
```

The paper source ZIP preserves these paths and includes the bundled ACM class,
BibTeX style and generated bibliography. To rebuild the **current** figures
from the bundled, frozen plotting inputs (without rerunning simulations), run
from the repository root:

```bash
python benchmark/AegisKV/experiments/scripts/paper/render_submission_figures.py
python benchmark/AegisKV/experiments/scripts/paper/build_submission_diagrams.py \
  --cli /path/to/drawio
```

The second command uses official Draw.io Desktop 31.1.5, with a virtual display
on headless Linux; the local wrapper is `.codex/skills/drawio/scripts/drawio-cli`.
Install the Cantarell font used by the native diagrams. Matplotlib uses its
bundled DejaVu Sans. Draw.io exports native PNG/PDF with embedded XML; PyMuPDF
normalizes vector pages to exactly seven inches and assembles the three-panel
Motivation. The two statistical Motivation panels are editable Python/SVG;
the time-scaled workflow and both mechanism diagrams are native Draw.io.

`benchmark/AegisKV/experiments/results/paper/data/publication-figure-inputs.json` preserves the workload arrays and fifteen
accepted F1 WCT endpoint arrays with their original bindings. The existing
analysis/descriptive scripts above regenerate statistics but also write older
figure layouts; always run the new publication generators afterwards. Use
`--freeze-inputs` only when deliberately regenerating portable inputs from the
accepted local campaign. No current plotting command runs inference or new
experiments. Numerical body text is generated separately by
`write_result_sections.py` from the unchanged `aligned-statistics.json`.

Historical Motivation inputs, the old composite and its generator are preserved
under `benchmark/AegisKV/experiments/results/paper/data/motivation-real-cc/`. To independently verify its observed values:

```bash
python benchmark/AegisKV/experiments/scripts/paper/verify_motivation_trace.py \
  --trace /path/to/cc-traces-weka-062126/traces.jsonl
```

The 1.72 GiB source trace is not bundled. Obtain the identified public dataset
or use the sglsim archive path recorded in `FIGURE_REVISION.md`; verify SHA-256
`29b6a19e751ff5230771519aab755f80a0f43a4ba9cf96b72d3a6a437ec99276`.
The checker reconstructs timestamps, 124 workflow gaps and example arithmetic;
it does not rerun or calibrate the historical AIConfigurator predictions.

Render manuscript pages and all ten figures in grayscale for review.
`benchmark/AegisKV/experiments/results/paper/data/figure-manifest.json` binds generators, inputs, native components and
exports; `benchmark/AegisKV/experiments/results/paper/data/delivery-checks.json` also checks every accepted raw hash and
references the recorded visual review. This full verifier needs the local
campaign, trace and Mooncake reference; compiling the extracted paper does not.

Large raw run files remain in the local accepted campaign. The package
manifest explicitly identifies this boundary and includes their acceptance
hashes; the smaller downloadable bundles contain exact sources, workload,
plans and analysis inputs sufficient to rerun them.
