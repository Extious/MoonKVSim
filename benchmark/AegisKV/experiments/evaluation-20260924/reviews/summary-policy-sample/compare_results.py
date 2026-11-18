"""Check exact old/new serialized summaries, retaining adverse timing measurements."""

import gzip
import json
from pathlib import Path


def main():
    evidence = Path(__file__).resolve().parent
    expected = [
        f"history_reuse-n{n}-s7-aegiskv-{fault}"
        for n in (8, 32)
        for fault in ("F0", "left.decode")
    ]
    rows = []
    for job in expected:
        old, new = (evidence / "runs" / variant / job for variant in ("old", "optimized"))
        if not (old / "TIMING.json").exists() or not (new / "TIMING.json").exists():
            continue
        before, after = (json.loads((p / "TIMING.json").read_text()) for p in (old, new))
        exact_files = ["summary.json", "config.json", "failure.json"]
        for name in exact_files:
            assert (old / name).read_bytes() == (new / name).read_bytes(), (job, name)
        for name in ("events.jsonl.gz", "flows.jsonl.gz"):
            assert gzip.decompress((old / name).read_bytes()) == gzip.decompress(
                (new / name).read_bytes()
            ), (job, name)
        rows.append(
            dict(
                id=job,
                summary_identical=True,
                events_and_flows_identical=True,
                summary_sha256=before["summary_sha256"],
                old_wall_seconds=before["wall_seconds"],
                optimized_wall_seconds=after["wall_seconds"],
                wall_speedup=before["wall_seconds"] / after["wall_seconds"],
                old_cpu_seconds=before["cpu_seconds"],
                optimized_cpu_seconds=after["cpu_seconds"],
                cpu_speedup=before["cpu_seconds"] / after["cpu_seconds"],
                old_duration_calls=sum(
                    before["profile_duration_cache"][k] for k in ("hits", "misses")
                ),
                optimized_duration_calls=sum(
                    after["profile_duration_cache"][k] for k in ("hits", "misses")
                ),
            )
        )
    result = dict(
        status="COMPLETE" if len(rows) == len(expected) else "PARTIAL",
        expected_pairs=expected,
        compared_pairs=len(rows),
        timing_scope="one process per cell on a concurrently used host; no confidence interval",
        source="isolated current source copies, not original structural campaign workers",
        pairs=rows,
    )
    (evidence / "RESULTS.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
