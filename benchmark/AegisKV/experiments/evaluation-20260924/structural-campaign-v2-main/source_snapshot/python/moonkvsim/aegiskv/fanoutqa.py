"""FanOutQA Evidence-Provided workload construction for AegisKV studies.

The source questions and dependency graph are human-authored.  Model requests,
prompt text, and timings are deterministic modeled artifacts and are labelled as
such in every record and in the workload manifest.
"""

from __future__ import annotations

import gzip
import hashlib
import html
import json
import os
import struct
import threading
import time
import urllib.parse
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, ClassVar, Final, Protocol, cast

import httpx

from moonkvsim.aegiskv.experiment import QWEN3_8B_MODEL_ID, QWEN3_8B_MODEL_REVISION
from moonkvsim.aegiskv.experiment_workload import CONTEXT_BUCKETS, bucket_name_for
from moonkvsim.common.hash import sha256_json
from moonkvsim.workload.causal_trace import load_normalized_trace_records

FANOUTQA_NORMALIZER_VERSION: Final = "moonkvsim.fanoutqa.v1"
SOURCE_BLOCK_TOKENS: Final = 64
EXPECTED_TASK_COUNT: Final = 310
EXPECTED_SOURCE_SHA256: Final = "b62a9797732c716e6b17ba4086f277d154d747ce2fa01614cb76a3372e7fb88c"
SYSTEM_TEMPLATE: Final = """You are one worker in a fan-out research workflow.
Use only the revision-pinned evidence and completed prerequisite answers supplied
in the request. Preserve names, dates, units, and list membership exactly. Do not
invent facts that are absent from the evidence. Return only the concise answer
needed by the parent workflow; do not add citations, preambles, or analysis. The
workflow engine will combine your answer with sibling results after all declared
dependencies finish. This request is a deterministic serving-simulation prompt,
not an observed historical LLM call.\n\n"""


class FanOutQAError(ValueError):
    """The public source cannot be frozen without changing its task semantics."""


class _UnavailableEvidenceError(FanOutQAError):
    """A source-declared revision is permanently unavailable from MediaWiki."""


class TokenizerLike(Protocol):
    def encode(self, sequence: str, add_special_tokens: bool = False) -> Any: ...


@dataclass(frozen=True, slots=True)
class FanOutQADurationModel:
    """Explicit uncalibrated timing model for constructed Qwen3 requests."""

    prefill_ns_per_token: int = 100_000
    decode_ns_per_token: int = 5_000_000

    def __post_init__(self) -> None:
        if self.prefill_ns_per_token <= 0 or self.decode_ns_per_token <= 0:
            raise ValueError("FanOutQA duration rates must be positive")

    def duration_ns(self, prompt_tokens: int, output_tokens: int) -> int:
        return max(
            1,
            prompt_tokens * self.prefill_ns_per_token + output_tokens * self.decode_ns_per_token,
        )

    def to_dict(self) -> dict[str, int | str | bool]:
        return {
            "kind": "explicit_uncalibrated_linear_token_model",
            "prefill_ns_per_token": self.prefill_ns_per_token,
            "decode_ns_per_token": self.decode_ns_per_token,
            "physically_calibrated": False,
        }


@dataclass(frozen=True, slots=True)
class FanOutQANormalizationResult:
    task_id: str
    records: tuple[dict[str, Any], ...]
    max_context_tokens: int
    max_parallel_roots: int


