"""File-scoped project organization; old-result deletion awaits Markdown selection."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").is_file())
AUDIT = Path(__file__).resolve().parent


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def files(path: Path) -> list[Path]:
    return [path] if path.is_file() else sorted(p for p in path.rglob("*") if p.is_file())


def write(name: str, value: object) -> None:
    (AUDIT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def main() -> None:
    if (AUDIT / "ORGANIZATION_COMPLETE.json").exists():
        raise SystemExit("organization already completed; do not repeat")
    pairs = [
        ("output/pdf", "benchmark/AegisKV/Archived/paper-reviews"),
        ("output/analysis", "benchmark/AegisKV/experiments/analysis"),
        ("output/notion", "benchmark/AegisKV/exports/notion"),
        (
            "docs/development/mooncake-aegiskv-three-way-design-implementation.md",
            "benchmark/AegisKV/docs/mooncake-aegiskv-three-way-design-implementation.md",
        ),
        (
            "tmp/pdfs/figure5-explanation",
            "benchmark/AegisKV/exports/reference-pages/figure5-explanation",
        ),
    ]
    for path in sorted((ROOT / "schemas").glob("aegiskv-*.schema.json")):
        pairs.append(
            (str(path.relative_to(ROOT)), "benchmark/AegisKV/experiments/schemas/" + path.name)
        )
    reference = ROOT / "tmp/pdfs/aegiskv-overview-references"
    for path in sorted(reference.iterdir()):
        dest = (
            "benchmark/AegisKV/docs/related_works/imported-20261004/"
            if path.suffix == ".pdf"
            else "benchmark/AegisKV/exports/reference-pages/aegiskv-overview-references/"
        )
        pairs.append((str(path.relative_to(ROOT)), dest + path.name))
    plan = []
    for source, destination in pairs:
        src, dst = ROOT / source, ROOT / destination
        if not src.exists() or dst.exists():
            raise RuntimeError(f"unexpected migration state: {source} -> {destination}")
        for path in files(src):
            target = dst if src.is_file() else dst / path.relative_to(src)
            plan.append(
                {
                    "source": str(path.relative_to(ROOT)),
                    "destination": str(target.relative_to(ROOT)),
                    "sha256": sha(path),
                    "bytes": path.stat().st_size,
                }
            )
    write("MIGRATION_PLAN.json", plan)
    for source, destination in pairs:
        dst = ROOT / destination
        dst.parent.mkdir(parents=True, exist_ok=True)
        (ROOT / source).rename(dst)
    for item in plan:
        target = ROOT / item["destination"]
        if sha(target) != item["sha256"]:
            raise RuntimeError(f"migration changed content: {target}")
    write("MIGRATION_BYTE_VERIFICATION.json", {"status": "PASS", "files": len(plan)})

    modified = []

    def change(relative: str, transform) -> None:
        path = ROOT / relative
        before = path.read_text()
        after = transform(before)
        if before == after:
            return
        backup = AUDIT / "source-before" / relative
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, backup)
        path.write_text(after)
        modified.append(
            {"path": relative, "before_sha256": sha(backup), "after_sha256": sha(path)}
        )

    change(
        "python/moonkvsim/config/validation.py",
        lambda text: text.replace(
            '_SCHEMA_DIRECTORY: Final = _REPOSITORY_ROOT / "schemas"',
            '_SCHEMA_DIRECTORY: Final = _REPOSITORY_ROOT / "schemas"\n'
            '_AEGISKV_SCHEMA_DIRECTORY: Final = (\n'
            '    _REPOSITORY_ROOT / "benchmark/AegisKV/experiments/schemas"\n'
            ')',
        ).replace(
            '    path = _SCHEMA_DIRECTORY / _SCHEMA_FILES[canonical_name]',
            '    directory = (\n'
            '        _AEGISKV_SCHEMA_DIRECTORY\n'
            '        if canonical_name.startswith("aegiskv-")\n'
            '        else _SCHEMA_DIRECTORY\n'
            '    )\n'
            '    path = directory / _SCHEMA_FILES[canonical_name]',
        ),
    )
    for relative in [
        "python/moonkvsim/aegiskv/qwen3_32b_tp4_config.py",
        "python/moonkvsim/aegiskv/qwen3_8b_acceptance.py",
        "tests/aegiskv/test_no_failure_overhead_runner.py",
        "tests/aegiskv/test_qwen3_8b_acceptance_manifest.py",
        "tests/aegiskv/test_qwen3_8b_failure_campaign.py",
    ]:
        change(
            relative,
            lambda text: text.replace('"schemas/aegiskv-', '"benchmark/AegisKV/experiments/schemas/aegiskv-'),
        )
    change(
        "README.md",
        lambda text: text.replace(
            "docs/development/mooncake-aegiskv-three-way-design-implementation.md",
            "benchmark/AegisKV/docs/mooncake-aegiskv-three-way-design-implementation.md",
        ),
    )
    change(
        "benchmark/AegisKV/experiments/scripts/paper/render_adapter_analysis.py",
        lambda text: text.replace(
            '"output/pdf/aegiskv-adapter-analysis-20260919"',
            '"benchmark/AegisKV/exports/adapter-analysis-20260919"',
        ),
    )
    for name, old in [
        ("prepare_assets.py", "ROOT = Path(__file__).resolve().parents[3]"),
        ("publish.py", "ROOT = OUT.parents[2]"),
    ]:
        change(
            "benchmark/AegisKV/exports/notion/aegiskv-20261002/" + name,
            lambda text, old=old: text.replace(
                old,
                'ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").is_file())',
            ),
        )
    for directory in [ROOT / "output", reference, ROOT / ".agents", ROOT / ".codex"]:
        if directory.is_dir() and not any(directory.iterdir()):
            directory.rmdir()
    protected = json.loads((AUDIT / "ACTIVE_PAPER_BEFORE.json").read_text())
    drift = [path for path, digest in protected.items() if sha(ROOT / path) != digest]
    if drift:
        raise RuntimeError(f"active paper changed: {drift}")
    write("PATH_EDITS.json", modified)
    result = {
        "status": "COMPLETE",
        "moved_files": len(plan),
        "moved_bytes": sum(item["bytes"] for item in plan),
        "path_edits": len(modified),
        "active_paper_hashes": "PASS",
        "old_results_and_images": "awaiting exact preservation Markdown path",
    }
    write("ORGANIZATION_COMPLETE.json", result)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
