"""Audit current algorithm bindings, matched data, plotted values and final exports."""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path

import numpy as np
import audit_paper_story as media
from paper_paths import ROOT
from three_system_data import SYSTEMS, load_case, sha
from three_system_review_notes import controller_service

ART = ROOT / "output/agent-lease-20260908"
OUT = ROOT / "output/pdf/aegiskv-agent-lease-20260908"
DIRECTORY = ROOT / "benchmark/AegisKV/experiments"
RENDER = ROOT / "tmp/pdfs/agent-lease-review"


def read(path): return json.loads(path.read_text())


def csv_rows(name):
    with (OUT/(name+".csv")).open() as f: return list(csv.DictReader(f))


@lru_cache(maxsize=2)
def data(case, system): return read(ART/f"data/{case}/{system}.json")


def audit_runs():
    snapshot = ART/"source-v3/MECHANISM_SOURCE_SNAPSHOT.json"
    snap = read(snapshot)
    for name, digest in snap["files"].items(): assert sha(snapshot.parent/name) == digest, name
    authority = read(ART/"ALGORITHM_AUTHORITY.json")
    for name, digest in authority["files"].items():
        assert snap["files"][name] == digest and sha(ROOT/name) == digest
    results = {}; plans = {}
    for campaign, expected_count in [("campaign-v3", 47), ("contention-campaign", 4)]:
        croot = ART/campaign; protocol = read(croot/"PROTOCOL.json"); state = read(croot/"STATUS.json")
        jobs = {(c,s) for c, cfg in protocol["cases"].items() for s in cfg.get("systems", SYSTEMS)}
        assert len(jobs) == expected_count and set(map(tuple, state["completed"])) == jobs
        assert not any(state[k] for k in ["failed", "active", "pending"])
        for case, system in sorted(jobs):
            d = data(case, system); m = d["manifest"]
            raw = croot/f"runs/{case}/{system}.json.gz"
            assert m == read(raw.with_name(system+".manifest.json"))
            assert m["raw_sha256"] == sha(raw)
            assert m["source_snapshot_sha256"] == sha(snapshot)
            assert m["cpu_calibration_sha256"] == sha(ART/"CPU_QUOTES.json")
            assert d["extractor_sha256"] == sha(Path(__file__).with_name("three_system_data.py"))
            assert d["audit"]["status"] == m["status"] == "PASS"
            assert all(v is True for k,v in d["audit"].items() if k != "status")
            assert len(d["workflows"]) == 160 and len(d["requests"]) == 2608
            assert m["workload"]["input_sha256"] == snap["files"]["benchmark/AegisKV/experiments/workloads/fanoutqa-dev-qwen3-8b-160.jsonl"]
            assert m["algorithm_contract"]["algorithm2"] == "single_chunk_agent_subleases_tail_only_rent_joint_DAG_WCT"
            assert m["configuration"]["source_version"] == "agent-subleases-tail-rent-guarded-aimd-20260908"
            assert m["configuration"]["window_ns"] == 50_000_000
            cfg = protocol["cases"][case]
            assert m["configuration"]["strict_free_gain"] == cfg.get("strict-free-gain", False)
            assert m["configuration"]["static_peer"] == cfg.get("static-peer", False)
            assert m["configuration"]["eager_refresh"] == cfg.get("eager-refresh", False)
            assert m["configuration"]["slack_enabled"] != cfg.get("no-slack", False)
            assert m["configuration"]["dma_slowdown"] == cfg.get("dma-slowdown", 0)
            if system != "mooncake": assert d["agent_lease_events"]
            if system == "aegis": assert d["foreground_budget"]
            if "reference" in cfg:
                ref = data(cfg["reference"], "mooncake")["manifest"]
                assert m["failure_reference_sha256"] == ref["raw_sha256"]
                plan = m["failure_schedule"]["events"][0]
                assert plan["focus_span_id"].endswith(":revisit-0")
                if case in plans: assert plans[case] == plan
                plans[case] = plan
            else: assert m["failure_schedule"] is None
            results[case+"/"+system] = dict(raw_sha256=m["raw_sha256"], data_sha256=sha(ART/f"data/{case}/{system}.json"), audit=d["audit"])
        for case, cfg in protocol["cases"].items():
            if len(cfg.get("systems", SYSTEMS)) == 3: load_case(ART/"data"/case)
    reconstructed = reconstruct_focus(plans)
    return dict(executions=len(results), source_files=len(snap["files"]), results=results,
        source_sha256=sha(snapshot), selected_faults=reconstructed,
        note="Successful retained executions only. Quota-interrupted attempts are archived and excluded; reused raw hashes are not new replicates.")


