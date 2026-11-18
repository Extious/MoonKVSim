from __future__ import annotations
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
    args.imports.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
