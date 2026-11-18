"""Replay sealed profile campaigns from frozen sources in a fresh output folder.

The original campaign is read only. Core simulator/evaluation modules always
come from its source_snapshot. Missing ancillary package/import support is
copied separately from the current tree, hashed, and explicitly disclosed.
--verify-only checks seals and imports without creating a replay or running jobs.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
CORE_PREFIXES = (
    "python/moonkvsim/aegiskv/current/",
    "python/moonkvsim/simulation/",
    "python/moonkvsim/aegiskv/evaluation_",
)
REQUIRED = (
    {
        "python/moonkvsim/aegiskv/current/" + name + ".py"
        for name in ("__init__", "__main__", "model", "policy", "runtime", "tracker", "workload")
    }
    | {
        "python/moonkvsim/aegiskv/evaluation_" + name + ".py"
        for name in ("campaign", "profile", "workload")
    }
    | {
        "python/moonkvsim/simulation/" + name + ".py"
        for name in (
            "__init__",
            "event",
            "global_des",
            "flow_des",
            "network",
            "ledger",
            "transaction",
        )
    }
    | {"python/moonkvsim/common/hash.py"}
)

# A fresh isolated interpreter installs this finder before any MoonKVSim import.
# It prevents an editable install from silently supplying missing core modules.
BOOTSTRAP = """from __future__ import annotations
import argparse, hashlib, importlib.abc, importlib.machinery, importlib.metadata
import json, platform, sys
from pathlib import Path

TREE = Path(__file__).resolve().parent
PACKAGE = TREE / "python"
sys.path.insert(0, str(PACKAGE))