def reconstruct_focus(plans):
    """Reconstruct first-round 60% crossings independently from baseline traces."""
    original = [json.loads(line) for line in (ART/"source-v3/benchmark/AegisKV/experiments/workloads/fanoutqa-dev-qwen3-8b-160.jsonl").read_text().splitlines() if line.strip()]
    eligible = {r["span_id"]+":revisit-0": r["prompt_tokens"] for r in original if r["prompt_tokens"] >= 16384}
    outputs = []
    for case, targets in [("f0-base", [("f1-q25",250),("f1-q50",500),("f1-q75",750),("f1-no-dag",500)]),
        ("f0-seed1",[("f1-seed1",500)]),("f0-seed2",[("f1-seed2",500)])]:
        with gzip.open(ART/f"campaign-v3/runs/{case}/mooncake.json.gz", "rt") as f: raw = json.load(f)
        ends = {r["workflow_id"]: 0 for r in raw["span_details"]}
        for r in raw["span_details"]: ends[r["workflow_id"]] = max(ends[r["workflow_id"]],r["completed_ns"])
        crossings = {}
        for step in raw["representative"]["continuous_batch_scheduler"]["steps"]:
            for p in step["participants"]:
                rid = p["request_id"]
                if rid not in eligible or rid in crossings: continue
                threshold = eligible[rid]*600//1000
                before, after = p["num_computed_tokens_before"],p["num_computed_tokens_after"]
                if before <= threshold < after:
                    crossings[rid] = step["start_ns"]+(step["planned_end_ns"]-step["start_ns"])*(threshold-before)//(after-before)
        counts = {rid:sum(t < at for t in ends.values()) for rid,at in crossings.items()}
        for failed, progress in targets:
            chosen = min(crossings, key=lambda rid:(abs(counts[rid]*1000-progress*160),crossings[rid],rid))
            plan = plans[failed]
            assert plan["focus_span_id"] == chosen and plan["reference_at_ns"] == crossings[chosen]
            assert plan["workload_position"]["reference_completed_workflow_count"] == counts[chosen]
            outputs.append(dict(case=failed,focus_span_id=chosen,completed=counts[chosen],reference_at_ns=crossings[chosen]))
        del raw
    return outputs


