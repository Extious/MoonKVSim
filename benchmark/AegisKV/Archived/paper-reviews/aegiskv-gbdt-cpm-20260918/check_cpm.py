"""Independent path-enumeration check of the paper's CPM recurrences.

This checks the mathematical specification, not a serving implementation or
the accuracy of the GBDT predictor. All times below are synthetic.
"""
import itertools
import json
from pathlib import Path


def cpm(durations, edges):
    n = len(durations)
    parents = [[a for a, b in edges if b == v] for v in range(n)]
    children = [[b for a, b in edges if a == v] for v in range(n)]
    earliest, latest = [0] * n, [0] * n
    for v in range(n):
        earliest[v] = durations[v] + max((earliest[a] for a in parents[v]), default=0)
    horizon = max(earliest, default=0)
    for v in reversed(range(n)):
        latest[v] = min((latest[b] - durations[b] for b in children[v]), default=horizon)
    return horizon, [max(0, latest[v] - earliest[v]) for v in range(n)]


def enumerate_paths(n, edges):
    roots = [v for v in range(n) if all(b != v for _, b in edges)]

    def visit(path):
        children = [b for a, b in edges if a == path[-1]]
        if not children:
            yield path
        for child in children:
            yield from visit(path + [child])

    for root in roots:
        yield from visit([root])


candidate_edges = list(itertools.combinations(range(4), 2))
cases = 0
for mask in itertools.product((False, True), repeat=len(candidate_edges)):
    edges = [edge for edge, keep in zip(candidate_edges, mask) if keep]
    paths = list(enumerate_paths(4, edges))
    for durations in itertools.product((1, 3), repeat=4):
        lengths = [sum(durations[v] for v in path) for path in paths]
        horizon = max(lengths)
        oracle = [
            horizon - max(length for path, length in zip(paths, lengths) if v in path)
            for v in range(4)
        ]
        actual_horizon, actual_slack = cpm(durations, edges)
        assert actual_horizon == horizon
        assert actual_slack == oracle, (durations, edges, actual_slack, oracle)
        cases += 1

examples = {
    "parallel_branches_20_50": {"durations": [20, 50], "edges": [], "slack": [30, 0]},
    "sequential_agents": {"durations": [20, 50], "edges": [(0, 1)], "slack": [0, 0]},
    "fork_join_segments": {"durations": [5, 20, 50, 5], "edges": [(0, 1), (0, 2), (1, 3), (2, 3)], "slack": [0, 30, 0, 0]},
    "empty_workflow": {"durations": [], "edges": [], "slack": []},
}
for example in examples.values():
    horizon, slack = cpm(example["durations"], example["edges"])
    assert slack == example["slack"]
    example["horizon"] = horizon

report = {
    "scope": "Mathematical paper-specification check, not runtime or prediction validation",
    "oracle": "Workflow longest path minus longest source-to-sink path containing each node",
    "exhaustive_four_node_cases": cases,
    "examples": examples,
    "result": "pass",
}
Path(__file__).with_name("cpm-check.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps({"cases": cases, "examples": len(examples), "result": "pass"}))
