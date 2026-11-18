"""Inspect downloaded public reference samples only; no upstream code or LLM calls."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent
SOURCES = ROOT / "sources"

log = (SOURCES / "MAST_2048.log").read_text()
headers = re.findall(
    r"^\[([^\]]+)\] ([^:\n]+): \*\*([^*]+<->[^*]+)\*\*", log, re.M
)
coder = json.loads((SOURCES / "NVIDIA_coder_example.trace.json").read_text())
events = coder["events"]
rows = [
    json.loads(line)
    for line in (SOURCES / "TraceLab_v002_first100.jsonl").read_text().splitlines()
]
audit = {
    "status": "REFERENCE_SAMPLES_INSPECTED",
    "scope": "Schema and source-log counts; not original-run verification, workload integration, or performance evidence",
    "MAST_2048": {
        "reply_header_count": len(headers),
        "usage_log_count": log.count("**[OpenAI_Usage_Info Receive]**"),
        "reply_roles": dict(Counter(item[1] for item in headers)),
        "limitation": "Log counts and timestamps, not service-side requests/start-end times; inter-Agent review/modification alternates",
    },
    "NVIDIA_coder_example": {
        "event_count": len(events),
        "event_types": dict(Counter(event["event_type"] for event in events)),
        "assistant_message_count": sum(
            event.get("event_type") == "message" and event.get("role") == "assistant"
            for event in events
        ),
        "conversation_ids": sorted(
            {event["conversation_id"] for event in events if "conversation_id" in event}
        ),
        "parallel_boundary_count": sum(
            event["event_type"] in ("parallel_start", "parallel_end") for event in events
        ),
        "limitation": "This released example is Coder, not the Open Deep Research trace described in the blog; compact text-free format",
    },
    "SyFI_first100": {
        "row_count": len(rows),
        "providers": dict(Counter(row["provider"] for row in rows)),
        "session_count": len({row["session_id"] for row in rows}),
        "tool_records": sum(len(row["tools"]) for row in rows),
        "top_level_keys": sorted({key for row in rows for key in row}),
        "top_level_explicit_agent_or_parent_keys": sorted(
            {key for row in rows for key in row if "agent" in key or "parent" in key}
        ),
        "limitation": "First physical rows, not random/representative sample; full release integrity and global counts not audited",
    },
    "llm_calls_executed_locally": 0,
    "sha256": {
        name: hashlib.sha256((SOURCES / name).read_bytes()).hexdigest()
        for name in (
            "MAST_2048.log",
            "NVIDIA_coder_example.trace.json",
            "TraceLab_v002_first100.jsonl",
            "agent-scaling_plancraft_run_trace.txt",
        )
    },
}
(ROOT / "SAMPLE_AUDIT.json").write_text(
    json.dumps(audit, ensure_ascii=False, indent=2) + "\n"
)
print(json.dumps({key: value for key, value in audit.items() if key != "sha256"}, ensure_ascii=False))
