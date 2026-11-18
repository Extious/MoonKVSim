"""Check old main structural EOS exposure without equating request finish with EOS."""

from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_bytes())


def main():
    campaign = Path(__file__).resolve().parent.parent / "structural-campaign-v1"
    plan = read(campaign / "PLAN.json")
    profile_path = campaign / plan["profile"]
    assert sha(profile_path) == plan["profile_sha256"]
    profile = read(profile_path)
    minimum = min(r["latency_ns"] for r in profile["rows"] if r["stage"] == "decode")
    before, rows, input_hashes = 0, [], {"PLAN.json": sha(campaign / "PLAN.json")}
    input_hashes[plan["profile"]] = sha(profile_path)
    for job in plan["jobs"]:
        if job["workflows"] != 8:
            continue
        path = campaign / "runs" / job["id"] / "summary.json"
        summary = read(path)
        assert summary["complete"]
        input_hashes[str(path.relative_to(campaign))] = sha(path)
        for row in summary["recoveries"]:
            if not row["checkpoint_tokens"]:
                continue
            if row["restore_done_ns"] <= row["first_new_token_ns"]:
                before += 1
                continue
            assert job["config"]["compute_dma_slowdown"] == 0
            workload = plan["workloads"][job["workload_id"]]
            path = campaign / workload["path"]
            content = gzip.decompress(path.read_bytes())
            assert hashlib.sha256(content).hexdigest() == workload["sha256"]
            input_hashes[workload["path"]] = sha(path)
            agents = json.loads(content)
            agent = next(a for a in agents if a["workflow"] + "/" + a["name"] == row["agent"])
            invocation = agent["calls"][row["invocation"]]
            assert len(invocation["prompt"]) + len(invocation["output"]) <= max(
                profile["context_grid"]
            )
            # Recovery explicitly emits one token in the first new-token forward.
            remaining = (
                len(invocation["prompt"])
                + len(invocation["output"])
                - max(len(invocation["prompt"]), row["durable_tokens"])
                - 1
            )
            lag = row["restore_done_ns"] - row["first_new_token_ns"]
            # Conservatively subtract a full layer count per token for integer division.
            lower_bound = remaining * (minimum - job["config"]["layers"])
            assert lower_bound > lag
            rows.append(
                dict(
                    id=job["id"],
                    agent=row["agent"],
                    remaining_output_tokens=remaining,
                    restore_after_first_new_ns=lag,
                    raw_decode_lower_bound_ns=lower_bound,
                    lower_bound_exceeds_restore_lag=lower_bound > lag,
                )
            )
    result = dict(
        evidence="read-only summary/workload/profile arithmetic; no DES execution",
        explanation=(
            "At least the minimum grid shape is required per remaining decode token. "
            "Subtract N ns per token for layer integer division. Bounded interpolation "
            "and zero slowdown preserve this lower bound; no request-finish assumption."
        ),
        minimum_grid_decode_ns=minimum,
        main_checkpoint_recoveries=before + len(rows),
        restore_at_or_before_first_new=before,
        restore_after_first_new=rows,
        input_sha256=input_hashes,
        source_sha256=sha(Path(__file__)),
    )
    Path(__file__).with_name("STRUCTURAL_EOS_BOUNDARY_CHECK.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n"
    )
    print(f"{before} restored by first-new-token; {len(rows)} pass remaining-decode bound")


if __name__ == "__main__":
    main()
