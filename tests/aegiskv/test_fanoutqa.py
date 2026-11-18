from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from moonkvsim.aegiskv.fanoutqa import (
    FanOutQADurationModel,
    load_frozen_fanoutqa_records,
    normalize_task,
)


class _Tokenizer:
    def encode(self, sequence: str, add_special_tokens: bool = False) -> SimpleNamespace:
        assert add_special_tokens is False
        return SimpleNamespace(ids=[ord(character) for character in sequence])


def test_fanoutqa_normalizer_preserves_human_dag_and_adds_one_final_sink() -> None:
    task = {
        "id": "task-0",
        "question": "Combine two facts.",
        "answer": "alpha and beta",
        "decomposition": [
            {
                "id": "leaf-a",
                "question": "What is A?",
                "answer": "alpha",
                "depends_on": [],
                "evidence": {"pageid": 1, "revid": 11, "title": "A"},
                "decomposition": [],
            },
            {
                "id": "leaf-b",
                "question": "What is B after A?",
                "answer": "beta",
                "depends_on": ["leaf-a"],
                "evidence": {"pageid": 2, "revid": 22, "title": "B"},
                "decomposition": [],
            },
        ],
    }
    result = normalize_task(
        task,
        workflow_line=1,
        tokenizer=_Tokenizer(),
        tokenizer_fingerprint="a" * 64,
        evidence_text_by_revision={11: "Evidence A.", 22: "Evidence B."},
        duration_model=FanOutQADurationModel(),
    )

    records = {record["span_id"]: record for record in result.records}
    assert set(records) == {
        "fanoutqa:task-0:leaf-a",
        "fanoutqa:task-0:leaf-b",
        "fanoutqa:task-0:final",
    }
    assert records["fanoutqa:task-0:leaf-b"]["parent_span_ids"] == ["fanoutqa:task-0:leaf-a"]
    assert records["fanoutqa:task-0:final"]["parent_span_ids"] == [
        "fanoutqa:task-0:leaf-a",
        "fanoutqa:task-0:leaf-b",
    ]
    assert all(record["token_count_mode"] == "qwen3_token_ids" for record in records.values())
    assert all(record["truncated"] is False for record in records.values())
    assert all(
        sum(record["source_hash_block_token_counts"]) == record["prompt_tokens"]
        for record in records.values()
    )


def test_frozen_loader_retains_exact_ids_only_when_requested(tmp_path: Path) -> None:
    task = {
        "id": "task-token-retention",
        "question": "Find one fact.",
        "answer": "alpha",
        "decomposition": [
            {
                "id": "leaf",
                "question": "What is A?",
                "answer": "alpha",
                "depends_on": [],
                "evidence": {"pageid": 1, "revid": 11, "title": "A"},
                "decomposition": [],
            }
        ],
    }
    result = normalize_task(
        task,
        workflow_line=1,
        tokenizer=_Tokenizer(),
        tokenizer_fingerprint="a" * 64,
        evidence_text_by_revision={11: "Evidence A."},
        duration_model=FanOutQADurationModel(),
    )
    path = tmp_path / "fanoutqa.jsonl"
    path.write_text(
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in result.records),
        encoding="utf-8",
    )
    workflow_id = str(result.records[0]["workflow_id"])

    compact = load_frozen_fanoutqa_records(
        path,
        expected_workflow_ids=[workflow_id],
        tokenizer_fingerprint="a" * 64,
    )
    exact = load_frozen_fanoutqa_records(
        path,
        expected_workflow_ids=[workflow_id],
        tokenizer_fingerprint="a" * 64,
        retain_token_ids=True,
    )

    assert all(record["messages_or_token_ids"] is None for record in compact)
    assert all(record["messages_or_token_ids"]["kind"] == "token_ids" for record in exact)
