"""Audited evaluation inputs, with workload construction kept distinct from traces.

FanOutQA supplies human task dependencies, not observed model invocations. Each
source subquestion (and the added final aggregation) maps to one Agent task with
one invocation. The historical normalizer's shared ``fanout-root`` label is not
an Agent-task identity: merging its calls can change the dependency graph.

The compact bundle references, hashes, and preserves the frozen prompts. Exact
output IDs are recovered from source answers using the pinned tokenizer. No
prompt clipping, repeated DAGs, inferred edges, or synthetic token IDs are used.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from moonkvsim.aegiskv.current.model import Agent, Invocation
from moonkvsim.aegiskv.fanoutqa import load_qwen3_tokenizer, load_source_tasks
from moonkvsim.common.hash import sha256_json

SCHEMA = "moonkvsim.aegiskv.evaluation_workload.v1"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _binding(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve()),
        "sha256": file_sha256(path),
        "size_bytes": path.stat().st_size,
    }


def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError("workload row must be an object")
            yield value


def _answer_text(value: object) -> str:
    if value is None or value == "":
        raise ValueError("source answer is empty")
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def source_answers(tasks: Sequence[Mapping[str, Any]]) -> dict[str, tuple[str, str]]:
    """Return exact source answer text and submission-visible question per span."""
    result: dict[str, tuple[str, str]] = {}
    for task in tasks:
        workflow = str(task["id"])

        def walk(nodes: Sequence[Mapping[str, Any]], workflow: str = workflow) -> None:
            for node in nodes:
                key = f"fanoutqa:{workflow}:{node['id']}"
                if key in result:
                    raise ValueError(f"duplicate source subquestion {key}")
                result[key] = (_answer_text(node["answer"]), str(node["question"]))
                walk(node.get("decomposition", []))

        walk(task["decomposition"])
        result[f"fanoutqa:{workflow}:final"] = (_answer_text(task["answer"]), str(task["question"]))
    return result


def _task_name(span_id: str, workflow: str) -> str:
    prefix = f"fanoutqa:{workflow}:"
    if not span_id.startswith(prefix) or "/" in span_id:
        raise ValueError("span identity does not belong to the declared workflow")
    return span_id[len(prefix) :]


def validate_fanoutqa_record(record: Mapping[str, Any]) -> tuple[int, ...]:
    """Reject ambiguous dependencies and token surrogates before conversion."""
    if record.get("evidence_class") != "public_human_dag_modeled_prompt_replay":
        raise ValueError("expected explicitly constructed FanOutQA requests")
    if record.get("token_count_mode") != "qwen3_token_ids" or record.get("truncated"):
        raise ValueError("exact, untruncated Qwen3 token IDs are required")
    parents = record["parent_span_ids"]
    if record.get("parent_edge_origin") != ("observed" if parents else "none"):
        raise ValueError("inferred dependencies are not a fixed task DAG")
    edges = record.get("parent_edges", [])
    if [edge["parent_span_id"] for edge in edges] != parents or any(
        edge.get("origin") != "observed" for edge in edges
    ):
        raise ValueError("parent edge audit differs from task dependencies")
    payload = record["messages_or_token_ids"]
    if payload.get("kind") != "token_ids":
        raise ValueError("token ID payload is required")
    prompt = tuple(payload["value"])
    if not prompt or any(type(token) is not int or token < 0 for token in prompt):
        raise ValueError("invalid prompt token IDs")
    digest = sha256_json(prompt)
    if digest != payload["sha256"] or digest != record["prompt_token_ids_hash"]:
        raise ValueError("prompt token hash mismatch")
    if len(prompt) != record["prompt_tokens"]:
        raise ValueError("prompt token count mismatch")
    if type(record["output_tokens"]) is not int or record["output_tokens"] <= 0:
        raise ValueError("positive output token count required")
    return prompt


def prepare_fanoutqa_bundle(
    source_workload: Path,
    source_manifest: Path,
    source_questions: Path,
    tokenizer_snapshot: Path,
    output_dir: Path,
    *,
    tokenizer_equivalence: Path | None = None,
) -> dict[str, Any]:
    """Write a compact conversion with per-request and whole-source hashes."""
    manifest = json.loads(source_manifest.read_text())
    source_binding = _binding(source_workload)
    if source_binding["sha256"] != manifest["artifact"]["sha256"]:
        raise ValueError("source workload differs from frozen manifest")
    tokenizer, tokenizer_fingerprint = load_qwen3_tokenizer(tokenizer_snapshot)
    if tokenizer_fingerprint != manifest["normalizer"]["tokenizer_fingerprint"]:
        raise ValueError("tokenizer differs from frozen source")
    answers = source_answers(load_source_tasks(source_questions))
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    workflows: list[str] = []
    counts: Counter[str] = Counter()
    max_context: dict[str, int] = {}
    old_agent_labels: Counter[tuple[str, str]] = Counter()
    prompt_total = output_total = edge_count = 0
    for index, record in enumerate(_read_jsonl(source_workload)):
        prompt = validate_fanoutqa_record(record)
        workflow, span = record["workflow_id"], record["span_id"]
        if span in seen:
            raise ValueError("duplicate source span")
        name = _task_name(span, workflow)
        parents = [_task_name(parent, workflow) for parent in record["parent_span_ids"]]
        if any(parent not in seen for parent in record["parent_span_ids"]):
            raise ValueError("source is not a complete topologically ordered DAG")
        if workflow not in counts:
            workflows.append(workflow)
        answer, question = answers[span]
        output = list(tokenizer.encode(answer, add_special_tokens=False).ids)
        if len(output) != record["output_tokens"]:
            raise ValueError(f"recovered output token count differs at {span}")
        if record["model_id"] != manifest["normalizer"]["model_id"]:
            raise ValueError("mixed model input requires an explicit mapping")
        rows.append(
            {
                "workflow": workflow,
                "name": name,
                "predecessors": parents,
                "role": record["raw_request_type"],
                "question": question,
                "source_row_zero_based": index,
                "source_span_id": span,
                "source_agent_label": record["agent_id"],
                "prompt_tokens": len(prompt),
                "prompt_sha256": sha256_json(prompt),
                "output_token_ids": output,
                "output_sha256": sha256_json(output),
                "model": record["model_id"],
                "model_revision": record["model_revision"],
            }
        )
        seen.add(span)
        counts[workflow] += 1
        old_agent_labels[(workflow, record["agent_id"])] += 1
        max_context[workflow] = max(max_context.get(workflow, 0), len(prompt) + len(output))
        prompt_total += len(prompt)
        output_total += len(output)
        edge_count += len(parents)
    if workflows != manifest["selection"]["selected_workflow_ids"]:
        raise ValueError("workflow identity/order differs from frozen selection")
    if len(rows) != manifest["artifact"]["record_count"]:
        raise ValueError("request count differs from frozen source")
    output_dir.mkdir(parents=True, exist_ok=True)
    mapping_path = output_dir / "fanoutqa-agent-tasks.jsonl"
    bundle_path = output_dir / "fanoutqa-bundle.json"
    if mapping_path.exists() or bundle_path.exists():
        raise FileExistsError("refusing to overwrite an existing workload bundle")
    mapping_path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
            for row in rows
        )
    )
    bundle: dict[str, Any] = {
        "schema": SCHEMA,
        "source_workload": source_binding,
        "source_manifest": _binding(source_manifest),
        "source_questions": _binding(source_questions),
        "source_dataset": manifest["source"],
        "task_mapping": _binding(mapping_path),
        "tokenizer": {
            "fingerprint": tokenizer_fingerprint,
            "files": [
                _binding(tokenizer_snapshot / name)
                for name in ("tokenizer.json", "tokenizer_config.json")
            ],
        },
        "model": manifest["normalizer"]["model_id"],
        "model_revision": manifest["normalizer"]["model_revision"],
        "workflow_ids": workflows,
        "workflow_request_counts": dict(counts),
        "workflow_max_context_tokens": max_context,
        "audit": {
            "workflows": len(workflows),
            "agents": len(rows),
            "invocations": len(rows),
            "edges": edge_count,
            "prompt_tokens": prompt_total,
            "output_tokens": output_total,
            "source_labels_split_into_independent_tasks": sum(
                n > 1 for n in old_agent_labels.values()
            ),
            "prompt_ids_preserved": True,
            "output_ids_recovered_and_count_verified": True,
            "source_order_preserved": True,
            "complete_workflows_preserved": True,
            "workflow_repetitions": 1,
            "truncated_requests": 0,
            "synthetic_token_ids": 0,
            "source_sha256_after": file_sha256(source_workload),
        },
        "semantics": {
            "task_dag": "human decomposition and depends_on, plus constructed final aggregation",
            "agent_mapping": (
                "one source subquestion/final span is one single-invocation Agent task"
            ),
            "source_agent_labels": "fanout-root groups unrelated aggregator tasks; never merge it",
            "request_content": (
                "constructed evidence-provided prompts; source answers as fixed outputs"
            ),
            "historically_observed_requests": False,
            "source_timing_used": False,
            "tool_delays": "absent from source; not invented",
            "history_reuse_claim": "no within-Agent follow-up invocation in this corpus mapping",
            "arrival_process": "campaign-specified modeled workflow arrivals; no source timestamps",
            "remaining_time_prior": (
                "caller supplied independent prior, never source completion time"
            ),
            "tokenizer_portability": "only models covered by verified equivalence evidence",
        },
    }
    if tokenizer_equivalence is not None:
        equivalence = json.loads(tokenizer_equivalence.read_text())
        if (
            equivalence.get("status") != "PASS"
            or equivalence.get("comparison") != "byte_identical_files_at_pinned_model_revisions"
        ):
            raise ValueError("tokenizer equivalence evidence is not byte-identical pinned files")
        for name in ("tokenizer.json", "tokenizer_config.json"):
            if file_sha256(tokenizer_snapshot / name) != equivalence["files"][name]:
                raise ValueError("local tokenizer files differ from equivalence evidence")
        bundle["tokenizer_equivalence"] = _binding(tokenizer_equivalence)
        bundle["equivalent_models"] = equivalence["models"]
    if bundle["audit"]["source_sha256_after"] != source_binding["sha256"]:
        raise ValueError("source workload changed during conversion")
    bundle_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return bundle


def _verify_binding(binding: Mapping[str, Any]) -> Path:
    path = Path(binding["path"])
    if file_sha256(path) != binding["sha256"]:
        raise ValueError(f"bound source hash mismatch: {path}")
    return path


def load_fanoutqa_agents(
    bundle_path: Path,
    *,
    workflow_ids: Sequence[str] | None = None,
    prior_ns: int = 10_000_000_000,
    role_priors_ns: Mapping[str, int] | None = None,
    arrival_interval_ns: int = 0,
    target_model: str | None = None,
    max_context_tokens: int | None = None,
) -> tuple[Agent, ...]:
    """Load exact tokens without silently selecting, clipping, or repeating work.

    A context-ineligible selected workflow raises rather than losing branches.
    Explicitly select eligible IDs from ``workflow_max_context_tokens`` first.
    """
    bundle = json.loads(bundle_path.read_text())
    if bundle.get("schema") != SCHEMA:
        raise ValueError("unsupported evaluation bundle schema")
    source = _verify_binding(bundle["source_workload"])
    mapping = _verify_binding(bundle["task_mapping"])
    model = target_model or bundle["model"]
    if model != bundle["model"]:
        if "tokenizer_equivalence" not in bundle:
            raise ValueError("target model has no pinned tokenizer equivalence")
        equivalence_path = _verify_binding(bundle["tokenizer_equivalence"])
        equivalence = json.loads(equivalence_path.read_text())
        if not any(item["model_id"] == model for item in equivalence["models"]):
            raise ValueError("target model has no pinned tokenizer equivalence")
    requested = list(bundle["workflow_ids"] if workflow_ids is None else workflow_ids)
    if len(set(requested)) != len(requested):
        raise ValueError("workflow repetition is forbidden")
    if not requested or not set(requested).issubset(bundle["workflow_ids"]):
        raise ValueError("unknown or empty workflow selection")
    if prior_ns <= 0 or arrival_interval_ns < 0:
        raise ValueError("invalid independent prior or modeled arrival interval")
    if max_context_tokens is not None:
        rejected = [
            workflow
            for workflow in requested
            if bundle["workflow_max_context_tokens"][workflow] > max_context_tokens
        ]
        if rejected:
            raise ValueError(f"whole workflows exceed selected model context: {rejected}")
    positions = {workflow: index for index, workflow in enumerate(requested)}
    metadata = {
        row["source_row_zero_based"]: row
        for row in _read_jsonl(mapping)
        if row["workflow"] in positions
    }
    agents: list[Agent] = []
    for index, record in enumerate(_read_jsonl(source)):
        if index not in metadata:
            continue
        row = metadata[index]
        prompt = validate_fanoutqa_record(record)
        output = tuple(row["output_token_ids"])
        if (
            record["span_id"] != row["source_span_id"]
            or sha256_json(prompt) != row["prompt_sha256"]
            or sha256_json(output) != row["output_sha256"]
        ):
            raise ValueError("mapping does not preserve source token/span identity")
        agents.append(
            Agent(
                workflow=row["workflow"],
                name=row["name"],
                predecessors=tuple(row["predecessors"]),
                calls=(Invocation(prompt, output, model=model, text=row["question"]),),
                prior_ns=(role_priors_ns or {}).get(row["role"], prior_ns),
                role=row["role"],
                release_ns=positions[row["workflow"]] * arrival_interval_ns,
            )
        )
    expected = sum(bundle["workflow_request_counts"][workflow] for workflow in requested)
    if len(agents) != expected:
        raise ValueError("selected workflow lost an invocation")
    return tuple(agents)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-workload", required=True, type=Path)
    parser.add_argument("--source-manifest", required=True, type=Path)
    parser.add_argument("--source-questions", required=True, type=Path)
    parser.add_argument("--tokenizer-snapshot", required=True, type=Path)
    parser.add_argument("--tokenizer-equivalence", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    result = prepare_fanoutqa_bundle(**vars(args))
    print(json.dumps(result["audit"], sort_keys=True))


if __name__ == "__main__":
    main()
