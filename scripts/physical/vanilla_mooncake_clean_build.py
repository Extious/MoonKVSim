#!/usr/bin/env python3
"""Build an auditable, unmodified Mooncake wheel in an isolated directory.

The source is reconstructed from Git objects at the pinned commit, including
the two pinned submodules.  No file from the dirty Mooncake worktree is copied
into the build.  The caller must choose a fresh work directory and output
directory, normally below ``/tmp``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

PINNED_COMMIT: Final = "f161118c18dbea1b56dd5c7908b9eaa440353e2e"
PINNED_SUBMODULES: Final = ("extern/pybind11", "extern/yalantinglibs")
PINNED_PYTHON: Final = Path("/home/comp/zhanzhao/Mooncake/aegiskv/.venv-vllm-sm89/bin/python")
PINNED_CUDA_ROOT: Final = Path("/usr/local/cuda-12.8")
PINNED_CUDART_RELATIVE: Final = Path(
    "targets/x86_64-linux/lib/libcudart.so.12.8.90"
)
PINNED_GCC_RUNTIME_ROOT: Final = Path("/usr/local/gcc/gcc-11.2.0/lib64")
PINNED_PATCHELF: Final = Path("/usr/local/anaconda/3-2025.06/bin/patchelf")
PINNED_PATCHELF_SHA256: Final = (
    "01051885c8a15bbf3b8ca28859c277612209af1629bcd2ad6eb1d9dad6086f32"
)
PINNED_NATIVE_DEPENDENCY_SOURCE: Final = Path(
    "/home/comp/zhanzhao/Mooncake/.deps-sglang-profiler"
)
PINNED_NATIVE_DEPENDENCY_PATHS: Final = (
    "include/asio",
    "include/async_simple",
    "include/boost",
    "include/cinatra",
    "include/curl",
    "include/frozen",
    "include/iguana",
    "include/infiniband",
    "include/json",
    "include/libnl3",
    "include/msgpack",
    "include/msgpack.hpp",
    "include/numa.h",
    "include/numacompat1.h",
    "include/numaif.h",
    "include/rdma",
    "include/yaml-cpp",
    "include/ylt",
    "include/xxhash.h",
    "lib/cmake/jsoncpp",
    "lib/cmake/yaml-cpp",
    "lib/cmake/yalantinglibs",
    "lib/libjsoncpp.so",
    "lib/libjsoncpp.so.27",
    "lib/libjsoncpp.so.1.9.8",
    "lib/libcurl.so",
    "lib/libcurl.so.4",
    "lib/libcurl.so.4.8.0",
    "lib/libnghttp2.so",
    "lib/libnghttp2.so.14",
    "lib/libnghttp2.so.14.29.3",
    "lib/libssh2.so",
    "lib/libssh2.so.1",
    "lib/libssh2.so.1.0.1",
    "lib/libssl.so",
    "lib/libssl.so.3",
    "lib/libcrypto.so",
    "lib/libcrypto.so.3",
    "lib/libgssapi_krb5.so",
    "lib/libgssapi_krb5.so.2",
    "lib/libgssapi_krb5.so.2.2",
    "lib/libzstd.so",
    "lib/libzstd.so.1",
    "lib/libzstd.so.1.5.7",
    "lib/libz.so.1",
    "lib/libz.so.1.3.2",
    "lib/libkrb5.so",
    "lib/libkrb5.so.3",
    "lib/libkrb5.so.3.3",
    "lib/libk5crypto.so",
    "lib/libk5crypto.so.3",
    "lib/libk5crypto.so.3.1",
    "lib/libcom_err.so",
    "lib/libcom_err.so.3",
    "lib/libcom_err.so.3.0",
    "lib/libkrb5support.so",
    "lib/libkrb5support.so.0",
    "lib/libkrb5support.so.0.1",
    "lib/libkeyutils.so",
    "lib/libkeyutils.so.1",
    "lib/libkeyutils.so.1.10",
    "lib/libibverbs",
    "lib/libefa.so",
    "lib/libefa.so.1",
    "lib/libefa.so.1.3.58.0",
    "lib/libhns.so",
    "lib/libhns.so.1",
    "lib/libhns.so.1.0.58.0",
    "lib/libmana.so",
    "lib/libmana.so.1",
    "lib/libmana.so.1.0.58.0",
    "lib/libmlx4.so",
    "lib/libmlx4.so.1",
    "lib/libmlx4.so.1.0.58.0",
    "lib/libibverbs.so",
    "lib/libibverbs.so.1",
    "lib/libibverbs.so.1.14.58.0",
    "lib/libmlx5.so",
    "lib/libmlx5.so.1",
    "lib/libmlx5.so.1.25.58.0",
    "lib/libnl-3.so",
    "lib/libnl-3.so.200",
    "lib/libnl-3.so.200.26.0",
    "lib/libnl-route-3.so",
    "lib/libnl-route-3.so.200",
    "lib/libnl-route-3.so.200.26.0",
    "lib/libnuma.so",
    "lib/libnuma.so.1",
    "lib/libnuma.so.1.0.0",
    "lib/librdmacm.so",
    "lib/librdmacm.so.1",
    "lib/librdmacm.so.1.3.58.0",
    "lib/libyaml-cpp.so",
    "lib/libyaml-cpp.so.0.8",
    "lib/libyaml-cpp.so.0.8.0",
    "lib/libxxhash.a",
    "lib/libxxhash.so",
    "lib/libxxhash.so.0",
    "lib/libxxhash.so.0.8.3",
)
SCHEMA: Final = "moonkvsim.vanilla_mooncake_clean_build.v1"
PINNED_BUILD_PACKAGES: Final = (
    "pip==26.2.1",
    "build==1.3.0",
    "wheel==0.46.3",
    "auditwheel==6.5.0",
    "setuptools==80.10.2",
)
LOCAL_WHEEL_PLATFORM_TAG: Final = "linux_x86_64"
AUDITWHEEL_REPAIR_PLATFORM_TAG: Final = "manylinux_2_34_x86_64"
SYSTEM_RUNTIME_ALLOWLIST: Final = frozenset(
    {
        "ld-linux-x86-64.so.2",
        "libc.so.6",
        "libdl.so.2",
        "libm.so.6",
        "libpthread.so.0",
        "libresolv.so.2",
        "librt.so.1",
        "linux-vdso.so.1",
    }
)
DRIVER_RUNTIME_ALLOWLIST: Final = frozenset({"libcuda.so.1"})


class BuildError(RuntimeError):
    """A fail-closed source, toolchain, build, or artifact error."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


