"""Reduce newly completed runs and render independently of simulation workers."""

import argparse
import concurrent.futures
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path


def read_live_json(path):
    """A status writer may briefly truncate its file before publishing JSON."""
    for attempt in range(5):
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            if attempt == 4:
                raise
            time.sleep(0.05)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--figures", type=Path)
    parser.add_argument("--reduce-only", action="store_true")
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    if not args.reduce_only and args.figures is None:
        parser.error("--figures is required unless --reduce-only is set")
    scripts = Path(__file__).resolve().parent
    protocol = json.loads((args.campaign / "PROTOCOL.json").read_text())
    expected = [
        (case, system)
        for case, config in protocol["cases"].items()
        for system in config.get("systems", ["mooncake", "dram", "aegis"])
    ]
    complete, active, rendered, failed = set(), {}, set(), []
    args.data.mkdir(parents=True, exist_ok=True)
    extractor_sha = hashlib.sha256((scripts / "three_system_data.py").read_bytes()).hexdigest()

    def reduce(job):
        case, system = job
        target = args.data / case
        target.mkdir(exist_ok=True)
        with (target / f"{system}-reduction.log").open("w") as log:
            result = subprocess.run(
                [
                    sys.executable,
                    str(scripts / "three_system_data.py"),
                    "--input",
                    str(args.campaign / "runs" / case),
                    "--output",
                    str(target),
                    "--systems",
                    system,
                ],
                stdout=log,
                stderr=subprocess.STDOUT,
            )
        return result.returncode

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        while len(complete) < len(expected):
            for job in expected:
                if len(active) >= args.workers:
                    break
                if job in complete or job in active.values():
                    continue
                case, system = job
                manifest = args.campaign / "runs" / case / f"{system}.manifest.json"
                if not manifest.exists():
                    continue
                if (args.data / case / f"{system}.json").exists():
                    reduced = json.loads((args.data / case / f"{system}.json").read_text())
                    assert (
                        reduced["manifest"]["raw_sha256"]
                        == json.loads(manifest.read_text())["raw_sha256"]
                    )
                    if reduced.get("extractor_sha256") == extractor_sha:
                        complete.add(job)
                    else:
                        active[pool.submit(reduce, job)] = job
                else:
                    active[pool.submit(reduce, job)] = job
            done, _ = concurrent.futures.wait(
                active, timeout=5, return_when=concurrent.futures.FIRST_COMPLETED
            )
            for future in done:
                job = active.pop(future)
                if future.result():
                    failed.append(job)
                else:
                    complete.add(job)
                    print(json.dumps({"reduced": job, "count": len(complete)}), flush=True)
            if failed:
                raise RuntimeError(f"reduction failed: {failed}")
            for case, config in protocol["cases"].items():
                if args.reduce_only:
                    continue
                if case in rendered or "systems" in config:
                    continue
                if not all((case, s) in complete for s in ("mooncake", "dram", "aegis")):
                    continue
                if case in {"f1-natural", "f2-natural"} and not all(
                    ("f0-natural", s) in complete for s in ("mooncake", "dram", "aegis")
                ):
                    continue
                if case in {"f0-natural", "f0-revisit"}:
                    command = [
                        sys.executable,
                        str(scripts / "render_three_system_figures.py"),
                        "--data",
                        str(args.data / case),
                        "--case",
                        case,
                        "--output",
                        str(args.figures),
                    ]
                else:
                    command = [
                        sys.executable,
                        str(scripts / "render_three_system_comparisons.py"),
                        "--data",
                        str(args.data),
                        "--case",
                        case,
                        "--output",
                        str(args.figures),
                    ]
                subprocess.run(command, check=True)
                rendered.add(case)
            state_file = args.campaign / "STATUS.json"
            if state_file.exists():
                state = read_live_json(state_file)
                if state["failed"] and not state["active"]:
                    raise RuntimeError(f"campaign stopped with failed runs: {state['failed']}")
            (args.data / "PROCESSING_STATUS.json").write_text(
                json.dumps(
                    {
                        "reduced": sorted(complete),
                        "rendered": sorted(rendered),
                        "active": list(active.values()),
                    },
                    indent=2,
                )
                + "\n"
            )
            if not active:
                time.sleep(5)
    if args.reduce_only:
        print(json.dumps({"status": "PASS", "runs": len(complete), "cases": len(protocol["cases"])}), flush=True)
        return
    subprocess.run(
        [
            sys.executable,
            str(scripts / "render_three_system_comparisons.py"),
            "--data",
            str(args.data),
            "--output",
            str(args.figures),
        ],
        check=True,
    )
    print(
        json.dumps({"status": "PASS", "runs": len(complete), "cases": len(protocol["cases"])}),
        flush=True,
    )


if __name__ == "__main__":
    main()
