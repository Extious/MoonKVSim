from __future__ import annotations
import argparse, fcntl, hashlib, importlib.abc, importlib.machinery, json, sys, traceback
from pathlib import Path
TREE = Path(__file__).resolve().parent
PACKAGE = TREE / "python"
sys.path.insert(0, str(PACKAGE))
class FrozenOnly(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "moonkvsim" or fullname.startswith("moonkvsim."):
            spec = importlib.machinery.PathFinder.find_spec(fullname, path or [str(PACKAGE)])
            if (spec is None or spec.origin is None
                    or not Path(spec.origin).resolve().is_relative_to(PACKAGE)):
                raise ImportError("MoonKVSim import escaped immutable snapshot: " + fullname)
            return spec
        return None
sys.meta_path.insert(0, FrozenOnly())
from moonkvsim.aegiskv import evaluation_walltime_campaign as campaign
if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--workers", type=int, default=2)
    p.add_argument("--limit", type=int)
    p.add_argument("--verify-only", action="store_true")
    args = p.parse_args()
    campaign.verify_frozen(args.out)
    report = dict(imported_source_sha256=campaign.imported_sources(),
                  root=str(TREE), python=sys.version)
    if args.verify_only:
        campaign.write_json(args.out / "IMPORT_PREFLIGHT.json", report)
    else:
        with (args.out / "RUNNING.lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            campaign.write_json(args.out / "RUN_IMPORTS.json", report)
            try:
                campaign.run(args.out, args.workers, args.limit)
            except BaseException as error:
                campaign.write_json(args.out / "RUN_ERROR.json", dict(
                    type=type(error).__name__, message=str(error),
                    traceback=traceback.format_exc()))
                raise
            finally:
                campaign.write_json(args.out / "FINAL_IMPORTS.json", dict(
                    imported_source_sha256=campaign.imported_sources(), root=str(TREE)))