def write_json(path: Path, value: object) -> None:
    path.write_text(canonical_json(value), encoding="utf-8")


def run_capture(
    command: Sequence[str],
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    log_path: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    started = time.time()
    completed = subprocess.run(
        list(command),
        cwd=cwd,
        env=None if env is None else dict(env),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if log_path is not None:
        header = {
            "command": list(command),
            "cwd": None if cwd is None else str(cwd),
            "started_unix": started,
            "elapsed_seconds": time.time() - started,
            "returncode": completed.returncode,
        }
        log_path.write_text(canonical_json(header) + completed.stdout, encoding="utf-8")
    if completed.returncode != 0:
        raise BuildError(
            f"command failed ({completed.returncode}): {' '.join(command)}"
            + (f"; log={log_path}" if log_path is not None else "")
        )
    return completed


def git_output(repository: Path, *arguments: str) -> str:
    return run_capture(["git", "-C", str(repository), *arguments]).stdout.strip()


def submodule_commits(repository: Path, commit: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for relative in PINNED_SUBMODULES:
        row = git_output(repository, "ls-tree", commit, relative).split()
        if len(row) < 4 or row[0] != "160000" or row[1] != "commit":
            raise BuildError(f"{relative} is not a pinned Git submodule at {commit}")
        values[relative] = row[2]
    return values


def create_archive(repository: Path, revision: str, destination: Path) -> None:
    with destination.open("xb") as stream:
        completed = subprocess.run(
            ["git", "-C", str(repository), "archive", "--format=tar", revision],
            stdout=stream,
            stderr=subprocess.PIPE,
            check=False,
        )
    if completed.returncode != 0:
        raise BuildError(
            f"git archive failed for {repository}@{revision}: "
            f"{completed.stderr.decode('utf-8', 'replace')}"
        )


def extract_archive(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    run_capture(["tar", "-xf", str(archive), "-C", str(destination)])


def prepare_submodule_target(target: Path) -> None:
    """Accept Git archive's empty gitlink directory, and nothing else.

    ``git archive`` materializes a directory entry for a gitlink on the pinned
    Mooncake tree.  The submodule archive must be extracted into that existing
    empty directory.  A symlink, non-directory, or populated path would make
    the reconstruction ambiguous and therefore fails closed.
    """

    if target.is_symlink():
        raise BuildError(f"submodule target is a symlink: {target}")
    target.mkdir(parents=True, exist_ok=True)
    if not target.is_dir() or any(target.iterdir()):
        raise BuildError(f"submodule target is not an empty directory: {target}")


def copy_native_dependency_subset(source_root: Path, destination: Path) -> dict[str, Any]:
    """Relocate only the pinned native headers/configs/libraries used by CMake."""

    if not source_root.is_dir() or source_root.is_symlink():
        raise BuildError(f"native dependency source is missing or unsafe: {source_root}")
    destination.mkdir(parents=True, exist_ok=False)
    for relative in PINNED_NATIVE_DEPENDENCY_PATHS:
        source = source_root / relative
        target = destination / relative
        if source.is_symlink():
            link_target = os.readlink(source)
            link_path = Path(link_target)
            if link_path.is_absolute() or ".." in link_path.parts:
                raise BuildError(f"unsafe native dependency symlink: {relative} -> {link_target}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(link_target)
        elif source.is_dir():
            shutil.copytree(source, target, symlinks=True, copy_function=shutil.copy2)
        elif source.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        else:
            raise BuildError(f"native dependency input is missing or unsupported: {source}")

    manifest = tree_manifest(destination)
    if not manifest:
        raise BuildError("native dependency subset is empty")
    return {
        "source": str(source_root.resolve()),
        "construction": "relocated_hash_manifested_subset",
        "selected_paths": list(PINNED_NATIVE_DEPENDENCY_PATHS),
        "tree_manifest": manifest,
        "tree_manifest_sha256": hashlib.sha256(canonical_json(manifest).encode()).hexdigest(),
    }


def publish_native_runtime_libraries(
    dependency_prefix: Path,
    destination: Path,
    *,
    additional_libraries: Sequence[tuple[str, Path, Path]] = (),
) -> dict[str, Any]:
    """Publish regular, checksum-addressed runtime libraries beside the wheel.

    The pinned upstream wheel repair explicitly excludes system/native
    dependencies.  The clean physical bundle therefore carries the exact
    selected shared objects used for linking.  Symlink aliases are materialized
    as regular files so the published bundle has no link traversal surface.
    """

    library_root = dependency_prefix / "lib"
    if not library_root.is_dir() or library_root.is_symlink():
        raise BuildError("native runtime library root is missing or unsafe")
    destination.mkdir(parents=True, exist_ok=False)
    copied = 0
    resolved_prefix = dependency_prefix.resolve()
    for source in sorted(library_root.rglob("*")):
        if source.is_dir() and not source.is_symlink():
            continue
        relative = source.relative_to(library_root)
        if ".so" not in source.name:
            continue
        try:
            resolved = source.resolve(strict=True)
        except OSError as error:
            raise BuildError(
                f"native runtime library is dangling or unreadable: {source}"
            ) from error
        try:
            resolved.relative_to(resolved_prefix)
        except ValueError as error:
            raise BuildError(f"native runtime library escapes prefix: {source}") from error
        if not resolved.is_file():
            raise BuildError(f"native runtime dependency is not a file: {source}")
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(resolved, target)
        copied += 1
    additional_records: list[dict[str, Any]] = []
    for relative_text, source, allowed_root in sorted(
        additional_libraries, key=lambda row: row[0]
    ):
        relative = Path(relative_text)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or not relative.parts
            or ".so" not in relative.name
        ):
            raise BuildError(f"unsafe additional runtime library path: {relative_text!r}")
        target = destination / relative
        if target.exists() or target.is_symlink():
            raise BuildError(f"duplicate additional runtime library: {relative_text}")
        try:
            resolved = source.resolve(strict=True)
            resolved.relative_to(allowed_root.resolve(strict=True))
        except (OSError, ValueError) as error:
            raise BuildError(
                f"additional runtime library escapes its pinned root: {source}"
            ) from error
        if not resolved.is_file():
            raise BuildError(f"additional runtime library is not a file: {source}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(resolved, target)
        additional_records.append(
            {
                "published_path": relative.as_posix(),
                "source": str(resolved),
                "source_sha256": sha256_file(resolved),
            }
        )
        copied += 1
    manifest = tree_manifest(destination)
    if not copied or any(row["type"] != "regular" for row in manifest):
        raise BuildError("native runtime dependency publication is empty or unsafe")
    return {
        "construction": "dereferenced_regular_files_from_hashed_native_subset",
        "library_count": copied,
        "additional_pinned_libraries": additional_records,
        "tree_manifest": manifest,
        "tree_manifest_sha256": hashlib.sha256(
            canonical_json(manifest).encode()
        ).hexdigest(),
    }


def reconstruct_source(
    repository: Path,
    commit: str,
    destination: Path,
    archive_dir: Path,
) -> dict[str, Any]:
    resolved = git_output(repository, "rev-parse", f"{commit}^{{commit}}")
    if resolved != commit:
        raise BuildError(f"commit mismatch: resolved={resolved}, expected={commit}")

    main_archive = archive_dir / "mooncake-source.tar"
    create_archive(repository, commit, main_archive)
    extract_archive(main_archive, destination)

    submodules = submodule_commits(repository, commit)
    submodule_records: dict[str, dict[str, str]] = {}
    for relative, revision in submodules.items():
        checkout = repository / relative
        observed = git_output(checkout, "rev-parse", "HEAD")
        dirty = git_output(checkout, "status", "--porcelain=v1", "--untracked-files=all")
        if observed != revision or dirty:
            raise BuildError(
                f"submodule checkout is not clean/pinned: {relative} "
                f"observed={observed}, expected={revision}, dirty={bool(dirty)}"
            )
        archive = archive_dir / f"{relative.replace('/', '-')}.tar"
        create_archive(checkout, revision, archive)
        target = destination / relative
        prepare_submodule_target(target)
        run_capture(["tar", "-xf", str(archive), "-C", str(target)])
        submodule_records[relative] = {
            "commit": revision,
            "archive_sha256": sha256_file(archive),
        }

    return {
        "repository": str(repository.resolve()),
        "commit": commit,
        "main_archive_sha256": sha256_file(main_archive),
        "submodules": submodule_records,
        "construction": "git_archive_from_objects",
        "dirty_worktree_files_copied": False,
    }


def tree_manifest(root: Path, *, ignored_prefixes: Sequence[str] = ()) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for current, directories, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        names = sorted(files + [name for name in directories if (current_path / name).is_symlink()])
        directories[:] = sorted(
            name for name in directories if not (current_path / name).is_symlink()
        )
        for name in names:
            path = current_path / name
            relative = path.relative_to(root).as_posix()
            if any(
                relative == prefix or relative.startswith(f"{prefix}/")
                for prefix in ignored_prefixes
            ):
                continue
            metadata = path.lstat()
            record: dict[str, Any] = {
                "path": relative,
                "mode": f"{stat.S_IMODE(metadata.st_mode):04o}",
            }
            if stat.S_ISLNK(metadata.st_mode):
                target = os.readlink(path)
                target_bytes = os.fsencode(target)
                record.update(
                    {
                        "type": "symlink",
                        "bytes": len(target_bytes),
                        "link_target": target,
                        "sha256": hashlib.sha256(target_bytes).hexdigest(),
                    }
                )
            elif stat.S_ISREG(metadata.st_mode):
                record.update(
                    {
                        "type": "regular",
                        "bytes": metadata.st_size,
                        "sha256": sha256_file(path),
                    }
                )
            else:
                raise BuildError(f"unsupported source-tree entry: {path}")
            records.append(record)
    records.sort(key=lambda row: str(row["path"]))
    return records


def compare_provided_archive(provided: Path, reconstructed: Path) -> dict[str, Any]:
    ignored = ("build-golden", "build-golden-prefix")
    expected = {row["path"]: row for row in tree_manifest(reconstructed)}
    observed = {row["path"]: row for row in tree_manifest(provided, ignored_prefixes=ignored)}
    missing = sorted(set(expected) - set(observed))
    mismatched = sorted(
        path
        for path in set(expected) & set(observed)
        if any(
            expected[path].get(key) != observed[path].get(key)
            for key in ("type", "mode", "bytes", "sha256", "link_target")
        )
    )
    # Extra files are recorded but do not weaken the comparison: the build uses
    # reconstructed Git objects, never the provided directory.
    extra = sorted(set(observed) - set(expected))
    if missing or mismatched:
        raise BuildError(
            "provided archive differs from pinned Git objects: "
            f"missing={missing[:10]}, mismatched={mismatched[:10]}"
        )
    digest = hashlib.sha256(canonical_json(list(expected.values())).encode()).hexdigest()
    return {
        "path": str(provided.resolve()),
        "status": "MATCH",
        "tracked_file_count": len(expected),
        "tracked_tree_manifest_sha256": digest,
        "ignored_build_prefixes": list(ignored),
        "extra_unbuilt_files": extra,
    }


def inspect_wheel(wheel: Path, extract_root: Path) -> dict[str, Any]:
    if "aegis" in wheel.name.lower():
        raise BuildError(f"clean wheel filename contains forbidden Aegis marker: {wheel.name}")
    with zipfile.ZipFile(wheel) as archive:
        names = sorted(archive.namelist())
        required_suffixes = (
            "mooncake/engine.so",
            "mooncake/store.so",
            "mooncake/mooncake_master",
            "mooncake/mooncake_client",
        )
        missing = [
            suffix for suffix in required_suffixes if not any(n.endswith(suffix) for n in names)
        ]
        if missing:
            raise BuildError(f"clean wheel lacks runtime members: {missing}")
        metadata_name = next((name for name in names if name.endswith(".dist-info/METADATA")), None)
        if metadata_name is None:
            raise BuildError("wheel lacks METADATA")
        metadata = archive.read(metadata_name).decode("utf-8", "replace")
        if "Name: mooncake-transfer-engine\n" not in metadata:
            raise BuildError("wheel distribution name is not mooncake-transfer-engine")
        if "+aegiskv" in metadata.lower() or "aegis" in metadata.lower():
            raise BuildError("wheel metadata contains forbidden Aegis marker")
        wheel_metadata_name = next(
            (name for name in names if name.endswith(".dist-info/WHEEL")), None
        )
        if wheel_metadata_name is None:
            raise BuildError("wheel lacks WHEEL metadata")
        wheel_metadata = archive.read(wheel_metadata_name).decode("utf-8", "replace")
        if (
            not wheel.name.endswith(f"-{LOCAL_WHEEL_PLATFORM_TAG}.whl")
            or f"-{LOCAL_WHEEL_PLATFORM_TAG}\n" not in wheel_metadata
        ):
            raise BuildError(
                f"wheel is not honestly tagged for the local platform: {wheel.name}"
            )
        native_hashes = {
            Path(name).name: hashlib.sha256(archive.read(name)).hexdigest()
            for name in names
            if name.endswith(("engine.so", "store.so", "mooncake_master", "mooncake_client"))
        }

    extract_root.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(wheel) as archive:
        archive.extractall(extract_root)
    return {
        "filename": wheel.name,
        "bytes": wheel.stat().st_size,
        "sha256": sha256_file(wheel),
        "metadata_member": metadata_name,
        "wheel_metadata_member": wheel_metadata_name,
        "platform_tag": LOCAL_WHEEL_PLATFORM_TAG,
        "native_member_sha256": native_hashes,
    }


def path_within(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (OSError, ValueError):
        return False
    return True


def audit_wheel_elf_runtime(
    extract_root: Path,
    runtime_directory: Path,
    *,
    pinned_runtime_sha256: Mapping[str, str],
) -> dict[str, Any]:
    """Fail closed on every final-wheel ELF's loader-visible dependency graph."""

    readelf = Path(shutil.which("readelf") or "")
    ldd = Path(shutil.which("ldd") or "")
    if not readelf.is_file() or not ldd.is_file():
        raise BuildError("readelf and ldd are required for the final ELF audit")
    elf_paths: list[Path] = []
    for path in sorted(extract_root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        with path.open("rb") as stream:
            if stream.read(4) == b"\x7fELF":
                elf_paths.append(path)
    if not elf_paths:
        raise BuildError("final wheel contains no ELF members")

    wheel_library_directories = sorted({path.parent for path in elf_paths})
    runtime_library_directories = [runtime_directory]
    provider_directory = runtime_directory / "libibverbs"
    if provider_directory.is_dir() and not provider_directory.is_symlink():
        runtime_library_directories.append(provider_directory)
    loader_paths = runtime_library_directories + wheel_library_directories
    audit_environment = {
        "LANG": "C",
        "LC_ALL": "C",
        "LD_LIBRARY_PATH": ":".join(str(path) for path in loader_paths),
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
    }
    needed_pattern = re.compile(r"\(NEEDED\).*\[([^]]+)\]")
    rpath_pattern = re.compile(r"\((RPATH|RUNPATH)\).*\[([^]]*)\]")
    observed_pins: dict[str, dict[str, str]] = {}
    records: list[dict[str, Any]] = []

    for elf in elf_paths:
        relative = elf.relative_to(extract_root).as_posix()
        dynamic = run_capture([str(readelf), "-d", str(elf)]).stdout
        needed = needed_pattern.findall(dynamic)
        dynamic_paths = [match[1] for match in rpath_pattern.findall(dynamic)]
        for value in dynamic_paths:
            for entry in value.split(":"):
                if entry and not (
                    entry == "$ORIGIN"
                    or entry.startswith("$ORIGIN/")
                    or entry == "${ORIGIN}"
                    or entry.startswith("${ORIGIN}/")
                ):
                    raise BuildError(f"{relative} contains non-relative RPATH/RUNPATH: {entry}")
        forbidden_cuda = sorted(name for name in needed if name.startswith("libcudart.so.13"))
        unsupported_cuda = sorted(
            name
            for name in needed
            if name.startswith("libcudart.so") and name != "libcudart.so.12"
        )
        if forbidden_cuda or unsupported_cuda:
            raise BuildError(
                f"{relative} contains an unpinned CUDA runtime dependency: "
                f"{sorted(set(forbidden_cuda + unsupported_cuda))}"
            )

        ldd_stdout = ""
        loader_rows: list[dict[str, str | None]] = []
        if needed:
            completed = run_capture([str(ldd), str(elf)], env=audit_environment)
            ldd_stdout = completed.stdout
            if "not found" in ldd_stdout.lower():
                raise BuildError(f"{relative} has an unresolved dynamic dependency")
            for raw_line in ldd_stdout.splitlines():
                line = raw_line.strip()
                if not line:
                    continue
                soname: str
                resolved_text: str | None
                if "=>" in line:
                    left, right = line.split("=>", 1)
                    soname = left.strip().split()[0]
                    resolved_text = right.strip().split()[0]
                else:
                    first = line.split()[0]
                    if first == "statically":
                        continue
                    if first.startswith("/"):
                        resolved_text = first
                        soname = Path(first).name
                    else:
                        soname = first
                        resolved_text = None
                row = {"soname": soname, "resolved": resolved_text}
                loader_rows.append(row)
                if resolved_text is None:
                    if soname != "linux-vdso.so.1":
                        raise BuildError(f"{relative} has an unparsed loader row: {line}")
                    continue
                resolved = Path(resolved_text)
                if soname in SYSTEM_RUNTIME_ALLOWLIST or soname in DRIVER_RUNTIME_ALLOWLIST:
                    continue
                if not (
                    path_within(resolved, runtime_directory)
                    or path_within(resolved, extract_root)
                ):
                    raise BuildError(
                        f"{relative} resolves {soname} outside the frozen bundle: {resolved}"
                    )
                if soname in pinned_runtime_sha256:
                    observed_sha256 = sha256_file(resolved)
                    expected_sha256 = pinned_runtime_sha256[soname]
                    if observed_sha256 != expected_sha256:
                        raise BuildError(
                            f"{relative} resolves {soname} to the wrong bytes: {resolved}"
                        )
                    observed_pins[soname] = {
                        "resolved": str(resolved.resolve()),
                        "sha256": observed_sha256,
                    }
        records.append(
            {
                "path": relative,
                "sha256": sha256_file(elf),
                "needed": needed,
                "rpath_runpath": dynamic_paths,
                "loader_rows": loader_rows,
                "ldd_stdout": ldd_stdout,
            }
        )

    missing_pins = sorted(set(pinned_runtime_sha256) - set(observed_pins))
    if missing_pins:
        raise BuildError(f"final wheel did not resolve required pinned runtimes: {missing_pins}")
    return {
        "schema": "moonkvsim.vanilla_mooncake_elf_runtime_audit.v1",
        "status": "PASS",
        "elf_count": len(records),
        "system_runtime_allowlist": sorted(SYSTEM_RUNTIME_ALLOWLIST),
        "driver_runtime_allowlist": sorted(DRIVER_RUNTIME_ALLOWLIST),
        "pinned_runtime_sha256": dict(sorted(pinned_runtime_sha256.items())),
        "observed_pinned_runtimes": observed_pins,
        "loader_environment": audit_environment,
        "records": records,
    }


def generate_checksums(directory: Path) -> None:
    rows = []
    for path in sorted(item for item in directory.rglob("*") if item.is_file()):
        if path.name == "SHA256SUMS":
            continue
        rows.append(f"{sha256_file(path)}  {path.relative_to(directory).as_posix()}\n")
    (directory / "SHA256SUMS").write_text("".join(rows), encoding="utf-8")


def executable_record(path: Path, version_command: Sequence[str]) -> dict[str, str]:
    resolved = path.resolve()
    return {
        "path": str(resolved),
        "sha256": sha256_file(resolved),
        "version": run_capture(version_command).stdout.strip(),
    }


def validate_pinned_freeze(freeze: str) -> dict[str, str]:
    observed: dict[str, str] = {}
    for raw_line in freeze.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "==" not in line:
            continue
        name, version = line.split("==", 1)
        observed[name.lower().replace("_", "-")] = version
    expected = {
        requirement.split("==", 1)[0].lower().replace("_", "-"): requirement.split("==", 1)[1]
        for requirement in PINNED_BUILD_PACKAGES
    }
    mismatches = {
        name: {"observed": observed.get(name), "expected": version}
        for name, version in expected.items()
        if observed.get(name) != version
    }
    if mismatches:
        raise BuildError(f"build-tool freeze violates exact pins: {mismatches}")
    return {name: observed[name] for name in sorted(expected)}


def build(args: argparse.Namespace) -> dict[str, Any]:
    repository = args.repository.resolve()
    provided_archive = args.provided_archive.resolve()
    requested_work_root = args.work_root.absolute()
    requested_output_dir = args.output_dir.absolute()
    if (
        requested_work_root.is_symlink()
        or requested_output_dir.is_symlink()
        or requested_work_root.parent.resolve() != requested_work_root.parent
        or requested_output_dir.parent.resolve() != requested_output_dir.parent
    ):
        raise BuildError("work-root and output-dir must not be symlinks")
    work_root = requested_work_root.resolve()
    final_output_dir = requested_output_dir.resolve()
    output_dir = final_output_dir.parent / f".{final_output_dir.name}.staging.{os.getpid()}"
    python = args.python.resolve()
    cuda_root = args.cuda_root.resolve()
    native_dependency_source = args.native_dependency_source.resolve()
    gcc_runtime_root = PINNED_GCC_RUNTIME_ROOT.resolve()
    patchelf = PINNED_PATCHELF.resolve()
    cudart_path = cuda_root / PINNED_CUDART_RELATIVE

    for path, kind in (
        (repository / ".git", "Mooncake Git repository"),
        (provided_archive, "provided clean archive"),
        (python, "pinned Python"),
        (cuda_root / "bin" / "nvcc", "CUDA compiler"),
        (cudart_path, "CUDA runtime"),
        (gcc_runtime_root / "libstdc++.so.6", "GCC C++ runtime"),
        (gcc_runtime_root / "libgcc_s.so.1", "GCC support runtime"),
        (patchelf, "pinned patchelf"),
        (native_dependency_source, "native dependency source"),
    ):
        if not path.exists():
            raise BuildError(f"missing {kind}: {path}")
    observed_patchelf_sha256 = sha256_file(patchelf)
    if observed_patchelf_sha256 != PINNED_PATCHELF_SHA256:
        raise BuildError(
            "pinned patchelf bytes drifted: "
            f"observed={observed_patchelf_sha256}, expected={PINNED_PATCHELF_SHA256}"
        )
    if (
        work_root.exists()
        or work_root.is_symlink()
        or final_output_dir.exists()
        or final_output_dir.is_symlink()
        or output_dir.exists()
        or output_dir.is_symlink()
    ):
        raise BuildError("work-root and output-dir must both be fresh paths")
    if not final_output_dir.parent.is_dir() or final_output_dir.parent.is_symlink():
        raise BuildError("output-dir parent must pre-exist and must not be a symlink")

    work_root.mkdir(parents=True)
    output_dir.mkdir(parents=True)
    (output_dir / "BUILD_INCOMPLETE").write_text(
        "This staging directory is not a consumable clean build.\n",
        encoding="utf-8",
    )
    logs = output_dir / "logs"
    logs.mkdir()
    archives = work_root / "archives"
    archives.mkdir()
    source = work_root / "source"
    source_record = reconstruct_source(repository, args.commit, source, archives)
    provided_record = compare_provided_archive(provided_archive, source)
    source_manifest_path = output_dir / "source-tree-manifest.json"
    write_json(source_manifest_path, tree_manifest(source))
    source_record["tree_manifest_sha256"] = sha256_file(source_manifest_path)

    native_dependency_prefix = work_root / "native-dependency-prefix"
    native_dependency_record = copy_native_dependency_subset(
        native_dependency_source,
        native_dependency_prefix,
    )
    native_dependency_manifest_path = output_dir / "native-dependency-manifest.json"
    write_json(native_dependency_manifest_path, native_dependency_record)
    pinned_cuda_link_directory = work_root / "pinned-cuda-link"
    pinned_cuda_link_directory.mkdir()
    shutil.copy2(cudart_path, pinned_cuda_link_directory / "libcudart.so")
    additional_runtime_libraries = (
        ("libcudart.so.12", cudart_path, cuda_root),
        ("libcudart.so.12.8.90", cudart_path, cuda_root),
        ("libgcc_s.so.1", gcc_runtime_root / "libgcc_s.so.1", gcc_runtime_root),
        ("libstdc++.so.6", gcc_runtime_root / "libstdc++.so.6", gcc_runtime_root),
        (
            "libstdc++.so.6.0.29",
            gcc_runtime_root / "libstdc++.so.6.0.29",
            gcc_runtime_root,
        ),
    )
    native_runtime_directory = output_dir / "native-runtime"
    native_runtime_record = publish_native_runtime_libraries(
        native_dependency_prefix,
        native_runtime_directory,
        additional_libraries=additional_runtime_libraries,
    )
    native_runtime_manifest_path = output_dir / "native-runtime-manifest.json"
    write_json(native_runtime_manifest_path, native_runtime_record)

    build_venv = work_root / "build-venv"
    run_capture(
        ["uv", "venv", "--python", str(python), str(build_venv)],
        log_path=logs / "01-create-build-venv.log",
    )
    build_python = build_venv / "bin" / "python"
    run_capture(
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(build_python),
            *PINNED_BUILD_PACKAGES,
        ],
        log_path=logs / "02-install-build-tools.log",
    )
    freeze_before = run_capture(["uv", "pip", "freeze", "--python", str(build_python)]).stdout
    validate_pinned_freeze(freeze_before)
    (output_dir / "build-tool-freeze.pre-wheel.txt").write_text(freeze_before, encoding="utf-8")
    constraints_path = output_dir / "build-constraints.txt"
    constraints_path.write_text("\n".join(PINNED_BUILD_PACKAGES) + "\n", encoding="utf-8")

    build_tmp = work_root / "tmp"
    build_tmp.mkdir()
    native_build_env = dict(os.environ)
    native_build_env["TMPDIR"] = str(build_tmp)
    native_env_prefixes = {
        "CPATH": (
            native_dependency_prefix / "include",
            native_dependency_prefix / "include" / "libnl3",
        ),
        "LIBRARY_PATH": (native_dependency_prefix / "lib",),
        "LD_LIBRARY_PATH": (native_dependency_prefix / "lib", gcc_runtime_root),
        "PKG_CONFIG_PATH": (native_dependency_prefix / "lib" / "pkgconfig",),
    }
    for key, prefixes in native_env_prefixes.items():
        values = [str(path) for path in prefixes]
        if native_build_env.get(key):
            values.append(native_build_env[key])
        native_build_env[key] = ":".join(values)

    build_dir = source / "build"
    linker_flags = " ".join(
        (
            f"-L{pinned_cuda_link_directory}",
            f"-Wl,-rpath-link,{native_dependency_prefix / 'lib'}",
            f"-Wl,-rpath-link,{cuda_root / 'targets/x86_64-linux/lib'}",
        )
    )
    cmake_command = [
        "cmake",
        "-S",
        str(source),
        "-B",
        str(build_dir),
        "-DCMAKE_BUILD_TYPE=Release",
        "-DCMAKE_C_COMPILER=/usr/local/gcc/gcc-11.2.0/bin/gcc",
        "-DCMAKE_CXX_COMPILER=/usr/local/gcc/gcc-11.2.0/bin/g++",
        f"-DCMAKE_CUDA_COMPILER={cuda_root / 'bin' / 'nvcc'}",
        f"-DCUDAToolkit_ROOT={cuda_root}",
        f"-DCUDA_CUDART={cuda_root / PINNED_CUDART_RELATIVE}",
        f"-DCUDA_cudart_LIBRARY={cuda_root / PINNED_CUDART_RELATIVE}",
        "-DCMAKE_CUDA_ARCHITECTURES=89",
        f"-DPython3_EXECUTABLE={build_python}",
        f"-DCMAKE_PREFIX_PATH={native_dependency_prefix}",
        "-DUSE_CUDA=ON",
        "-DUSE_NOF=OFF",
        "-DUSE_HTTP=ON",
        "-DUSE_ETCD=OFF",
        "-DUSE_REDIS=OFF",
        "-DSTORE_USE_ETCD=OFF",
        "-DSTORE_USE_REDIS=OFF",
        "-DSTORE_USE_K8S_LEASE=OFF",
        "-DWITH_TE=ON",
        "-DWITH_STORE=ON",
        "-DWITH_STORE_RUST=OFF",
        "-DWITH_P2P_STORE=OFF",
        "-DBUILD_UNIT_TESTS=OFF",
        "-DBUILD_EXAMPLES=ON",
        "-DCMAKE_SKIP_RPATH=ON",
        f"-DCMAKE_EXE_LINKER_FLAGS={linker_flags}",
        f"-DCMAKE_SHARED_LINKER_FLAGS={linker_flags}",
        f"-DCMAKE_MODULE_LINKER_FLAGS={linker_flags}",
    ]
    run_capture(
        cmake_command,
        env=native_build_env,
        log_path=logs / "03-cmake-configure.log",
    )
    run_capture(
        [
            "cmake",
            "--build",
            str(build_dir),
            "--parallel",
            str(args.jobs),
            "--target",
            "engine",
            "store",
            "mooncake_master",
            "mooncake_client",
            "transfer_engine_bench",
        ],
        env=native_build_env,
        log_path=logs / "04-cmake-build.log",
    )

    env = dict(native_build_env)
    env.update(
        {
            "PATH": f"{build_venv / 'bin'}:{patchelf.parent}:{env.get('PATH', '')}",
            "PYTHON_VERSION": "3.12",
            "BUILD_DIR": "build",
            "OUTPUT_DIR": "dist-clean",
            "PLATFORM_TAG": AUDITWHEEL_REPAIR_PLATFORM_TAG,
            "CUDA_HOME": str(cuda_root),
            "CUDAToolkit_ROOT": str(cuda_root),
            "CMAKE_PREFIX_PATH": str(native_dependency_prefix),
            "CI": "false",
            "FREE_BUILD_DIR": "0",
            # The upstream helper performs an explicit unversioned pip upgrade.
            # Constrain both that install and its PEP-517 build environment.
            "PIP_CONSTRAINT": str(constraints_path),
            "PIP_BUILD_CONSTRAINT": str(constraints_path),
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "UV_CONSTRAINT": str(constraints_path),
        }
    )
    run_capture(
        ["bash", "scripts/build_wheel.sh", "3.12", "dist-clean"],
        cwd=source,
        env=env,
        log_path=logs / "05-build-wheel.log",
    )
    freeze_after = run_capture(["uv", "pip", "freeze", "--python", str(build_python)]).stdout
    pinned_versions = validate_pinned_freeze(freeze_after)
    (output_dir / "build-tool-freeze.txt").write_text(freeze_after, encoding="utf-8")
    wheel_output_directory = source / "mooncake-wheel" / "dist-clean"
    wheels = sorted(wheel_output_directory.glob("*.whl"))
    if len(wheels) != 1:
        raise BuildError(f"expected exactly one repaired wheel, found {wheels}")
    repaired_wheel_record = {
        "filename": wheels[0].name,
        "sha256": sha256_file(wheels[0]),
        "auditwheel_platform_tag": AUDITWHEEL_REPAIR_PLATFORM_TAG,
    }
    run_capture(
        [
            str(build_python),
            "-m",
            "wheel",
            "tags",
            "--remove",
            "--platform-tag",
            LOCAL_WHEEL_PLATFORM_TAG,
            str(wheels[0]),
        ],
        log_path=logs / "06-retag-local-wheel.log",
    )
    wheels = sorted(wheel_output_directory.glob("*.whl"))
    if len(wheels) != 1 or not wheels[0].name.endswith(
        f"-{LOCAL_WHEEL_PLATFORM_TAG}.whl"
    ):
        raise BuildError(f"expected exactly one honestly retagged local wheel, found {wheels}")
    wheel_destination = output_dir / wheels[0].name
    shutil.copy2(wheels[0], wheel_destination)
    wheel_extract_root = work_root / "wheel-extract"
    wheel_record = inspect_wheel(wheel_destination, wheel_extract_root)
    wheel_record["upstream_repaired_wheel"] = repaired_wheel_record
    pinned_runtime_sha256 = {
        "libcudart.so.12": sha256_file(cudart_path),
        "libgcc_s.so.1": sha256_file(gcc_runtime_root / "libgcc_s.so.1"),
        "libstdc++.so.6": sha256_file(gcc_runtime_root / "libstdc++.so.6"),
    }
    elf_runtime_audit = audit_wheel_elf_runtime(
        wheel_extract_root,
        native_runtime_directory,
        pinned_runtime_sha256=pinned_runtime_sha256,
    )
    elf_runtime_audit_path = output_dir / "elf-runtime-audit.json"
    write_json(elf_runtime_audit_path, elf_runtime_audit)
    wheel_record["elf_runtime_audit"] = {
        "path": elf_runtime_audit_path.name,
        "sha256": sha256_file(elf_runtime_audit_path),
        "status": elf_runtime_audit["status"],
        "elf_count": elf_runtime_audit["elf_count"],
    }

    cmake_cache = build_dir / "CMakeCache.txt"
    shutil.copy2(cmake_cache, output_dir / "CMakeCache.txt")
    manifest = {
        "schema": SCHEMA,
        "status": "PASS",
        "evidence_class": "clean_build_provenance_only",
        "physical_validation": False,
        "source": source_record,
        "provided_archive_crosscheck": provided_record,
        "build": {
            "work_root": str(work_root),
            "python": str(python),
            "build_python": str(build_python),
            "cuda_root": str(cuda_root),
            "gcc_runtime_root": str(gcc_runtime_root),
            "local_wheel_platform_tag": LOCAL_WHEEL_PLATFORM_TAG,
            "auditwheel_repair_platform_tag": AUDITWHEEL_REPAIR_PLATFORM_TAG,
            "pinned_cuda_link_directory": str(pinned_cuda_link_directory),
            "native_dependency_prefix": str(native_dependency_prefix),
            "native_dependency_source": str(native_dependency_source),
            "native_dependency_manifest_sha256": sha256_file(
                native_dependency_manifest_path
            ),
            "native_dependency_tree_manifest_sha256": native_dependency_record[
                "tree_manifest_sha256"
            ],
            "native_runtime_directory": "native-runtime",
            "native_runtime_manifest_sha256": sha256_file(
                native_runtime_manifest_path
            ),
            "native_runtime_tree_manifest_sha256": native_runtime_record[
                "tree_manifest_sha256"
            ],
            "native_dependency_environment": {
                key: native_build_env[key]
                for key in (
                    "CPATH",
                    "LIBRARY_PATH",
                    "LD_LIBRARY_PATH",
                    "PKG_CONFIG_PATH",
                    "TMPDIR",
                )
            },
            "cmake_command": cmake_command,
            "jobs": args.jobs,
            "metadata_control_plane": "embedded_http_only",
            "http_metadata_enabled": True,
            "http_is_data_or_persistent_tier": False,
            "ssd_nvme_enabled": False,
            "dirty_mooncake_venv_modified": False,
            "pinned_vllm_venv_modified": False,
            "pinned_build_packages": list(PINNED_BUILD_PACKAGES),
            "pinned_build_package_versions": pinned_versions,
            "build_constraints_sha256": sha256_file(constraints_path),
            "pep517_build_isolation_constrained": True,
            "upstream_build_wheel_script_sha256": sha256_file(
                source / "scripts" / "build_wheel.sh"
            ),
            "build_tool_freeze_pre_wheel_sha256": sha256_file(
                output_dir / "build-tool-freeze.pre-wheel.txt"
            ),
            "build_tool_freeze_sha256": sha256_file(output_dir / "build-tool-freeze.txt"),
            "toolchain": {
                "python": executable_record(python, [str(python), "--version"]),
                "uv": executable_record(Path(shutil.which("uv") or ""), ["uv", "--version"]),
                "cmake": executable_record(
                    Path(shutil.which("cmake") or ""), ["cmake", "--version"]
                ),
                "gcc": executable_record(
                    Path("/usr/local/gcc/gcc-11.2.0/bin/gcc"),
                    ["/usr/local/gcc/gcc-11.2.0/bin/gcc", "--version"],
                ),
                "g++": executable_record(
                    Path("/usr/local/gcc/gcc-11.2.0/bin/g++"),
                    ["/usr/local/gcc/gcc-11.2.0/bin/g++", "--version"],
                ),
                "nvcc": executable_record(
                    cuda_root / "bin" / "nvcc",
                    [str(cuda_root / "bin" / "nvcc"), "--version"],
                ),
                "patchelf": executable_record(
                    patchelf,
                    [str(patchelf), "--version"],
                ),
                "cudart": {
                    "path": str((cuda_root / PINNED_CUDART_RELATIVE).resolve()),
                    "sha256": sha256_file(cuda_root / PINNED_CUDART_RELATIVE),
                },
                "libgcc_s": {
                    "path": str((gcc_runtime_root / "libgcc_s.so.1").resolve()),
                    "sha256": sha256_file(gcc_runtime_root / "libgcc_s.so.1"),
                },
                "libstdc++": {
                    "path": str((gcc_runtime_root / "libstdc++.so.6").resolve()),
                    "sha256": sha256_file(gcc_runtime_root / "libstdc++.so.6"),
                },
            },
        },
        "wheel": wheel_record,
    }
    write_json(output_dir / "build-manifest.json", manifest)
    (output_dir / "BUILD_INCOMPLETE").unlink()
    write_json(
        output_dir / "PUBLICATION_COMPLETE.json",
        {"schema": SCHEMA, "status": "PASS", "publication": "COMPLETE"},
    )
    generate_checksums(output_dir)
    os.replace(output_dir, final_output_dir)
    return manifest


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--repository", type=Path, default=Path("/home/comp/zhanzhao/Mooncake"))
    value.add_argument(
        "--provided-archive",
        type=Path,
        default=Path("/tmp/moonkvsim-mooncake-f161118.45Cs3n"),
    )
    value.add_argument("--commit", default=PINNED_COMMIT)
    value.add_argument("--python", type=Path, default=PINNED_PYTHON)
    value.add_argument("--cuda-root", type=Path, default=PINNED_CUDA_ROOT)
    value.add_argument(
        "--native-dependency-source",
        type=Path,
        default=PINNED_NATIVE_DEPENDENCY_SOURCE,
    )
    value.add_argument("--work-root", type=Path, required=True)
    value.add_argument("--output-dir", type=Path, required=True)
    value.add_argument("--jobs", type=int, default=12)
    return value


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        manifest = build(args)
    except Exception as error:
        final_output = args.output_dir.resolve()
        incomplete = final_output.parent / f".{final_output.name}.staging.{os.getpid()}"
        try:
            if (
                final_output.parent.is_dir()
                and not final_output.parent.is_symlink()
                and not final_output.exists()
                and not final_output.is_symlink()
                and not incomplete.exists()
                and not incomplete.is_symlink()
            ):
                incomplete.mkdir()
            if incomplete.is_dir() and not incomplete.is_symlink():
                complete_marker = incomplete / "PUBLICATION_COMPLETE.json"
                if complete_marker.exists() or complete_marker.is_symlink():
                    if not complete_marker.is_file() or complete_marker.is_symlink():
                        raise BuildError(
                            f"unsafe completion marker in failed staging: {complete_marker}"
                        )
                    complete_marker.unlink()
                write_json(
                    incomplete / "build-failure.json",
                    {
                        "schema": SCHEMA,
                        "status": "FAIL",
                        "publication": "INCOMPLETE",
                        "error_type": type(error).__name__,
                        "error": str(error),
                    },
                )
                (incomplete / "BUILD_INCOMPLETE").write_text(
                    "This staging directory is not a consumable clean build.\n",
                    encoding="utf-8",
                )
                generate_checksums(incomplete)
                print(f"MOONKVSIM_CLEAN_BUILD_INCOMPLETE={incomplete}", file=sys.stderr)
        except Exception as publication_error:
            print(
                f"MOONKVSIM_CLEAN_BUILD_FAILURE_RECORD_ERROR={publication_error}",
                file=sys.stderr,
            )
        print(f"MOONKVSIM_CLEAN_BUILD_ERROR={error}", file=sys.stderr)
        return 2
    print(canonical_json(manifest), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
