#!/usr/bin/env python3
"""K and L restore sweep on the sealed native sparse selections.

The grid is fixed before any timing result in this directory is read.
Checkpoint, documents, and block size match the sealed component protocol.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np

from moonkvsim.aegiskv.evaluation_native_transfer import placements, simulate

ROOT = Path(__file__).resolve().parents[5]
INPUTS = (
    ROOT
    / "benchmark/AegisKV/experiments/evaluation-20260924/native-transfer-postreview-v2/inputs"
)
OUT = ROOT / "benchmark/AegisKV/experiments/evaluation-20260924/sparse-restore-32gbs"
MODELS = ("NOSA-8B", "NSA-8B", "MiniCPM4.1-8B")
BOOKS = ("10146", "10321", "10356")
CHECKPOINT = 32000
QUERIES = 256
BANDWIDTH = 32
COMPUTES = (0, 256_000)
KS = (4, 16, 64)
LS = (1, 4, 8, 32)
METHODS = ("DRAM", "Current", "Recency", "Oracle")


def protocol():
    return {
        "schema": "aegiskv.sparse-restore-32gbs.v1",
        "status": "frozen_before_execution",
        "models": list(MODELS),
        "documents": list(BOOKS),
        "checkpoint_tokens": CHECKPOINT,
        "future_queries": QUERIES,
        "bandwidth_GBps": BANDWIDTH,
        "layer_compute_ns": list(COMPUTES),
        "K": list(KS),
        "L": list(LS),
        "methods": list(METHODS),
        "why": (
            "H2D is the system's 32 GB/s link and is not swept. "
            "K and L are the copy's own parameters. "
            "Compute 0 isolates the transfer; 256 us/layer is the forward overlap "
            "used with that fixed link. Neither was chosen from this sweep's outcomes."
        ),
    }


def jobs():
    seen = set()
    for k in KS:
        seen.add((k, 4))
    for depth in LS:
        seen.add((16, depth))
    return sorted(seen)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "PROTOCOL.json"
    payload = protocol()
    if path.exists() and json.loads(path.read_text()) != payload:
        raise SystemExit("existing protocol differs")
    if not path.exists():
        path.write_text(json.dumps(payload, indent=2) + "\n")
    rows = []
    for model in MODELS:
        for book in BOOKS:
            with np.load(INPUTS / f"{model}-{book}.npz") as data:
                chunks = data["chunks"]
                future = data["future"][:, :QUERIES]
            for k, depth in jobs():
                prepared, background, _counts = placements(
                    chunks, future, CHECKPOINT, k=k, depth=depth
                )
                for method in METHODS:
                    for compute in COMPUTES:
                        summary, *_rest = simulate(
                            future,
                            CHECKPOINT,
                            prepared[method],
                            background,
                            BANDWIDTH,
                            compute,
                        )
                        rows.append(
                            {
                                "model": model,
                                "book_id": book,
                                "K": k,
                                "L": depth,
                                "method": method,
                                "bandwidth_GBps": BANDWIDTH,
                                "layer_compute_ns": compute,
                                "exposed_wait_ns": summary["exposed_wait_ns"],
                                "finish_ns": summary["raw_component_finish_ns"],
                                "resident_demanded_bytes": summary["resident_demanded_bytes"],
                                "demanded_unique_bytes": summary["demanded_unique_bytes"],
                                "initial_resident_bytes": summary["initial_resident_bytes"],
                            }
                        )
                        print(model, book, f"K{k}", f"L{depth}", method, compute, flush=True)
    with (OUT / "results.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (OUT / "STATUS.json").write_text(json.dumps({"status": "COMPLETE", "rows": len(rows)}) + "\n")
    print("rows", len(rows))


if __name__ == "__main__":
    main()
