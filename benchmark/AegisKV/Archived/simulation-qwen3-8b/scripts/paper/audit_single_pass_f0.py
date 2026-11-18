"""Independently check the original-DAG F0 figures against published records."""
from __future__ import annotations

from collections import Counter, defaultdict
import csv
import gzip
import json
from pathlib import Path
import re

import pymupdf
from PIL import Image

from reduce_single_pass_f0 import ROOT, WORKLOAD, sha
from render_single_pass_f0 import ART, OUT, SYSTEMS


def main():
    manifest_path=OUT/"single-pass-manifest.json"
    manifest=json.loads(manifest_path.read_text())
    archive=json.loads((ART/"RAW_ARCHIVE.json").read_text())
    for r in archive["files"]:
        assert sha(ROOT/r["archive"])==r["sha256"]
    with WORKLOAD.open() as stream:
        records={r["span_id"]:r for r in map(json.loads,stream)}
    assert len(records)==1304 and all(":revisit-" not in k for k in records)
    assert sum(r["prompt_tokens"] for r in records.values())==26760371
    source=ROOT/"output/agent-lease-20260908/source-v3"
    snapshot=json.loads((source/"MECHANISM_SOURCE_SNAPSHOT.json").read_text())
    assert sha(source/"MECHANISM_SOURCE_SNAPSHOT.json")==manifest["source_snapshot_sha256"]
    for p,h in snapshot["files"].items():
        assert sha(source/p)==h,p
    assert sha(source/"benchmark/AegisKV/experiments/workloads/fanoutqa-dev-qwen3-8b-160.jsonl")==sha(WORKLOAD)
    oracle,diagnoses={},{}
    for s in SYSTEMS:
        raw_summary=json.loads((ART/"raw"/f"{s}.summary.json").read_text())
        pub=json.loads((ART/"raw"/f"{s}.manifest.json").read_text())
        assert pub["status"]=="PASS" and pub["failure_schedule"] is None
        assert raw_summary["rounds"]==1 and not raw_summary["failure_events"]
        assert set(r["span_id"] for r in raw_summary["requests"])==set(records)
        assert all(r["failure_at_ns"] is None for r in raw_summary["requests"])
        for path,h in manifest["inputs"].items():
            if s+".diagnosis" in path:
                assert sha(ROOT/path)==h
        with gzip.open(ART/"data"/f"{s}.diagnosis.json.gz","rt") as stream:
            d=json.load(stream)
        diagnoses[s]=d
        assert d["summary"]["preemptions"]==0
        by_workflow=defaultdict(list)
        for r in raw_summary["requests"]:
            by_workflow[r["workflow_id"]].append(r)
        oracle[s]={}
        request_steps=d["steps"]
        for wid,rr in by_workflow.items():
            values={"wct_s":(max(r["completed_ns"] for r in rr)-min(r["released_ns"] for r in rr))/1e9,
                    "requests":len(rr),"prompt_tokens":sum(records[r["span_id"]]["prompt_tokens"] for r in rr),
                    "local_hit_tokens":sum(r["reused_primary_tokens"] for r in rr),
                    "dram_hit_tokens":sum(r["reused_store_tokens"] for r in rr),
                    "peer_hit_tokens":sum(r["reused_peer_tokens"] for r in rr)}
            values["total_hit_tokens"]=sum(values[k] for k in ["local_hit_tokens","dram_hit_tokens","peer_hit_tokens"])
            values["prefill_executed_tokens"]=sum(max(0,min(records[r["span_id"]]["prompt_tokens"],st["after"])-min(records[r["span_id"]]["prompt_tokens"],st["before"]))
                for r in rr for st in request_steps[r["span_id"]])
            # In these F0 logs no preemption occurred. A second accounting path
            # from input lengths and served cache must match executed work.
            assert values["prefill_executed_tokens"]==values["prompt_tokens"]-values["total_hit_tokens"]
            oracle[s][wid]=values
        assert len(oracle[s])==160
    with (OUT/"all-workflows-paired.csv").open() as stream:
        rows=list(csv.DictReader(stream))
    assert len(rows)==480 and len({(r["system"],r["workflow_id"]) for r in rows})==480
    order=sorted(oracle["mooncake"],key=lambda k:(oracle["mooncake"][k]["wct_s"],k))
    for r in rows:
        s,w=r["system"],r["workflow_id"]
        assert order[int(r["workflow_rank"])-1]==w
        for k,v in oracle[s][w].items():
            assert abs(float(r[k])-v)<1e-9,(s,w,k)
        expected_delta=oracle[s][w]["wct_s"]-oracle["mooncake"][w]["wct_s"]
        assert abs(float(r["delta_wct_s"])-expected_delta)<1e-9
        assert abs(float(r["total_hit_pct"])-100*oracle[s][w]["total_hit_tokens"]/oracle[s][w]["prompt_tokens"])<1e-12
        assert int(r["dram_hit_tokens"])==int(r["peer_hit_tokens"])==0
    costs=manifest["focus_costs"]
    assert len({r["total_hit_tokens"] for r in costs})==1
    assert len({r["prefill_executed_tokens"] for r in costs})==1
    for r in costs:
        assert abs((r["critical_gpu_step_ns"]+r["critical_queue_other_ns"]+r["other_stages_ns"])/1e9-r["wct_s"])<1e-10
    batch=json.loads((ART/"final-request-batch-evidence.json").read_text())
    assert sha(ART/"final-request-batch-evidence.json")==manifest["final_request_evidence_sha256"]
    for s,d in batch.items():
        r=d["request"]
        assert r["prompt_tokens"]==250 and r["output_tokens"]==47
        assert r["prefill_executed_tokens"]==186 and r["total_hit_tokens"]==64
        assert d["step_count"]==47
        assert sum(p["prefill_tokens"] for p in d["co_batched_prefill_steps"])==d["co_batched_prefill_tokens"]
    assert batch["mooncake"]["co_batched_prefill_tokens"]==1291
    assert batch["aegis"]["co_batched_prefill_tokens"]==192182
    visuals=json.loads((ART/"VISUAL_REVIEW.json").read_text())
    assert visuals["status"]=="PASS" and visuals["placement_width_mm"]==177.8
    for r in manifest["figures"]:
        assert r["run_scope"]=="original_single_pass_F0"
        for ext,h in r["files"].items():assert sha(OUT/f'{r["name"]}.{ext}')==h
        assert visuals["pdf_hashes"][r["name"]]==r["files"]["pdf"]
        assert visuals["png_hashes"][r["name"]]==r["files"]["png"]
        with Image.open(OUT/f'{r["name"]}.png') as img:img.verify()
        with pymupdf.open(OUT/f'{r["name"]}.pdf') as doc:
            assert len(doc)==1 and abs(doc[0].rect.width-504)<.01
    doc_path=ROOT/"benchmark/AegisKV/experiments/Paper_Draft.md"
    text=doc_path.read_text()
    section=text.split("<!-- SINGLE_PASS_F0_START -->")[1].split("<!-- SINGLE_PASS_F0_END -->")[0]
    assert ":revisit-" not in section and "104.929" not in section and "94.257" not in section
    assert "1,304" in section and "各完整执行一次" in section
    for r in manifest["figures"]:
        assert str((OUT/(r["name"]+".png")).relative_to(ROOT)) in text
    for p in re.findall(r'<img src="([^"]+)"',text):assert (doc_path.parent/p).resolve().exists(),p
    result=dict(status="PASS",scope="three original-DAG F0 figures, paired tables and normal-service manuscript section",
                complete_runs=3,runs_per_system=1,workflows_per_run=160,requests_per_run=1304,
                new_simulations_in_this_task=0,reused_thread="01a0838b-2f2a-7771-bba9-4857d840b9ba",
                source_files_verified=len(snapshot["files"]),paired_workflow_rows=480,
                plotted_requests_checked=3912,normal_preemptions=0,
                cache_denominator="all original prompt tokens, including cold requests",
                raw_archive_files_verified=len(archive["files"]),raw_storage=archive["storage"],
                paper_sha256=sha(doc_path),figure_manifest_sha256=sha(manifest_path),
                visual_review_sha256=sha(ART/"VISUAL_REVIEW.json"),
                evidence="uncalibrated frozen-source DES, not native model execution or a performance-significance claim")
    (ART/"AUDIT.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps(result,ensure_ascii=False))


if __name__=="__main__":main()
