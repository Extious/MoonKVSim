"""Independent raw-count aggregation; no model forward or replay is executed."""

import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean

OUT = Path(__file__).resolve().parent
ROOT = OUT.parent.parent
SOURCE = ROOT / "native-topk-warm"
METHODS = {
    "decay_hysteresis": "Current",
    "recency": "Recency",
    "future_oracle": "Oracle",
    "cumulative_no_hysteresis": "Cumulative/no hysteresis",
    "frequency_static": "Static cumulative",
    "uniform": "Uniform",
}
K16_METHODS = {"decay_hysteresis", "recency", "future_oracle"}


def read(path):
    with path.open() as stream:
        return list(csv.DictReader(stream))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_csv(path, rows):
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


raw = read(SOURCE / "layer-checkpoint-results.csv")
groups = defaultdict(list)
for row in raw:
    if (
        int(row["K"]) in (16, 64)
        and int(row["layer"]) <= 4
        and row["method"] in METHODS
        and (int(row["K"]) == 64 or row["method"] in K16_METHODS)
    ):
        groups[row["model"], row["book_id"], int(row["K"]), row["method"]].append(row)
documents = []
for (model, book, k, method), rows in sorted(groups.items()):
    assert len(rows) == 8
    assert {(int(r["layer"]), int(r["checkpoint_tokens"])) for r in rows} == {
        (layer, checkpoint) for layer in range(1, 5) for checkpoint in (32000, 32256)
    }
    wanted = sum(int(r["demanded_blocks"]) for r in rows)
    covered = sum(int(r["covered_blocks"]) for r in rows)
    events = sum(int(r["query_block_events"]) for r in rows)
    event_hits = sum(int(r["covered_query_block_events"]) for r in rows)
    documents.append(
        dict(
            model=model,
            book_id=book,
            K=k,
            L=4,
            method=method,
            distinct_covered=covered,
            distinct_demanded=wanted,
            event_covered=event_hits,
            event_demanded=events,
            distinct_coverage=covered / wanted,
            event_coverage=event_hits / events,
        )
    )
reference = {
    (r["model"], r["book_id"], int(r["K"]), r["method"]): r
    for r in read(SOURCE / "document-results.csv")
    if int(r["first_L_layers"]) == 4
}
for row in documents:
    other = reference[row["model"], row["book_id"], row["K"], row["method"]]
    assert abs(row["distinct_coverage"] - float(other["demand_weighted_coverage"])) < 1e-14
    assert abs(row["event_coverage"] - float(other["event_weighted_coverage"])) < 1e-14
summary = []
for model in sorted({r["model"] for r in documents}):
    for k in (16, 64):
        for method in METHODS:
            if k == 16 and method not in K16_METHODS:
                continue
            group = [
                r for r in documents if (r["model"], r["K"], r["method"]) == (model, k, method)
            ]
            assert {r["book_id"] for r in group} == {"10146", "10321", "10356"}
            summary.append(
                dict(
                    model=model,
                    K=k,
                    L=4,
                    method=METHODS[method],
                    documents=3,
                    **{
                        f"{metric}_{stat}_percent": fn([100 * r[metric] for r in group])
                        for metric in ("distinct_coverage", "event_coverage")
                        for stat, fn in (("mean", mean), ("min", min), ("max", max))
                    },
                )
            )
write_csv(OUT / "document-recomputed.csv", documents)
write_csv(OUT / "operating-point-coverage.csv", summary)
lines = [
    "# Independent native Top-K operating-point extraction",
    "",
    "Recomputed directly from integer counts in the original warm layer/window CSV. For each document, sum the covered and demanded counts across the first four layers and both fixed heldout windows, take their ratio, then average three document ratios equally. Min/max are document ranges, not confidence intervals. Exact document numerators/denominators are retained in document-recomputed.csv.",
    "",
    "| Model | K | Method | Distinct historical blocks (%) | Query/block events (%) |",
    "|---|---:|---|---:|---:|",
]
for r in summary:
    lines.append(
        f"| {r['model']} | {r['K']} | {r['method']} | {r['distinct_coverage_mean_percent']:.6f} | {r['event_coverage_mean_percent']:.6f} |"
    )
lines += [
    "",
    "Distinct coverage counts each historical block once per layer/window; event coverage counts every query/block incidence, so repeatedly requested blocks have greater weight. Both exclude the new post-checkpoint tail. Neither metric is a total request hit rate, physical transfer measurement, or recovery/WCT result. Oracle chooses using the future window; it is an explicitly noncausal same-K coverage upper comparator.",
    "",
    "The primary WCT campaign PLAN uses K=16 with Qwen3-8B L=11 and Qwen3-32B L=1. Its model/attention traces also differ: the native diagnostic uses NOSA-8B, NSA-8B and MiniCPM4.1-8B. Therefore even the K=16/L=4 extraction matches only K, not the WCT model or protected-layer depth. K=64/L=4 differs in both K and depth. The diagnostic cannot substantiate native recovery coverage at the primary WCT operating points, and the WCT runs cannot validate native sparse-cache hit rates.",
    "",
    "Causal ranking sees only prior observed queries; Current is warm from q0, Recency uses historical positions, and Oracle is future-aware. This extraction introduces no reruns, parameter changes or sample selection; it reports all three fixed models and documents, including negative Current-versus-Recency differences.",
]
(OUT / "RESULTS.md").write_text("\n".join(lines) + "\n")
inputs = [
    SOURCE / "layer-checkpoint-results.csv",
    SOURCE / "document-results.csv",
    SOURCE / "summary.csv",
    ROOT / "formal-core-v1/PLAN.json",
]
(OUT / "AUDIT.json").write_text(
    json.dumps(
        dict(
            passed=True,
            document_rows=len(documents),
            summary_rows=len(summary),
            raw_count_reaggregation_matches_original_document_values=True,
            source_sha256={str(p.relative_to(ROOT)): digest(p) for p in inputs},
            script_sha256=digest(Path(__file__)),
            output_sha256={
                p.name: digest(p)
                for p in (
                    OUT / "document-recomputed.csv",
                    OUT / "operating-point-coverage.csv",
                    OUT / "RESULTS.md",
                )
            },
        ),
        indent=2,
    )
    + "\n"
)
print("\n".join(lines))