class FrozenOnly(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "moonkvsim" or fullname.startswith("moonkvsim."):
            spec = importlib.machinery.PathFinder.find_spec(fullname, path or [str(PACKAGE)])
            if spec is None or spec.origin is None:
                raise ModuleNotFoundError("missing isolated module: " + fullname)
            if not Path(spec.origin).resolve().is_relative_to(PACKAGE):
                raise ImportError("module escaped isolated package: " + fullname)
            return spec
        return None

sys.meta_path.insert(0, FrozenOnly())
from moonkvsim.aegiskv import evaluation_campaign

def imported_sources():
    sources = {}
    for name, module in sorted(sys.modules.items()):
        if name == "moonkvsim" or name.startswith("moonkvsim."):
            path = Path(module.__file__).resolve()
            if not path.is_relative_to(PACKAGE):
                raise ImportError("import escaped frozen tree: " + name)
            sources[str(path.relative_to(TREE))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return sources

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path)
    parser.add_argument("--imports", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    if args.out is not None:
        evaluation_campaign.run(args.out, args.workers, args.limit)
    distributions = importlib.metadata.packages_distributions()
    external = set()
    for name in sys.modules:
        if name.split(".")[0] != "moonkvsim":
            external.update(distributions.get(name.split(".")[0], ()))
    report = dict(
        python=platform.python_version(),
        imported_package_sources=imported_sources(),
        installed_import_dependency_versions={
            n: importlib.metadata.version(n) for n in sorted(external)
        },
        namespace_guard="all MoonKVSim imports must resolve inside isolated physical copy",
    )
    args.imports.write_text(json.dumps(report, indent=2, sort_keys=True) + "\\n")
"""


def sha(path):
    hasher = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024**2), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def read(path):
    return json.loads(Path(path).read_bytes())


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def relative_path(root, relative):
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"unsafe relative artifact path: {relative}")
    target = root / path
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"artifact escapes its root: {relative}")
    return target


def core(relative):
    return relative.startswith(CORE_PREFIXES) or relative == "python/moonkvsim/common/hash.py"


def verify_artifacts(campaign):
    manifest, plan = read(campaign / "MANIFEST.json"), read(campaign / "PLAN.json")
    sources = manifest["source_sha256"]
    if not sources.keys() >= REQUIRED:
        raise ValueError(
            "required frozen sources absent: " + str(sorted(REQUIRED - sources.keys()))
        )
    controls = manifest.get("control_sha256", {})
    if not {"PLAN.json", "PRIORS.json"} <= controls.keys():
        raise ValueError("replay requires sealed PLAN.json and PRIORS.json")
    for relative, expected in sources.items():
        if sha(relative_path(campaign / "source_snapshot", relative)) != expected:
            raise ValueError(f"frozen source hash mismatch: {relative}")
    for bindings in (controls, manifest["profile_sha256"]):
        for relative, expected in bindings.items():
            if sha(relative_path(campaign, relative)) != expected:
                raise ValueError(f"frozen artifact hash mismatch: {relative}")
    if len({job["id"] for job in plan["jobs"]}) != len(plan["jobs"]):
        raise ValueError("duplicate planned run IDs")
    for job in plan["jobs"]:
        if Path(job["id"]).name != job["id"] or job["id"] in ("", ".", ".."):
            raise ValueError("unsafe run ID")
        if job["workload"] not in plan["workloads"]:
            raise ValueError("planned workload is absent")
        if f"profiles/{job['model']}.json" not in manifest["profile_sha256"]:
            raise ValueError("planned profile lacks frozen hash")
    for workload in plan["workloads"].values():
        path = relative_path(campaign, workload["path"])
        if sha(path) != workload["sha256"]:
            raise ValueError(f"workload artifact mismatch: {path}")
        data = gzip.decompress(path.read_bytes()) if path.suffix == ".gz" else path.read_bytes()
        if hashlib.sha256(data).hexdigest() != workload["content_sha256"]:
            raise ValueError(f"workload content mismatch: {path}")
    return manifest, plan


def copy_file(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def supplement_paths(manifest):
    # These files only make old module imports work. They never replace the
    # frozen current/simulation/evaluation implementation or common hash helper.
    for path in sorted((ROOT / "python/moonkvsim").rglob("*.py")):
        relative = str(path.relative_to(ROOT))
        if relative not in manifest["source_sha256"] and not core(relative):
            yield relative, path


def build_tree(campaign, manifest, tree, *, support=None):
    for relative, expected in manifest["source_sha256"].items():
        target = relative_path(tree, relative)
        copy_file(relative_path(campaign / "source_snapshot", relative), target)
        if sha(target) != expected:
            raise ValueError(f"source changed during copy: {relative}")
    supplements = {}
    if support is None:
        inputs = supplement_paths(manifest)
    else:
        inputs = ((str(p.relative_to(support)), p) for p in sorted(support.rglob("*.py")))
    for relative, source in inputs:
        if core(relative) or relative in manifest["source_sha256"]:
            raise ValueError(f"supplement attempted to override frozen source: {relative}")
        target = relative_path(tree, relative)
        copy_file(source, target)
        supplements[relative] = sha(target)
    (tree / "_frozen_bootstrap.py").write_text(BOOTSTRAP)
    return supplements


def call_frozen(tree, imports, *, out=None, workers=1, limit=None):
    command = [sys.executable, "-I", str(tree / "_frozen_bootstrap.py"), "--imports", str(imports)]
    if out is not None:
        command += ["--out", str(out), "--workers", str(workers)]
        if limit is not None:
            command += ["--limit", str(limit)]
    subprocess.run(command, cwd=tree, check=True)
    return read(imports)


def validate_import_report(report, manifest, supplements):
    expected = {**manifest["source_sha256"], **supplements}
    for relative, actual in report["imported_package_sources"].items():
        if actual != expected.get(relative):
            raise ValueError(
                f"executed import did not match frozen or supplemental hash: {relative}"
            )
        if core(relative) and relative not in manifest["source_sha256"]:
            raise ValueError(f"core module was not from frozen snapshot: {relative}")


def copy_campaign(campaign, out, manifest, plan):
    if out.exists() or out.is_symlink():
        raise FileExistsError(f"replay destination must not exist: {out}")
    if out.resolve().is_relative_to(campaign.resolve()):
        raise ValueError("replay destination must be outside the original campaign")
    out.mkdir(parents=True)
    files = {"MANIFEST.json", *manifest["control_sha256"], *manifest["profile_sha256"]}
    files.update(w["path"] for w in plan["workloads"].values())
    for relative in sorted(files):
        copy_file(relative_path(campaign, relative), relative_path(out, relative))
    for relative in manifest["source_sha256"]:
        copy_file(
            relative_path(campaign / "source_snapshot", relative),
            relative_path(out / "source_snapshot", relative),
        )
    (out / "runs").mkdir()


def compare_replay(campaign, out):
    comparisons = []
    for row in read(out / "RUNS.json"):
        original = campaign / "runs" / row["id"]
        old_marker = original / "COMPLETE.json"
        value = dict(id=row["id"])
        if old_marker.exists():
            old = read(old_marker)
            expected = sha(original / "summary.json")
            if old.get("summary_sha256") != expected:
                raise ValueError("original completed summary no longer matches its own marker")
            value.update(
                reference_available=True,
                reference_sha256=expected,
                replay_sha256=row["summary_sha256"],
                byte_identical=expected == row["summary_sha256"],
            )
        else:
            value["reference_available"] = False
        comparisons.append(value)
    return comparisons


def replay(campaign, out=None, *, workers=1, limit=None, verify_only=False):
    campaign = Path(campaign).resolve()
    manifest, plan = verify_artifacts(campaign)
    if workers < 1 or (limit is not None and limit < 1):
        raise ValueError("workers/limit must be positive")
    if not verify_only and out is None:
        raise ValueError("--out is required except with --verify-only")
    if not verify_only:
        out = Path(out).resolve()
        if out.exists() or out.is_relative_to(campaign):
            raise FileExistsError(
                "replay destination must be new and outside the original campaign"
            )
    with tempfile.TemporaryDirectory(prefix="aegiskv-frozen-replay-") as temporary:
        tree = Path(temporary)
        supplements = build_tree(campaign, manifest, tree)
        preflight = call_frozen(tree, tree / "PREFLIGHT_IMPORTS.json")
        validate_import_report(preflight, manifest, supplements)
        if verify_only:
            return dict(
                status="VERIFIED",
                planned_runs=len(plan["jobs"]),
                executed_runs=0,
                frozen_sources=len(manifest["source_sha256"]),
                ancillary_supplement_sources=len(supplements),
                imported_sources=len(preflight["imported_package_sources"]),
                campaign_modified=False,
            )
        copy_campaign(campaign, out, manifest, plan)
        for relative in supplements:
            copy_file(tree / relative, out / "replay_support" / relative)
        copy_file(Path(__file__), out / "REPLAY_LAUNCHER.py")
        (out / "FROZEN_BOOTSTRAP.py").write_text(BOOTSTRAP)
        write(
            out / "REPLAY_MANIFEST.json",
            dict(
                schema="aegiskv.frozen-profile-replay.v1",
                original_campaign=str(campaign),
                original_manifest_sha256=sha(campaign / "MANIFEST.json"),
                core_sources="original immutable source_snapshot; no live core fallback",
                supplement_origin=str(ROOT),
                supplement_sha256=supplements,
                supplement_scope=(
                    "ancillary import support only; current/simulation/evaluation excluded"
                ),
                supplement_limit=(
                    "not originally frozen; exact current copies are separately hashed and retained"
                ),
                launcher_sha256=sha(Path(__file__)),
                bootstrap_sha256=sha(out / "FROZEN_BOOTSTRAP.py"),
                workers=workers,
                limit=limit,
                original_planned_jobs=len(plan["jobs"]),
                preflight=preflight,
            ),
        )
        # Re-check the copy. The frozen runner then independently verifies its
        # ROOT-relative source hashes in the isolated tree before scheduling.
        verify_artifacts(out)
        try:
            imported = call_frozen(
                tree, out / "REPLAY_IMPORTS.json", out=out, workers=workers, limit=limit
            )
            validate_import_report(imported, manifest, supplements)
            comparisons = compare_replay(campaign, out)
            status = read(out / "STATUS.json")
            result = dict(
                status="COMPLETE" if status["complete"] else "PARTIAL",
                completed_runs=status["completed_runs"],
                planned_runs=status["planned_runs"],
                comparisons=comparisons,
                original_campaign_modified=False,
            )
            if any(r.get("byte_identical") is False for r in comparisons):
                result["status"] = "MISMATCH"
            write(out / "REPLAY_RESULT.json", result)
            if result["status"] == "MISMATCH":
                raise RuntimeError(
                    "replayed summary differs from completed original; see REPLAY_RESULT.json"
                )
            return result
        except Exception as error:
            write(out / "REPLAY_FAILED.json", dict(type=type(error).__name__, message=str(error)))
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    result = replay(
        args.campaign,
        args.out,
        workers=args.workers,
        limit=args.limit,
        verify_only=args.verify_only,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