def audit_values():
    base = load_case(ART/"data/f0-base")
    ids = [r["workflow_id"] for r in csv_rows("workflow-order")]
    assert ids == [r["workflow_id"] for r in sorted(base["mooncake"]["workflows"],key=lambda r:(r["wct_s"],r["workflow_id"]))]
    service = controller_service(base)
    specs = {"wct":("wct_s",False),"wct-difference":("wct_s",True),"dram-hit":("dram_hit_pct",False),
        "scheduler-queue":("mean_scheduler_queue_s",False),"hbm-wait":("mean_foreground_hbm_wait_s",False),
        "controller-service-difference":(None,True),"background-copy":("background_copy_gib",False),"peer-copy":("peer_copy_gib",False)}
    for name,(key,difference) in specs.items():
        rows = csv_rows("f0-revisit-"+name); assert [r["workflow_id"] for r in rows] == ids
        v = {s:{r["workflow_id"]:r[key] if key else service[s][i] for i,r in enumerate(base[s]["workflows"])} for s in SYSTEMS}
        for r in rows:
            for s in SYSTEMS: assert np.isclose(float(r[s]), v[s][r["workflow_id"]]-(v["mooncake"][r["workflow_id"]] if difference else 0),rtol=0,atol=1e-9)
    counts = {}
    for s in SYSTEMS:
        rows = [r for r in csv_rows("f0-revisit-tpot-tail") if r["system"] == s]
        values = np.array([r["request_tpot_ns"]/1e6 for r in base[s]["requests"] if r["request_tpot_ns"] is not None])
        assert sum(int(r["count"]) for r in rows) == len(values)
        for r in rows: assert np.isclose(float(r["survival_ge"]),np.mean(values >= float(r["tpot_ms"])))
        counts[s] = len(values)
    for q in (25,50,75):
        plotted = csv_rows(f"f1-q{q}-workflow-penalty"); assert [r["workflow_id"] for r in plotted] == ids
        for s in SYSTEMS:
            current = data(f"f1-q{q}",s)
            a = {r["workflow_id"]:r["wct_s"] for r in base[s]["workflows"]}
            b = {r["workflow_id"]:r["wct_s"] for r in current["workflows"]}
            differences = [b[w]-a[w] for w in ids]
            assert np.allclose([float(r[s]) for r in plotted],differences,rtol=0,atol=1e-9)
            summary = next(r for r in csv_rows("failure-summary") if int(r["progress_pct"])==q and r["system"]==s)
            assert np.isclose(float(summary["p95_penalty_s"]),np.percentile(differences,95))
            assert np.isclose(float(summary["mean_penalty_s"]),np.mean(differences))
            phase = next(r for r in csv_rows("failure-focal-recovery-phases") if int(r["progress_pct"])==q and r["system"]==s)
            focus = current["manifest"]["failure_schedule"]["events"][0]["focus_span_id"]
            failed = next(r for r in current["failures"] if r["span_id"]==focus)
            ready = next(r["timestamp_ns"] for r in current["recovery_events"] if r["span_id"]==focus and r["event"]=="CONTINUOUS_RECOVERY_PREFIX_MATERIALIZED")
            assert phase["focus_span_id"]==focus
            for key,value in {"materialize_s":(ready-failed["failure_at_ns"])/1e9,
                "suffix_and_resume_s":(failed["resume_decode_start_ns"]-ready)/1e9,
                "restored_peer_tokens":failed["restored_peer_tokens"],"restored_store_tokens":failed["restored_store_tokens"],
                "recompute_tokens":failed["recompute_tokens"]}.items():assert np.isclose(float(phase[key]),value)
    failed_means={s:np.mean([data(f"f1-q{q}",s)["summary"]["mean_wct_s"] for q in [25,50,75]]) for s in SYSTEMS}
    for r in csv_rows("benefit-cost-fault-mixture"):
        system=r["system"];healthy=base[system]["summary"]["mean_wct_s"]
        failed=failed_means[system]
        probability=float(r["fault_probability"])
        assert np.isclose(float(r["expected_mean_wct_s"]),(1-probability)*healthy+probability*failed)
    lazy,eager = base["dram"], data("f0-eager","dram")
    strip = lambda r:(r["span_id"],r["pool_id"],r["chunk_key"],r["status"],r["victims"])
    assert [strip(r) for r in lazy["agent_lease_events"]] == [strip(r) for r in eager["agent_lease_events"]]
    return dict(workflow_curves=8,paired_workflows=len(ids),tpot_sample_counts=counts,
        failure_curves=3,lazy_eager_decisions_identical=True)


