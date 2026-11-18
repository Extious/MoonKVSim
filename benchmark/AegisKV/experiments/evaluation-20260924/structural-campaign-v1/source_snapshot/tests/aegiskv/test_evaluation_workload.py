import json

import pytest

from moonkvsim.aegiskv.evaluation_workload import (
    SCHEMA,
    file_sha256,
    load_fanoutqa_agents,
    source_answers,
    validate_fanoutqa_record,
)
from moonkvsim.common.hash import sha256_json


def record(name, parents=()):
    prompt = [1, 2, 3]
    parent_ids = [f"fanoutqa:w:{parent}" for parent in parents]
    return {
        "workflow_id": "w",
        "span_id": f"fanoutqa:w:{name}",
        "agent_id": "fanout-root",
        "evidence_class": "public_human_dag_modeled_prompt_replay",
        "token_count_mode": "qwen3_token_ids",
        "truncated": False,
        "parent_span_ids": parent_ids,
        "parent_edge_origin": "observed" if parents else "none",
        "parent_edges": [{"parent_span_id": parent, "origin": "observed"} for parent in parent_ids],
        "messages_or_token_ids": {
            "kind": "token_ids",
            "sha256": sha256_json(prompt),
            "value": prompt,
        },
        "prompt_token_ids_hash": sha256_json(prompt),
        "prompt_tokens": 3,
        "output_tokens": 1,
    }


@pytest.mark.parametrize(
    "mutation,match",
    [
        (lambda r: r.update(parent_edge_origin="inferred"), "inferred dependencies"),
        (lambda r: r.update(token_count_mode="source_hash_blocks_64"), "exact, untruncated"),
        (lambda r: r["messages_or_token_ids"]["value"].append(4), "hash mismatch"),
        (lambda r: r.update(prompt_tokens=4), "count mismatch"),
    ],
)
def test_conversion_rejects_inferred_dags_and_token_surrogates(mutation, match):
    row = record("final", ("a",))
    mutation(row)
    with pytest.raises(ValueError, match=match):
        validate_fanoutqa_record(row)


def make_bundle(tmp_path):
    source = tmp_path / "source.jsonl"
    records = [record("a"), record("final", ("a",))]
    source.write_text("".join(json.dumps(row) + "\n" for row in records))
    mapping = tmp_path / "mapping.jsonl"
    rows = []
    for i, row in enumerate(records):
        rows.append(
            {
                "source_row_zero_based": i,
                "workflow": "w",
                "name": "a" if i == 0 else "final",
                "predecessors": [] if i == 0 else ["a"],
                "source_span_id": row["span_id"],
                "prompt_sha256": sha256_json([1, 2, 3]),
                "output_token_ids": [9],
                "output_sha256": sha256_json([9]),
                "question": "A task",
                "role": "aggregator",
            }
        )
    mapping.write_text("".join(json.dumps(row) + "\n" for row in rows))
    bundle = tmp_path / "bundle.json"
    bundle.write_text(
        json.dumps(
            {
                "schema": SCHEMA,
                "model": "Qwen/Qwen3-8B",
                "workflow_ids": ["w"],
                "source_workload": {"path": str(source), "sha256": file_sha256(source)},
                "task_mapping": {"path": str(mapping), "sha256": file_sha256(mapping)},
                "workflow_request_counts": {"w": 2},
                "workflow_max_context_tokens": {"w": 4},
            }
        )
    )
    return bundle, source


def test_shared_legacy_agent_label_does_not_merge_tasks_or_drop_dependency(tmp_path):
    bundle, _ = make_bundle(tmp_path)
    agents = load_fanoutqa_agents(bundle, prior_ns=7)
    assert [agent.name for agent in agents] == ["a", "final"]
    assert agents[1].predecessors == ("a",)
    assert all(len(agent.calls) == 1 for agent in agents)
    assert agents[0].calls[0].tokens == (1, 2, 3, 9)
    assert all(agent.prior_ns == 7 for agent in agents)


def test_source_drift_is_rejected_before_loading_tokens(tmp_path):
    bundle, source = make_bundle(tmp_path)
    source.write_text(source.read_text().replace('"output_tokens": 1', '"output_tokens": 2'))
    with pytest.raises(ValueError, match="source hash mismatch"):
        load_fanoutqa_agents(bundle)


@pytest.mark.parametrize(
    "kwargs,match",
    [
        ({"workflow_ids": ["w", "w"]}, "repetition"),
        ({"max_context_tokens": 3}, "whole workflows exceed"),
        ({"target_model": "Llama-3.1-70B"}, "tokenizer equivalence"),
    ],
)
def test_no_repetition_partial_dag_or_cross_model_tokenization(tmp_path, kwargs, match):
    bundle, _ = make_bundle(tmp_path)
    with pytest.raises(ValueError, match=match):
        load_fanoutqa_agents(bundle, **kwargs)


def test_structured_answers_use_same_canonical_text_as_original_normalizer():
    answers = source_answers(
        [
            {
                "id": "w",
                "question": "root",
                "answer": ["x", "y"],
                "decomposition": [{"id": "a", "question": "child", "answer": {"z": 1, "a": 2}}],
            }
        ]
    )
    assert answers["fanoutqa:w:a"] == ('{"a":2,"z":1}', "child")
    assert answers["fanoutqa:w:final"] == ('["x","y"]', "root")