class _ArticleTextExtractor(HTMLParser):
    _SKIP: ClassVar[frozenset[str]] = frozenset({"script", "style", "template", "noscript"})
    _BREAK: ClassVar[frozenset[str]] = frozenset(
        {"p", "div", "section", "h1", "h2", "h3", "h4", "li", "tr", "td", "th", "br"}
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in self._SKIP:
            self.skip_depth += 1
        elif tag in self._BREAK and not self.skip_depth:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP and self.skip_depth:
            self.skip_depth -= 1
        elif tag in self._BREAK and not self.skip_depth:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip_depth:
            self.parts.append(data)

    def text(self) -> str:
        lines = (" ".join(line.split()) for line in "".join(self.parts).splitlines())
        return "\n".join(line for line in lines if line).strip()


def load_qwen3_tokenizer(snapshot: Path) -> tuple[TokenizerLike, str]:
    """Load the pinned local tokenizer without importing model weights."""

    tokenizer_json = snapshot / "tokenizer.json"
    tokenizer_config = snapshot / "tokenizer_config.json"
    if not tokenizer_json.is_file() or not tokenizer_config.is_file():
        raise FanOutQAError("pinned Qwen3 tokenizer.json and tokenizer_config.json are required")
    try:
        from tokenizers import Tokenizer
    except ImportError as error:
        raise FanOutQAError(
            "FanOutQA preparation requires the optional 'fanoutqa' dependency"
        ) from error
    fingerprint = sha256_json(
        {
            "model_id": QWEN3_8B_MODEL_ID,
            "model_revision": QWEN3_8B_MODEL_REVISION,
            "tokenizer_json_sha256": _sha256_file(tokenizer_json),
            "tokenizer_config_sha256": _sha256_file(tokenizer_config),
        }
    )
    return cast(TokenizerLike, Tokenizer.from_file(tokenizer_json.as_posix())), fingerprint


def load_source_tasks(path: Path) -> tuple[dict[str, Any], ...]:
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != EXPECTED_SOURCE_SHA256:
        raise FanOutQAError("FanOutQA dev source SHA-256 drifted")
    value = json.loads(raw)
    if not isinstance(value, list) or len(value) != EXPECTED_TASK_COUNT:
        raise FanOutQAError(f"FanOutQA dev must contain {EXPECTED_TASK_COUNT} tasks")
    if not all(isinstance(item, dict) for item in value):
        raise FanOutQAError("FanOutQA dev tasks must be objects")
    task_ids = [item.get("id") for item in value]
    if not all(isinstance(item, str) and item for item in task_ids):
        raise FanOutQAError("FanOutQA task IDs must be non-empty strings")
    if len(set(task_ids)) != len(task_ids):
        raise FanOutQAError("FanOutQA task IDs are not unique")
    return tuple(value)


def collect_evidence(tasks: Sequence[Mapping[str, Any]]) -> tuple[dict[str, Any], ...]:
    by_revision: dict[int, dict[str, Any]] = {}

    def walk(nodes: object) -> None:
        if not isinstance(nodes, list):
            raise FanOutQAError("FanOutQA decomposition must be an array")
        for node in nodes:
            if not isinstance(node, Mapping):
                raise FanOutQAError("FanOutQA decomposition node must be an object")
            evidence = node.get("evidence")
            if evidence is not None:
                if not isinstance(evidence, Mapping):
                    raise FanOutQAError("FanOutQA evidence must be an object or null")
                revid = evidence.get("revid")
                pageid = evidence.get("pageid")
                title = evidence.get("title")
                if revid == "###TBD###" or pageid == "###TBD###":
                    walk(node.get("decomposition", []))
                    continue
                if type(revid) is not int or type(pageid) is not int or not isinstance(title, str):
                    raise FanOutQAError("FanOutQA evidence identity is malformed")
                canonical = {"pageid": pageid, "revid": revid, "title": title}
                previous = by_revision.setdefault(revid, canonical)
                if previous != canonical:
                    raise FanOutQAError(f"Wikipedia revision {revid} has conflicting identity")
            walk(node.get("decomposition", []))

    for task in tasks:
        walk(task.get("decomposition"))
    return tuple(by_revision[key] for key in sorted(by_revision))


def fetch_evidence_snapshot(
    evidence: Sequence[Mapping[str, Any]],
    *,
    cache_dir: Path,
    workers: int = 8,
) -> dict[int, str]:
    """Fetch exact Wikipedia revisions with retryable, content-addressed caching."""

    if workers <= 0:
        raise FanOutQAError("evidence fetch workers must be positive")
    cache_dir.mkdir(parents=True, exist_ok=True)
    rate_lock = threading.Lock()
    next_request_at = [0.0]
    client = httpx.Client(
        timeout=60,
        follow_redirects=True,
        limits=httpx.Limits(
            max_connections=workers,
            max_keepalive_connections=workers,
        ),
        headers={
            "User-Agent": (
                "MoonKVSim-FanOutQA-reproduction/0.1 "
                "(academic deterministic revision fetch; "
                "https://github.com/Mooncake-Labs/MoonKVSim)"
            )
        },
    )

    def pace_request() -> None:
        with rate_lock:
            delay_seconds = max(0.0, next_request_at[0] - time.monotonic())
            if delay_seconds:
                time.sleep(delay_seconds)
            next_request_at[0] = time.monotonic() + 0.35

    def fetch(item: Mapping[str, Any]) -> tuple[int, str | None]:
        revid = int(item["revid"])
        pageid = int(item["pageid"])
        cache_path = cache_dir / f"{pageid}-{revid}.txt"
        if cache_path.is_file():
            cached = cache_path.read_text(encoding="utf-8")
            if cached:
                return revid, cached
        url = f"https://en.wikipedia.org/w/rest.php/v1/revision/{revid}/html"
        last_error: Exception | None = None
        for attempt in range(6):
            try:
                pace_request()
                try:
                    response = client.get(url)
                    response.raise_for_status()
                    payload = response.text
                except httpx.HTTPStatusError as rest_error:
                    if rest_error.response.status_code != 404:
                        raise
                    query = urllib.parse.urlencode(
                        {
                            "action": "parse",
                            "oldid": revid,
                            "prop": "text",
                            "format": "json",
                            "formatversion": 2,
                        }
                    )
                    pace_request()
                    action_response = client.get(f"https://en.wikipedia.org/w/api.php?{query}")
                    action_response.raise_for_status()
                    action_value = action_response.json()
                    parsed = action_value.get("parse")
                    action_error = action_value.get("error")
                    if isinstance(action_error, dict) and action_error.get("code") == "nosuchrevid":
                        raise _UnavailableEvidenceError(
                            f"MediaWiki reports no such revision {revid}"
                        ) from rest_error
                    if (
                        not isinstance(parsed, dict)
                        or parsed.get("revid") != revid
                        or parsed.get("pageid") != pageid
                        or not isinstance(parsed.get("text"), str)
                    ):
                        raise _UnavailableEvidenceError(
                            f"MediaWiki oldid {revid} did not preserve its identity"
                        ) from rest_error
                    payload = str(parsed["text"])
                parser = _ArticleTextExtractor()
                parser.feed(payload)
                text = html.unescape(parser.text())
                if not text:
                    raise FanOutQAError(f"Wikipedia revision {revid} normalized to empty text")
                temporary = cache_path.with_name(f".{cache_path.name}.tmp")
                temporary.write_text(text, encoding="utf-8")
                os.replace(temporary, cache_path)
                return revid, text
            except _UnavailableEvidenceError:
                return revid, None
            except (OSError, UnicodeError, httpx.HTTPError, FanOutQAError) as error:
                last_error = error
                if isinstance(error, httpx.HTTPStatusError) and error.response.status_code not in {
                    429,
                    500,
                    502,
                    503,
                    504,
                }:
                    break
                time.sleep(min(16, 2**attempt))
        raise FanOutQAError(f"cannot freeze Wikipedia revision {revid}: {last_error}")

    try:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            pairs = tuple(executor.map(fetch, evidence))
    finally:
        client.close()
    return {revid: text for revid, text in pairs if text is not None}


def normalize_task(
    task: Mapping[str, Any],
    *,
    workflow_line: int,
    tokenizer: TokenizerLike,
    tokenizer_fingerprint: str,
    evidence_text_by_revision: Mapping[int, str],
    duration_model: FanOutQADurationModel,
    max_model_len_tokens: int = 131_072,
) -> FanOutQANormalizationResult:
    task_id = _string(task.get("id"), "task.id")
    root_question = _string(task.get("question"), f"task[{task_id}].question")
    nodes: dict[str, Mapping[str, Any]] = {}
    direct_children: dict[str, tuple[str, ...]] = {}

    def index(raw_nodes: object) -> None:
        if not isinstance(raw_nodes, list):
            raise FanOutQAError(f"task {task_id} decomposition must be an array")
        for raw in raw_nodes:
            if not isinstance(raw, Mapping):
                raise FanOutQAError(f"task {task_id} has a non-object decomposition node")
            node_id = _string(raw.get("id"), f"task[{task_id}].node.id")
            if node_id in nodes:
                raise FanOutQAError(f"task {task_id} duplicates subquestion {node_id}")
            nodes[node_id] = raw
            children = raw.get("decomposition", [])
            if not isinstance(children, list):
                raise FanOutQAError(f"task {task_id} node {node_id} decomposition is invalid")
            direct_children[node_id] = tuple(
                _string(child.get("id"), "child.id") for child in children
            )
            index(children)

    top_level = task.get("decomposition")
    index(top_level)
    if not isinstance(top_level, list) or not top_level:
        raise FanOutQAError(f"task {task_id} has no decomposition")
    answers = {node_id: _answer_text(node.get("answer")) for node_id, node in nodes.items()}
    records: list[dict[str, Any]] = []
    emitted: set[str] = set()
    visiting: set[str] = set()

    def emit(node_id: str) -> None:
        if node_id in emitted:
            return
        if node_id in visiting:
            raise FanOutQAError(f"task {task_id} contains a dependency cycle at {node_id}")
        visiting.add(node_id)
        node = nodes[node_id]
        for child_id in direct_children[node_id]:
            emit(child_id)
        dependencies = node.get("depends_on", [])
        if not isinstance(dependencies, list) or not all(
            isinstance(item, str) for item in dependencies
        ):
            raise FanOutQAError(f"task {task_id} node {node_id} dependencies are invalid")
        parent_node_ids = tuple(dict.fromkeys((*direct_children[node_id], *dependencies)))
        if any(parent_id not in nodes for parent_id in parent_node_ids):
            raise FanOutQAError(f"task {task_id} node {node_id} has an unknown dependency")
        for parent_id in parent_node_ids:
            emit(parent_id)
        question = _string(node.get("question"), f"task[{task_id}].node[{node_id}].question")
        child_context = "\n".join(
            f"- {_string(nodes[parent_id].get('question'), 'parent.question')}: "
            f"{answers[parent_id]}"
            for parent_id in parent_node_ids
        )
        evidence = node.get("evidence")
        if direct_children[node_id]:
            request_kind = "fanoutqa_local_fan_in"
            body = (
                f"Original task: {root_question}\n"
                f"Current subquestion: {question}\n"
                f"Completed child and prerequisite answers:\n{child_context}\n"
                "Synthesize the answer to the current subquestion."
            )
            agent_role = "main"
        else:
            if not isinstance(evidence, Mapping):
                raise FanOutQAError(f"leaf {node_id} in task {task_id} lacks evidence")
            revid = evidence.get("revid")
            pageid = evidence.get("pageid")
            title = evidence.get("title")
            if type(revid) is not int or type(pageid) is not int or not isinstance(title, str):
                raise FanOutQAError(
                    f"task {task_id} leaf {node_id} does not pin an evidence revision"
                )
            try:
                article = evidence_text_by_revision[revid]
            except KeyError as error:
                raise FanOutQAError(f"Wikipedia revision {revid} was not frozen") from error
            prerequisites = (
                f"Completed prerequisite answers:\n{child_context}\n" if child_context else ""
            )
            body = (
                f"Original task: {root_question}\n"
                f"Current subquestion: {question}\n"
                f"{prerequisites}Evidence title: {title}\n"
                f"Evidence revision: {revid}\n"
                f"Evidence:\n{article}\n"
                "Answer the current subquestion from this evidence."
            )
            request_kind = "fanoutqa_evidence_leaf"
            agent_role = "subagent"
        records.append(
            _record(
                task_id=task_id,
                node_id=node_id,
                workflow_line=workflow_line,
                top_level_index=len(records),
                parent_node_ids=parent_node_ids,
                body=body,
                output=answers[node_id],
                tokenizer=tokenizer,
                tokenizer_fingerprint=tokenizer_fingerprint,
                duration_model=duration_model,
                max_model_len_tokens=max_model_len_tokens,
                raw_request_type=request_kind,
                agent_role=agent_role,
            )
        )
        visiting.remove(node_id)
        emitted.add(node_id)

    for raw in top_level:
        emit(_string(raw.get("id"), "top-level.id"))
    top_ids = tuple(_string(raw.get("id"), "top-level.id") for raw in top_level)
    final_context = "\n".join(
        f"- {_string(nodes[node_id].get('question'), 'top.question')}: {answers[node_id]}"
        for node_id in top_ids
    )
    records.append(
        _record(
            task_id=task_id,
            node_id="final",
            workflow_line=workflow_line,
            top_level_index=len(records),
            parent_node_ids=top_ids,
            body=(
                f"Original task: {root_question}\n"
                f"Completed top-level research answers:\n{final_context}\n"
                "Produce the final answer to the original task."
            ),
            output=_answer_text(task.get("answer")),
            tokenizer=tokenizer,
            tokenizer_fingerprint=tokenizer_fingerprint,
            duration_model=duration_model,
            max_model_len_tokens=max_model_len_tokens,
            raw_request_type="fanoutqa_final_fan_in",
            agent_role="main",
        )
    )
    load_normalized_trace_records(records)
    roots = sum(not record["parent_span_ids"] for record in records)
    return FanOutQANormalizationResult(
        task_id=task_id,
        records=tuple(records),
        max_context_tokens=max(int(record["total_model_tokens"]) for record in records),
        max_parallel_roots=roots,
    )


def _first_unpinned_leaf(task: Mapping[str, Any]) -> str | None:
    task_id = _string(task.get("id"), "task.id")

    def walk(raw_nodes: object) -> str | None:
        if not isinstance(raw_nodes, list):
            raise FanOutQAError(f"task {task_id} decomposition must be an array")
        for raw in raw_nodes:
            if not isinstance(raw, Mapping):
                raise FanOutQAError(f"task {task_id} has a non-object decomposition node")
            children = raw.get("decomposition", [])
            if not isinstance(children, list):
                raise FanOutQAError(f"task {task_id} decomposition is malformed")
            if not children:
                evidence = raw.get("evidence")
                if not isinstance(evidence, Mapping) or any(
                    type(evidence.get(field)) is not int for field in ("pageid", "revid")
                ):
                    return _string(raw.get("id"), f"task[{task_id}].node.id")
            nested = walk(children)
            if nested is not None:
                return nested
        return None

    return walk(task.get("decomposition"))


def prepare_fanoutqa_workload(
    *,
    source_path: Path,
    license_path: Path,
    tokenizer_snapshot: Path,
    output_path: Path,
    manifest_path: Path,
    evidence_snapshot_path: Path,
    evidence_cache_dir: Path,
    source_revision: str,
    target_task_count: int = 160,
    max_model_len_tokens: int = 131_072,
    duration_model: FanOutQADurationModel | None = None,
    fetch_workers: int = 8,
) -> dict[str, Any]:
    """Freeze exactly ``target_task_count`` independent tasks and their token IDs."""

    if not source_revision or target_task_count <= 0:
        raise FanOutQAError("source revision and target task count are required")
    if duration_model is None:
        duration_model = FanOutQADurationModel()
    outputs = (output_path, manifest_path, evidence_snapshot_path)
    if any(path.exists() for path in outputs):
        raise FanOutQAError("FanOutQA output, manifest, and evidence snapshot must be absent")
    tasks = load_source_tasks(source_path)
    tokenizer, tokenizer_fingerprint = load_qwen3_tokenizer(tokenizer_snapshot)
    results: list[FanOutQANormalizationResult] = []
    rejected: dict[str, str] = {}
    evidence_by_revision: dict[int, dict[str, Any]] = {}
    evidence_text: dict[int, str] = {}
    ranked_tasks = sorted(
        enumerate(tasks, start=1),
        key=lambda item: (
            hashlib.sha256(_string(item[1].get("id"), "task.id").encode()).hexdigest(),
            _string(item[1].get("id"), "task.id"),
        ),
    )
    evaluated_task_count = 0
    for batch_start in range(0, len(ranked_tasks), 32):
        batch = ranked_tasks[batch_start : batch_start + 32]
        pinned_batch: list[tuple[int, dict[str, Any]]] = []
        for workflow_line, task in batch:
            task_id = _string(task.get("id"), "task.id")
            unpinned_leaf = _first_unpinned_leaf(task)
            if unpinned_leaf is None:
                pinned_batch.append((workflow_line, task))
            else:
                rejected[task_id] = (
                    f"task {task_id} leaf {unpinned_leaf} does not pin an evidence revision"
                )
        batch_evidence = collect_evidence([task for _, task in pinned_batch])
        for item in batch_evidence:
            revid = int(item["revid"])
            canonical = dict(item)
            previous = evidence_by_revision.setdefault(revid, canonical)
            if previous != canonical:
                raise FanOutQAError(
                    f"Wikipedia revision {revid} has conflicting identity across batches"
                )
        evidence_text.update(
            fetch_evidence_snapshot(
                batch_evidence,
                cache_dir=evidence_cache_dir,
                workers=fetch_workers,
            )
        )
        for workflow_line, task in pinned_batch:
            task_id = _string(task.get("id"), "task.id")
            try:
                results.append(
                    normalize_task(
                        task,
                        workflow_line=workflow_line,
                        tokenizer=tokenizer,
                        tokenizer_fingerprint=tokenizer_fingerprint,
                        evidence_text_by_revision=evidence_text,
                        duration_model=duration_model,
                        max_model_len_tokens=max_model_len_tokens,
                    )
                )
            except FanOutQAError as error:
                if not any(
                    marker in str(error) for marker in ("exceeds", "does not pin", "was not frozen")
                ):
                    raise
                rejected[task_id] = str(error)
        evaluated_task_count += len(batch)
        if len(results) >= target_task_count:
            break
    if len(results) < target_task_count:
        raise FanOutQAError(
            f"only {len(results)} complete tasks pass the unsegmented 128K guard; "
            "deterministic evidence segmentation is required before publication"
        )
    selected = tuple(results[:target_task_count])
    selected_ids = [item.task_id for item in selected]
    records = tuple(record for result in selected for record in result.records)
    jsonl = b"".join(_canonical_json_bytes(record) for record in records)
    artifact_sha256 = hashlib.sha256(jsonl).hexdigest()

    evidence_rows = [
        {
            **dict(item),
            "normalized_text": evidence_text[int(item["revid"])],
            "normalized_text_sha256": hashlib.sha256(
                evidence_text[int(item["revid"])].encode()
            ).hexdigest(),
        }
        for _, item in sorted(evidence_by_revision.items())
        if int(item["revid"]) in evidence_text
    ]
    unavailable_evidence_revisions = sorted(
        int(item["revid"])
        for _, item in sorted(evidence_by_revision.items())
        if int(item["revid"]) not in evidence_text
    )
    evidence_bytes = b"".join(_canonical_json_bytes(row) for row in evidence_rows)
    evidence_snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_evidence = evidence_snapshot_path.with_name(f".{evidence_snapshot_path.name}.tmp")
    with (
        temporary_evidence.open("wb") as raw_stream,
        gzip.GzipFile(fileobj=raw_stream, mode="wb", mtime=0) as stream,
    ):
        stream.write(evidence_bytes)

    bucket_counts = {bucket.name: 0 for bucket in CONTEXT_BUCKETS}
    for record in records:
        bucket_counts[bucket_name_for(int(record["total_model_tokens"]))] += 1
    workflow_span_counts = Counter(str(record["workflow_id"]) for record in records)
    source_hash = _sha256_file(source_path)
    license_hash = _sha256_file(license_path)
    manifest: dict[str, Any] = {
        "schema": "moonkvsim.aegiskv.experiment_workload_manifest.v1",
        "status": "pass",
        "evidence": {
            "class": "E2",
            "scope": "modeled/preliminary",
            "calibration": "not_calibrated",
            "physical_execution": False,
            "paper_ready": False,
        },
        "source": {
            "dataset": "FanOutQA",
            "split": "dev",
            "revision": source_revision,
            "source_sha256": source_hash,
            "license": "CC BY-SA 4.0",
            "license_sha256": license_hash,
            "source_task_count": len(tasks),
        },
        "normalizer": {
            "version": FANOUTQA_NORMALIZER_VERSION,
            "topology": "human_decomposition_and_depends_on_plus_final_fan_in",
            "prompt_source": "deterministic_evidence_provided_template",
            "tokenizer_fingerprint": tokenizer_fingerprint,
            "model_id": QWEN3_8B_MODEL_ID,
            "model_revision": QWEN3_8B_MODEL_REVISION,
            "duration_model": duration_model.to_dict(),
            "tool_delay_ns": 0,
        },
        "evidence_snapshot": {
            "path": evidence_snapshot_path.as_posix(),
            "sha256": _sha256_file(temporary_evidence),
            "revision_count": len(evidence_rows),
            "unavailable_declared_revisions": unavailable_evidence_revisions,
            "uncompressed_sha256": hashlib.sha256(evidence_bytes).hexdigest(),
            "format": "gzip_jsonl_mtime_zero",
        },
        "selection": {
            "kind": "complete_fanoutqa_tasks_after_whole_task_guard",
            "ranking": "ascending_sha256_task_id_then_task_id",
            "selected_workflow_ids": selected_ids,
            "eligible_unsegmented_task_count": len(results),
            "evaluated_ranked_prefix_task_count": evaluated_task_count,
            "unevaluated_lower_rank_task_count": len(tasks) - evaluated_task_count,
            "rejected_unsegmented_tasks": rejected,
            "no_span_slicing": True,
            "no_cross_workflow_concatenation": True,
            "no_truncation": True,
            "no_padding": True,
            "no_synthesis": True,
            "audit": {
                "task_count": len(selected),
                "record_count": len(records),
                "context_bucket_counts": bucket_counts,
                "max_model_len_tokens": max_model_len_tokens,
                "max_observed_context_tokens": max(item.max_context_tokens for item in selected),
                "workflow_span_counts": dict(sorted(workflow_span_counts.items())),
                "minimum_root_fan_out": min(item.max_parallel_roots for item in selected),
                "source_questions_human_authored": True,
                "model_requests_historically_observed": False,
            },
        },
        "artifact": {
            "path": output_path.as_posix(),
            "sha256": artifact_sha256,
            "record_count": len(records),
            "semantic_fingerprint": sha256_json(records),
        },
    }
    manifest["fingerprint"] = sha256_json(manifest)
    manifest_bytes = (
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_output = output_path.with_name(f".{output_path.name}.tmp")
    temporary_manifest = manifest_path.with_name(f".{manifest_path.name}.tmp")
    try:
        temporary_output.write_bytes(jsonl)
        temporary_manifest.write_bytes(manifest_bytes)
        os.replace(temporary_output, output_path)
        os.replace(temporary_manifest, manifest_path)
        os.replace(temporary_evidence, evidence_snapshot_path)
    except OSError as error:
        for path in (temporary_output, temporary_manifest, temporary_evidence):
            path.unlink(missing_ok=True)
        raise FanOutQAError(f"cannot publish FanOutQA workload: {error}") from error
    return manifest


def load_frozen_fanoutqa_records(
    path: Path,
    *,
    expected_workflow_ids: Sequence[str],
    tokenizer_fingerprint: str,
    retain_token_ids: bool = False,
) -> list[dict[str, Any]]:
    """Validate frozen token evidence and optionally retain exact IDs for scheduling.

    Metadata-only E2 callers keep the compact default.  Scheduler-step paper
    experiments must opt in because reconstructing IDs from hashes or source
    blocks would not be exact-token continuous batching.
    """

    if type(retain_token_ids) is not bool:
        raise TypeError("retain_token_ids must be a boolean")

    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", newline="") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                raise FanOutQAError(f"FanOutQA workload line {line_number} is blank")
            value = json.loads(line)
            if not isinstance(value, dict):
                raise FanOutQAError(f"FanOutQA workload line {line_number} is not an object")
            if value.get("token_count_mode") != "qwen3_token_ids":
                raise FanOutQAError("FanOutQA workload lost target-tokenizer token counts")
            if value.get("tokenizer_fingerprint") != tokenizer_fingerprint:
                raise FanOutQAError("FanOutQA workload tokenizer fingerprint drifted")
            content = value.get("messages_or_token_ids")
            if not isinstance(content, dict) or content.get("kind") != "token_ids":
                raise FanOutQAError("FanOutQA workload lacks frozen token IDs")
            token_ids = content.get("value")
            if not isinstance(token_ids, list) or not all(type(item) is int for item in token_ids):
                raise FanOutQAError("FanOutQA workload token IDs are malformed")
            if len(token_ids) != value.get("prompt_tokens"):
                raise FanOutQAError("FanOutQA prompt token count differs from frozen IDs")
            token_hash = sha256_json(token_ids)
            if token_hash != content.get("sha256") or token_hash != value.get(
                "prompt_token_ids_hash"
            ):
                raise FanOutQAError("FanOutQA prompt token hash drifted")
            records.append(value)
    trace = load_normalized_trace_records(records)
    actual = sorted({span.workflow_id for span in trace.spans})
    if actual != sorted(expected_workflow_ids):
        raise FanOutQAError("FanOutQA workflow IDs differ from manifest selection")
    by_workflow: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_workflow[str(record["workflow_id"])].append(record)
    for workflow_id, workflow_records in by_workflow.items():
        sinks = _sink_span_ids(workflow_records)
        if len(sinks) != 1 or not next(iter(sinks)).endswith(":final"):
            raise FanOutQAError(f"FanOutQA workflow {workflow_id} lacks one final fan-in")
    if retain_token_ids:
        return records
    compact: list[dict[str, Any]] = []
    for record in records:
        item = dict(record)
        item["messages_or_token_ids"] = None
        compact.append(item)
    return compact


def _record(
    *,
    task_id: str,
    node_id: str,
    workflow_line: int,
    top_level_index: int,
    parent_node_ids: Sequence[str],
    body: str,
    output: str,
    tokenizer: TokenizerLike,
    tokenizer_fingerprint: str,
    duration_model: FanOutQADurationModel,
    max_model_len_tokens: int,
    raw_request_type: str,
    agent_role: str,
) -> dict[str, Any]:
    system_ids = list(tokenizer.encode(SYSTEM_TEMPLATE, add_special_tokens=False).ids)
    body_ids = list(tokenizer.encode(body, add_special_tokens=False).ids)
    prompt_ids = [*system_ids, *body_ids]
    output_ids = list(tokenizer.encode(output, add_special_tokens=False).ids)
    if not output_ids:
        output_ids = list(tokenizer.encode("Unknown", add_special_tokens=False).ids)
    total = len(prompt_ids) + len(output_ids)
    if total > max_model_len_tokens:
        raise FanOutQAError(
            f"task {task_id} node {node_id} exceeds {max_model_len_tokens}: {total}"
        )
    hashes, counts, scopes = _token_blocks(prompt_ids, len(system_ids))
    duration_ns = duration_model.duration_ns(len(prompt_ids), len(output_ids))
    span_id = f"fanoutqa:{task_id}:{node_id}"
    parents = [f"fanoutqa:{task_id}:{parent_id}" for parent_id in parent_node_ids]
    parent_edges = [
        {
            "parent_span_id": parent,
            "origin": "observed",
            "confidence": 1.0,
            "inference_rule": None,
        }
        for parent in parents
    ]
    is_root = not parents
    prompt_hash = sha256_json(prompt_ids)
    return {
        "schema": "moonkvsim.multi_agent_trace.v1",
        "workflow_id": task_id,
        "session_id": task_id,
        "agent_id": "fanout-root" if agent_role == "main" else f"fanout-researcher:{node_id}",
        "agent_role": agent_role,
        "span_id": span_id,
        "parent_span_ids": parents,
        "parent_edges": parent_edges,
        "parent_edge_origin": "none" if is_root else "observed",
        "parent_edge_confidence": None if is_root else 1.0,
        "observed_submit_ns": 0,
        "observed_finish_ns": duration_ns,
        "recorded_api_time_ns": duration_ns,
        "messages_or_token_ids": {"kind": "token_ids", "sha256": prompt_hash, "value": prompt_ids},
        "prompt_token_ids_hash": prompt_hash,
        "source_hash_ids": hashes,
        "source_hash_block_token_counts": counts,
        "source_hash_block_scopes": scopes,
        "source_hash_ids_sha256": sha256_json(hashes),
        "prompt_tokens": len(prompt_ids),
        "cached_prefix_tokens": 0,
        "output_tokens": len(output_ids),
        "total_model_tokens": total,
        "tool_name": None,
        "tool_delay_ns": 0,
        "dependency_release_rule": (
            "observed_root_arrival" if is_root else "parent_completion_plus_recorded_delay"
        ),
        "retry_of_span_id": None,
        "model_id": QWEN3_8B_MODEL_ID,
        "model_revision": QWEN3_8B_MODEL_REVISION,
        "token_count_mode": "qwen3_token_ids",
        "tokenizer_fingerprint": tokenizer_fingerprint,
        "source_block_size_tokens": SOURCE_BLOCK_TOKENS,
        "source_hash_id_scope_raw": "mixed",
        "hash_id_scope": "global_system_template_and_within_workflow",
        "evidence_class": "public_human_dag_modeled_prompt_replay",
        "synthetic": False,
        "truncated": False,
        "model_length_guard_passed": True,
        "source_position": {
            "workflow_line": workflow_line,
            "top_level_index": top_level_index,
            "inner_index": None,
        },
        "raw_request_type": raw_request_type,
        "subagent_group": (
            None
            if agent_role == "main"
            else {
                "group_id": f"fanoutqa:{task_id}:researchers",
                "subagent_type": "fanoutqa_evidence_researcher",
                "status": "modeled_complete",
                "duration_ns": 0,
                "tool_use_count": 0,
            }
        ),
    }


def _token_blocks(
    token_ids: Sequence[int], system_token_count: int
) -> tuple[list[int], list[int], list[str]]:
    hashes: list[int] = []
    counts: list[int] = []
    scopes: list[str] = []
    for start in range(0, len(token_ids), SOURCE_BLOCK_TOKENS):
        block = token_ids[start : start + SOURCE_BLOCK_TOKENS]
        scope = (
            "global_system_template"
            if start + len(block) <= system_token_count
            else "within_workflow"
        )
        payload = scope.encode() + b"\0" + b"".join(struct.pack(">I", item) for item in block)
        hashes.append(int.from_bytes(hashlib.sha256(payload).digest()[:8], "big"))
        counts.append(len(block))
        scopes.append(scope)
    return hashes, counts, scopes


def _answer_text(value: object) -> str:
    if value is None:
        raise FanOutQAError("FanOutQA answer is null")
    if isinstance(value, str):
        if not value:
            raise FanOutQAError("FanOutQA answer is empty")
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _string(value: object, location: str) -> str:
    if not isinstance(value, str) or not value:
        raise FanOutQAError(f"{location} must be a non-empty string")
    return value


def _sink_span_ids(records: Sequence[Mapping[str, Any]]) -> set[str]:
    span_ids = {str(record["span_id"]) for record in records}
    parent_ids = {str(parent) for record in records for parent in record["parent_span_ids"]}
    return span_ids - parent_ids


def _canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