def audit_native():
    folder = ART/"native-l40s"; m=read(folder/"manifest.json")
    assert m["status"] == "PASS" and m["direct_peer_supported"]
    assert sha(folder/"samples.jsonl") == m["samples_sha256"]
    rows = [json.loads(x) for x in (folder/"samples.jsonl").read_text().splitlines()]
    assert len(rows) == m["sample_count"] == 360 and all(r["status"] == "PASS" for r in rows)
    cells = Counter((r["batch"],r["prompt_tokens"],r["backup_occupancy_gib"],r["mode"]) for r in rows)
    assert len(cells) == 72 and set(cells.values()) == {5}
    by = {(r["repeat"],r["batch"],r["prompt_tokens"],r["backup_occupancy_gib"],r["mode"]):r for r in rows}
    for batch in [1,4]:
        for r in csv_rows(f"native-forward-b{batch}"):
            repeat,tokens,mode = int(r["repeat"]),int(r["prompt_tokens"]),r["mode"]
            expected = by[repeat,batch,tokens,8,mode]["forward_gpu_ms"]/by[repeat,batch,tokens,8,"none"]["forward_gpu_ms"]
            assert np.isclose(float(r["slowdown"]),expected,rtol=0,atol=1e-12)
    release = read(folder/"reclaim.json"); assert Counter(r["gib"] for r in release) == {1:20,4:20,8:20}
    for r in csv_rows("native-copy-cpu"):
        source=by[int(r["repeat"]),1,int(r["prompt_tokens"]),8,r["mode"]]
        assert np.isclose(float(r["cpu_cores"]),source["process_cpu_ns"]/source["forward_wall_ns"],rtol=0,atol=1e-12)
    return dict(samples=360,conditions=72,within_allocation_blocks=5,independent_allocations=1,release_trials=60,job_id=m["job_id"],manifest_sha256=sha(folder/"manifest.json"))


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--prepare-visuals",action="store_true");args=parser.parse_args()
    selection=read(ART/"paper-selection.json");assert len(selection["figures"]) == 51
    for source,digest in selection["manifest_bindings"].items():
        assert sha(ROOT/source) == digest
        for p,h in read(ROOT/source).get("input_bindings",{}).items():assert sha(ROOT/p) == h,p
    media.OUT=OUT;media.ART=ART;media.RENDER=RENDER
    figures=media.audit_media(selection,args.prepare_visuals)
    if args.prepare_visuals:
        print(json.dumps(dict(status="RENDERED_FOR_REVIEW",figures=len(figures))));return
    runs=audit_runs();values=audit_values();native=audit_native()
    visual=read(ART/"VISUAL_REVIEW.json"); assert visual["status"] == "REVIEWED" and set(visual["figures"]) == set(figures)
    for name,r in figures.items():
        assert visual["figures"][name]["pdf_sha256"] == r["pdf_sha256"]
        assert visual["figures"][name]["render_sha256"] == sha(RENDER/(name+".png"))
    assert visual["placement_pdf_sha256"] == sha(OUT/"paper-placement.pdf")
    layout=read(ART/"MARKDOWN_LAYOUT.json");assert layout["status"] == "RENDERED" and layout["images"] == 38 and layout["loaded"]
    assert layout["source_sha256"] == sha(DIRECTORY/"Paper_Figures.md")
    assert layout["html_sha256"] == sha(OUT/"paper-story.html")
    assert layout["overflow"]["document"] <= layout["overflow"]["viewport"]
    for pair in layout["pairedRows"]:assert len(pair)==2 and abs(pair[0]["y"]-pair[1]["y"])<=2
    documents=[DIRECTORY/n for n in ["Paper_Figures.md","PAPER_FIGURE_REVIEW.md","FIGURES.md","Old_Figures.md","AGENT_LEASE_PROTOCOL.md","AGENT_LEASE_IMPLEMENTATION.md"]]
    assert re.findall(r"^## (.+)$",documents[0].read_text(),re.M) == ["Motivation","System Design","Evaluation"]
    links=0
    for doc in documents:
        for target in re.findall(r"\]\(([^)]+)\)",doc.read_text())+re.findall(r'<img src="([^"]+)"',doc.read_text()):
            if target.startswith(("http:","https:","mailto:","#")):continue
            path=(doc.parent/target.split("#",1)[0]).resolve()
            assert path.exists() or path == ART/"DELIVERY_AUDIT.json",(doc,target)
            if "#paper-" in target:assert '<a id="'+target.split("#",1)[1]+'"' in path.read_text()
            links+=1
    old=read(ROOT/"output/paper-story-20260908/DELIVERY_AUDIT.json")
    for name,r in old["figures_by_name"].items():
        assert sha(ROOT/f"output/pdf/aegiskv-paper-story-20260908/{name}.pdf") == r["pdf_sha256"]
    result=dict(status="PASS",scope="Algorithm/source/data/export integrity and actual-layout review; not proof of native end-to-end benefits",figures=51,primary_figures=38,supplements=13,
        design_figures=6,paired_rows=len(layout["pairedRows"]),runs=runs,plotted_values=values,native=native,figures_by_name=figures,
        local_links_checked=links,old_33_pdf_exports_unchanged=True,selection_sha256=sha(ART/"paper-selection.json"),
        visual_review_sha256=sha(ART/"VISUAL_REVIEW.json"),documents={str(p.relative_to(ROOT)):sha(p) for p in documents})
    archive=read(ART/"EVIDENCE_ARCHIVE.json")
    assert archive["status"]=="PASS" and archive["raw_gzip_files"]==51
    assert sha(ART/"evidence.tar.zst")==archive["archive_sha256"]
    for key,r in runs["results"].items():
        case,system=key.split("/");campaign="contention-campaign" if case.startswith("f0-dma30") else "campaign-v3"
        assert archive["members"][f"{campaign}/runs/{case}/{system}.json.gz"]["sha256"]==r["raw_sha256"]
        assert archive["members"][f"data/{case}/{system}.json"]["sha256"]==r["data_sha256"]
    result["durable_evidence_archive"]={"manifest_sha256":sha(ART/"EVIDENCE_ARCHIVE.json"),"archive_sha256":archive["archive_sha256"],"verified_members":archive["verified_members"]}
    (ART/"DELIVERY_AUDIT.json").write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps({k:result[k] for k in ["status","figures","primary_figures","supplements","design_figures","paired_rows","local_links_checked"]}))


if __name__ == "__main__":main()
