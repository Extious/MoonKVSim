# Vanilla Mooncake + vLLM physical component

This directory owns the small, pinned, two-RTX4090 Vanilla baseline path. It
does not enable AegisKV policy and does not modify or consume the dirty AegisKV
Mooncake wheel installed in the pinned vLLM environment.

The physical topology is two independent TP=1 vLLM servers. Both use the
upstream `MooncakeStoreConnector` with `kv_role=kv_both`, a fixed
`PYTHONHASHSEED=0`, TCP transport, and embedded DRAM segments. The Mooncake
master's embedded HTTP endpoint is metadata control plane only; all KV payloads
remain in the TCP/embedded-DRAM data path. `enable_offload=false`, and SSD,
NVMe, NVMe-oF, standalone Store, and file-storage keys are rejected before
model import or launch.

## Evidence boundary

A successful request run is capped at
`E3_SMALL_SCALE_PHYSICAL_COMPONENT`. It proves a clean Mooncake physical
cross-instance path when all of the following agree:

- server A reports a successful `save_put` with nonzero bytes;
- server B, which has never seen that prompt, reports successful
  `lookup_exists` and `load_get` operations with nonzero bytes and no failed
  keys;
- the matched reuse request computes fewer prompt KV tokens than the
  equal-length cold reference on server B;
- every measured case binds exactly one completed-request queue, prefill,
  inference, computed-token, and engine-E2E observation.

The artifact also reports client E2E and a forward-path residual computed as
vLLM prefill time minus the instrumented `load_get` RPC span. These spans are
not additive: external lookup and asynchronous Store work can overlap vLLM
request phases.

This is not an E4 result. E4 remains blocked until the same cases have a
matched MoonKVSim run and the forward/KV-I/O/queue/E2E component errors are
computed against the physical observations. Import success, server startup,
or a physical-only decomposition never satisfies that gate. Results are also
preliminary, single-node, two-GPU, and not paper-ready.

## Clean build

The build helper reconstructs Mooncake exclusively from Git objects at
`f161118c18dbea1b56dd5c7908b9eaa440353e2e`, including the pinned pybind11 and
yalantinglibs submodule objects. It cross-checks the supplied clean archive at
`/tmp/moonkvsim-mooncake-f161118.45Cs3n`, records regular-file modes and
symlink modes/targets in `source-tree-manifest.json`, and builds with CUDA 12.8
for SM89. HTTP metadata support is enabled, but etcd, Redis, SSD/NVMe-oF,
standalone Store, Rust Store, and AegisKV changes are disabled or absent.

The build environment is an isolated fresh directory. `pip`, `build`, `wheel`,
`auditwheel`, and `setuptools` are exact-version inputs. A constraints file
also binds the unversioned upgrade performed by the upstream wheel helper and
its PEP-517 build environment. Pre/post wheel freezes and the hashes/versions
of Python, uv, CMake, GCC, G++, NVCC, and the exact hash-pinned `patchelf`
binary used by `auditwheel` are included in the build manifest.
Neither the dirty Mooncake checkout nor the pinned vLLM virtual environment is
installed into or modified.

The upstream helper first repairs against the conservative
`manylinux_2_34_x86_64` policy. Because the execution hosts use glibc 2.28 and
the GCC 11 C++ ABI is supplied by the frozen runtime bundle, that intermediate
tag is not installable on the target host. The final wheel is therefore
explicitly and honestly retagged `linux_x86_64`; both pre-retag and final
filenames/hashes are recorded. This is a cluster-local physical artifact, not
a portable manylinux release.

Example, using fresh paths:

```bash
uv run python scripts/physical/vanilla_mooncake_clean_build.py \
  --work-root /tmp/moonkvsim-vanilla-clean-build.WORK \
  --output-dir /tmp/moonkvsim-vanilla-clean-build.OUT
```

