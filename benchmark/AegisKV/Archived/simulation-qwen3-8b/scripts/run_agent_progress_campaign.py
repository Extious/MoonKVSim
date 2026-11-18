#!/usr/bin/env python3
"""Freeze and execute independent, paired 80%-progress failure positions."""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from run_agent_progress_failure import ROOT, SYSTEMS, read_records, sha, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--rounds", type=int, default=1)
    parser.add_argument("--workers", type=int, default=12)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    records = read_records(1, 160)
    by_workflow = defaultdict(list)
    for r in records:
        by_workflow[r["workflow_id"]].append(r)
    modal_count = Counter(map(len, by_workflow.values())).most_common(1)[0][0]
    wid = min(w for w, rs in by_workflow.items() if len(rs) == modal_count and
              sum(not r["parent_span_ids"] for r in rs) == 1 and
              sum(r["span_id"].endswith(":final") for r in rs) == 1)
    selected = sorted(by_workflow[wid], key=lambda r: r["source_position"]["top_level_index"])
    assert len(selected) == 7
    labels = ["A1: prerequisite", "A2: branch 1", "A3: branch 2", "A4: branch 3",
              "A5: branch 4", "A6: branch 5", "A7: final"]
    positions = [{"case": f"a{i+1}", "position": i+1, "label": labels[i],
                  "span_id": r["span_id"] + (":revisit-0" if args.rounds > 1 else ""),
                  "agent_id": r["agent_id"], "parent_span_ids": r["parent_span_ids"],
                  "prompt_tokens": r["prompt_tokens"], "output_tokens": r["output_tokens"],
                  "threshold_tokens": (r["prompt_tokens"] + r["output_tokens"]) * .8}
                 for i, r in enumerate(selected)]
    runner = Path(__file__).with_name("run_agent_progress_failure.py")
    protocol = {
        "schema": "aegiskv.agent80_campaign.v1", "frozen_before_execution": True,
        "workflow_id": wid,
        "selection": "lexicographically first input workflow having modal 7 nodes, one root and one final node; no F1 outcomes used",
        "positions": positions, "parallel_branches": [2, 3, 4, 5, 6],
        "systems": list(SYSTEMS), "seed": 0, "independent_repeats_per_condition": 1,
        "workflows_per_run": 1 if args.smoke else 160,
        "requests_per_run": 7 * args.rounds if args.smoke else len(records) * args.rounds,
        "rounds": args.rounds, "workflow_concurrency": 16,
        "trigger": "first scheduler-visible crossing of 0.8 * (prompt_tokens + output_tokens); nanosecond interpolation within forward step",
        "host": "actual GPU hosting the fixed focus at crossing, separately resolved for each strategy",
        "outage_seconds": 120, "failure_count_per_F1_run": 1,
        "F0_control": "same system, identical input/configuration/seed, no failure",
        "cross_figure_reuse": "final-agent F1 runs reused for all-workflow figure and agent-position sweep",
        "new_workflow_figure_y": "same-system WCT(F1) minus WCT(F0), seconds; all workflow IDs retained",
        "agent_position_figure_y": "focus-workflow same-system WCT(F1) minus WCT(F0), seconds",
        "indirect_affected_definition": "not in active/queued victim union for this system and exact integer-nanosecond WCT change != 0; descriptive counterfactual effect including queue/release changes",
        "source_snapshot_sha256": sha(ROOT / "MECHANISM_SOURCE_SNAPSHOT.json"),
        "runner_sha256": sha(runner), "orchestrator_sha256": sha(__file__),
        "cpu_quotes_sha256": sha(ROOT / "output/agent-lease-20260908/CPU_QUOTES.json"),
        "evidence": "frozen source-v3 uncalibrated CPU-hosted GlobalDES; no native GPU execution",
        "raw_compression": "gzip level 1; same unmodified payload and representative fields",
        "scope": "smoke regression" if args.smoke else "exploratory paired stage sensitivity; no independent-repeat confidence intervals",
    }
    path = out / "PROTOCOL.json"
    if path.exists():
        assert json.loads(path.read_text()) == protocol, "frozen protocol drift"
    else:
        write_json(path, protocol)

    jobs = [("f0", s) for s in SYSTEMS]
    chosen = positions[-1:] if args.smoke else positions
    jobs += [(p["case"], s) for p in chosen for s in SYSTEMS]
    configs = {p["case"]: p for p in positions}
    pending, active, completed, failures = list(jobs), {}, [], []
    for job in tuple(pending):
        manifest = out / "runs" / job[0] / f"{job[1]}.manifest.json"
        if manifest.exists():
            value = json.loads(manifest.read_text())
            assert value["status"] == "PASS", (job, value)
            assert value["runner_sha256"] == protocol["runner_sha256"]
            completed.append(job)
            pending.remove(job)

    def execute(job):
        case, system = job
        directory = out / "runs" / case
        directory.mkdir(parents=True, exist_ok=True)
        command = [sys.executable, str(runner), "--system", system, "--output", str(directory),
                   "--workflow-id", wid, "--rounds", str(args.rounds),
                   "--workflows", str(protocol["workflows_per_run"])]
        if case != "f0":
            command += ["--focus-span", configs[case]["span_id"], "--control",
                        str(out / "runs/f0" / f"{system}.summary.json")]
        write_json(directory / f"{system}.command.json", command)
        env = dict(os.environ, PYTHONPATH=str(ROOT / "python"), TMPDIR="/tmp",
                   MOONKVSIM_PROGRESS_EVERY_EVENTS="10000")
        with (directory / f"{system}.log").open("w") as log:
            return subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT).returncode

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        while pending or active:
            if failures:
                pending.clear()
            controls_ready = all(("f0", s) in completed for s in SYSTEMS)
            for job in tuple(pending):
                if len(active) >= args.workers:
                    break
                if job[0] != "f0" and not controls_ready:
                    continue
                if job[0] != "f0":
                    control = json.loads((out / "runs/f0" / f"{job[1]}.summary.json").read_text())
                    assert "at_ns" in control["focus_crossings"][configs[job[0]]["span_id"]], "80% was skipped by reused prefix"
                active[pool.submit(execute, job)] = job
                pending.remove(job)
                print(json.dumps({"started": job, "active": len(active), "pending": len(pending)}), flush=True)
            done, _ = wait(active, timeout=10, return_when=FIRST_COMPLETED)
            for future in done:
                job = active.pop(future)
                try:
                    code = future.result()
                except Exception as exc:
                    code = repr(exc)
                (failures if code else completed).append(job)
                print(json.dumps({"finished": job, "exit": code, "completed": len(completed), "failed": failures}), flush=True)
            write_json(out / "STATUS.json", {"status": "FAILED" if failures else "RUNNING" if active or pending else "PASS",
                       "total": len(jobs), "completed": completed, "failed": failures,
                       "active": list(active.values()), "pending": pending, "updated_unix_s": time.time()})
    assert not failures, failures


if __name__ == "__main__":
    main()