The final output directory appears only after an atomic rename and contains
`PUBLICATION_COMPLETE.json`, `build-manifest.json`, the wheel, raw build logs,
`CMakeCache.txt`, the source-tree manifest, the tool freeze, and
`SHA256SUMS`. Because upstream wheel repair intentionally excludes several
native dependencies, the bundle also contains a symlink-free
`native-runtime/` library tree plus a byte- and mode-exact
`native-runtime-manifest.json`. The physical wrapper puts that tree and its
libibverbs provider subdirectory in an exact, non-inherited `LD_LIBRARY_PATH`.
The tree includes the pinned CUDA 12 and GCC 11 runtimes. The build also runs
`readelf` and `ldd` over every final-wheel ELF, rejects CUDA 13, absolute/build
RPATHs, unresolved libraries, and non-allowlisted system resolution, and saves
the result as `elf-runtime-audit.json`. The preflight recomputes the runtime
tree and binds both audit and manifest hashes. A failed build remains under a
hidden staging name with
`BUILD_INCOMPLETE` and `build-failure.json`; it must not be used.

Before a physical submission, a verified successful bundle must be copied and
atomically published as this directory's `clean-build/`. No copy is consumable
without a passing `sha256sum --check --strict SHA256SUMS` and a complete marker.

## Physical preflight and submission

`scripts/physical/vanilla_mooncake_e4_preflight.py` creates the required,
fresh, no-clobber submission record. It verifies the clean-build checksum
inventory, exact source hashes and resource directives, protected-job
observations, gpu10's advertised GPUs/free memory/current jobs, and
`sbatch --test-only`. It performs no submission or scheduler mutation. Run it
to a shared, non-repository path after the clean bundle and repository source
snapshot are frozen:

```bash
uv run python scripts/physical/vanilla_mooncake_e4_preflight.py \
  --clean-build /shared/frozen/moonkvsim-vanilla-clean-build \
  --output /shared/frozen/moonkvsim-vanilla-submission-preflight.json
```

`scripts/physical/run_vanilla_mooncake_e4.sbatch` is pinned to an exclusive
`gpu10` allocation with two RTX4090 GPUs. Its first GPU action records
`nvidia-smi` inventory and fails closed if either assigned device already has a
compute process. After teardown it fails the run if either GPU still has a
compute process. It never kills, cancels, requeues, releases, or changes any
unowned process or Slurm job. In particular, jobs `136567`, `135889`, `135847`,
and `135326` must remain present and PENDING in `squeue`. Jobs `142290` and
`142291` are read-only monitored experiments: they may naturally run, finish,
or leave `squeue`, but each pre/post observation must have a root-job `sacct`
record. No pre/post state equality is required, and none of the six jobs is
mutated.

Before `sbatch`, record an immutable submission JSON containing at least:

- SHA-256 of the exact sbatch file, harness, schema, clean wheel, clean-build
  manifest, native-runtime manifest, ELF-runtime audit, and clean-build
  `SHA256SUMS`;
- the complete `sbatch --test-only`/requested job configuration;
- current `squeue` rows for the protected jobs, `sacct` rows for the two
  read-only monitored jobs, and the queue on `gpu10`;
- `sinfo` and `scontrol show node gpu10` output;
- the intended command, submit directory, user, and UTC timestamp.

Only after that record passes review may the job be submitted from the
repository root. The clean bundle and preflight record must be on a path shared
with gpu10 and are bound to the submitted source hashes inside the job:

```bash
sbatch \
  --export=ALL,MOONKVSIM_CLEAN_BUILD_DIR=/shared/frozen/moonkvsim-vanilla-clean-build,MOONKVSIM_PREFLIGHT_RECORD=/shared/frozen/moonkvsim-vanilla-submission-preflight.json \
  scripts/physical/run_vanilla_mooncake_e4.sbatch
```

Each numeric run directory is atomically published and must contain
`PUBLICATION_COMPLETE.json`, the Slurm-spooled submitted script, source/build/
wheel hashes, a successful native extension import plus `LD_DEBUG=libs` loader
trace, raw master and vLLM logs, GPU pre/post records, requests and raw
responses, raw Prometheus snapshots, per-request metric deltas, `result.json`,
schema validation logs, protected-job snapshots, and `SHA256SUMS`. A directory
with `PUBLICATION_INCOMPLETE`, a failed checksum, a failed schema validation, or
`result.status != PASS` is not physical component evidence.
