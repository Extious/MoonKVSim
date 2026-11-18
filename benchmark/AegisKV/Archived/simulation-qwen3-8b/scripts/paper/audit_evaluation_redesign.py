"""Verify Evaluation data transformations, original preservation and final exports."""
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path

import numpy as np
import pymupdf

from paper_paths import ROOT
from render_evaluation_redesign import ART,OUT,OLD,DATA,sha,SYSTEMS

DIR=ROOT/"benchmark/AegisKV/experiments"
RENDER=ROOT/"tmp/pdfs/evaluation-redesign"


def read(path):return json.loads(path.read_text())


def rows(path):
    with path.open() as f:return list(csv.DictReader(f))


def close(a,b):
    assert np.isclose(float(a),float(b),rtol=1e-11,atol=1e-8),(a,b)


def verify_values():
    data={s:read(DATA/f"f0-base/{s}.json") for s in SYSTEMS}
    wf={s:{r["workflow_id"]:r for r in d["workflows"]} for s,d in data.items()}
    a=rows(OUT/"eval-healthy-workflow.csv")
    b=rows(OUT/"eval-healthy-reuse.csv")
    assert len(a)==len(b)==480
    assert len({r["workflow_id"] for r in a})==160
    for r in a:
        v=wf[r["system"]][r["workflow_id"]]["wct_s"]
        base=wf["mooncake"][r["workflow_id"]]["wct_s"]
        close(r["wct_s"],v);close(r["mooncake_wct_s"],base)
        close(r["overhead_pct"],100*(v/base-1))
    for r in b:
        v=wf[r["system"]][r["workflow_id"]]["dram_hit_pct"]
        base=wf["mooncake"][r["workflow_id"]]["dram_hit_pct"]
        close(r["change_pp"],v-base)
    resource=rows(OUT/"eval-healthy-resources.csv")
    assert len(resource)==21
    for r in resource:
        close(r["ratio"],float(r["value"])/float(r["mooncake_value"]))
        field={"Foreground HBM wait":"foreground_hbm_wait_s","Scheduler queue P95":"p95_scheduler_queue_s"}.get(r["metric"])
        if field:close(r["value"],data[r["system"]]["summary"][field])
        else:
            old=next(x for x in rows(OLD/"evaluation-resource-cost.csv") if x["system"]==r["system"] and x["metric"]==r["metric"])
            close(r["value"],old["value"]);close(r["mooncake_value"],old["mooncake_value"])
    focal=rows(ART/"legacy-focal-workflows.csv")
    assert len(focal)==9
    for r in focal:
        d=read(DATA/f'f1-q{r["legacy_progress_pct"]}/{r["system"]}.json')
        v=next(x["wct_s"] for x in d["workflows"] if x["workflow_id"]==r["workflow_id"])
        close(v,r["f1_wct_s"])
        close(r["f0_wct_s"],wf[r["system"]][r["workflow_id"]]["wct_s"])
        close(r["delta_wct_s"],v-float(r["f0_wct_s"]))
        close(r["delta_common_pct"],100*float(r["delta_wct_s"])/float(r["mooncake_f0_wct_s"]))
        baseline=next(x for x in focal if x["case_id"]==r["case_id"] and x["system"]=="mooncake")
        close(r["f1_ratio"],v/float(baseline["f1_wct_s"]))
    assert rows(OUT/"eval-failure-wct.csv")==focal==rows(OUT/"eval-failure-increment.csv")
    phases=rows(OUT/"eval-failure-recovery.csv")
    tokens=rows(OUT/"eval-failure-kv.csv")
    original=rows(OLD/"failure-focal-recovery-phases.csv")
    for r in phases:
        q={"C1":"25","C2":"50","C3":"75"}[r["case_id"]]
        p=next(p for p in original if p["progress_pct"]==q and p["system"]==r["system"])
        for field in ["materialize_s","suffix_and_resume_s","resume_s"]:close(r[field],p[field])
        close(float(r["materialize_s"])+float(r["suffix_and_resume_s"]),r["resume_s"])
    for r in tokens:
        q={"C1":"25","C2":"50","C3":"75"}[r["case_id"]]
        p=next(p for p in original if p["progress_pct"]==q and p["system"]==r["system"])
        close(r["tokens"],p[r["source"]])
    assert all(int(r["tokens"])==0 for r in tokens if r["source"]=="restored_peer_tokens")
    contracts=read(ART/"legacy-failure-contracts.json")
    assert len(contracts)==9 and all(c["impact_scope"]=="OBSERVED_ONLY" for c in contracts)
    mismatch={}
    for case in ["C1","C2","C3"]:
        c=[c for c in contracts if c["case_id"]==case]
        mismatch[case]=dict(same_active_sets=len({tuple(sorted(x["active_spans"])) for x in c})==1,
            same_queued_sets=len({tuple(sorted(x["queued_spans"])) for x in c})==1,
            same_target_gpu=len({x["target_gpu_id"] for x in c})==1)
    return dict(workflows=160,healthy_points=480,resource_points=21,focal_pairs=9,
        recovery_stages=9,recovery_source_counts=27,legacy_actual_set_comparison=mismatch,
        aegis_mean_wct_change_pct=100*(data["aegis"]["summary"]["mean_wct_s"]/data["mooncake"]["summary"]["mean_wct_s"]-1))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--prepare-visuals",action="store_true")
    args=p.parse_args()
    selection=read(ART/"paper-selection.json");manifest=read(OUT/"manifest.json")
    assert Counter(r["section"] for r in selection["figures"])=={"Motivation":3,"System Design":1,"Evaluation":7}
    assert manifest["new_experiments"]==selection["new_experiments"]==0
    for path,digest in manifest["inputs"].items():assert sha(ROOT/path)==digest,path
    assert sha(OUT/"manifest.json")==selection["source_manifest_sha256"]
    assert sha(Path(__file__).with_name("render_evaluation_redesign.py"))==manifest["script_sha256"]
    assert sha(Path(__file__).with_name("build_evaluation_redesign.py"))==selection["generator_sha256"]
    assert sha(Path(__file__).with_name("templates")/"evaluation-draft.md")==selection["template_sha256"]
    old=read(ROOT/"output/agent-lease-20260908/paper-selection.json")
    for r in old["figures"]:
        for ext,digest in r["files"].items():assert sha(OLD/f'{r["name"]}.{ext}')==digest,(r["name"],ext)
    for path,digest in read(ART/"before-redesign/REVISION_BASE.json")["files"].items():
        assert sha(ART/"before-redesign"/path)==digest
    for ref in read(ART/"reference-review.json"):assert sha(ROOT/ref["pdf"])==ref["sha256"]
    numerical=verify_values()
    protocol=read(DIR/"evaluation-design/protocol.json")
    assert protocol["status"]=="DRAFT_NOT_EXECUTED"
    for path in (DIR/"evaluation-design/data").glob("*.csv"):assert len(rows(path))==0,path
    primary_names={r["name"] for r in selection["figures"]}
    assert not any(r["name"] in primary_names for r in selection["layout_only"])
    all_figures=selection["figures"]+selection["layout_only"]
    metadata={}
    RENDER.mkdir(parents=True,exist_ok=True)
    for r in all_figures:
        for ext,digest in r["files"].items():assert sha(OUT/f'{r["name"]}.{ext}')==digest
        path=OUT/f'{r["name"]}.pdf';doc=pymupdf.open(path);assert len(doc)==1
        page=doc[0];close(page.rect.width/72,r["width_in"])
        spans=[s for b in page.get_text("dict")["blocks"] if "lines" in b for l in b["lines"] for s in l["spans"] if s["text"].strip()]
        outside=[s["text"] for s in spans if s["bbox"][0]<-1 or s["bbox"][1]<-1 or s["bbox"][2]>page.rect.width+1 or s["bbox"][3]>page.rect.height+1]
        assert not outside,(r["name"],outside)
        if not r.get("inherited"):assert min(s["size"] for s in spans)>=9.9
        if r["evidence"]=="layout_only_no_data":assert "No measurements" in page.get_text()
        if args.prepare_visuals:page.get_pixmap(matrix=pymupdf.Matrix(2,2)).save(RENDER/f'{r["name"]}.png')
        metadata[r["name"]]=dict(pdf_sha256=sha(path),width_in=page.rect.width/72,
            minimum_pdf_font_pt=min(s["size"] for s in spans),text_inside_page=True)
    (ART/"PDF_METADATA.json").write_text(json.dumps(metadata,indent=2)+"\n")
    if args.prepare_visuals:
        proof=pymupdf.open(OUT/"paper-placement.pdf")
        for i,page in enumerate(proof):
            page.get_pixmap(matrix=pymupdf.Matrix(1.5,1.5)).save(RENDER/f"placement-{i+1:02}.png")
        print(json.dumps({"status":"PREPARED_FOR_ACTUAL_VIEW","figures":len(all_figures),"proof_pages":len(proof),"values":numerical}))
        return
    layout=read(ART/"MARKDOWN_LAYOUT.json");visual=read(ART/"VISUAL_REVIEW.json")
    assert layout["source_sha256"]==sha(DIR/"Paper_Draft.md")
    assert layout["html_sha256"]==sha(OUT/"paper-story.html")
    assert layout["images"]==11 and layout["loaded"] and layout["overflow"]["document"]<=layout["overflow"]["viewport"]
    design_layout=read(ART/"DESIGN_LAYOUT.json")
    assert design_layout["source_sha256"]==sha(DIR/"EVALUATION_DESIGN.md")
    assert design_layout["images"]==4 and design_layout["loaded"]
    assert design_layout["overflow"]["document"]<=design_layout["overflow"]["viewport"]
    assert visual["selection_sha256"]==sha(ART/"paper-selection.json")
    assert visual["placement_sha256"]==sha(OUT/"paper-placement.pdf")
    assert visual["reviewed_pdf_figures"]==sorted(metadata)
    assert visual["pdf_hashes"]=={k:v["pdf_sha256"] for k,v in metadata.items()}
    assert visual["status"]=="REVIEWED"
    assert re.findall(r"^## (.+)$",(DIR/"Paper_Draft.md").read_text(),re.M)==["Motivation","System Design","Evaluation"]
    docs=[DIR/n for n in ["Paper_Draft.md","EVALUATION_DESIGN.md","PAPER_FIGURE_REVIEW.md","FIGURES.md","Old_Figures.md","Paper_Draft_BeforeEvaluation_20260909.md"]]
    links=0
    for doc in docs:
        for target in re.findall(r"\]\(([^)]+)\)",doc.read_text())+re.findall(r'<img src="([^"]+)"',doc.read_text()):
            if target.startswith(("https:","http:","#","mailto:")):continue
            dest=(doc.parent/target.split("#",1)[0]).resolve()
            assert dest.exists() or dest==ART/"DELIVERY_AUDIT.json",(doc,target)
            links+=1
    result=dict(status="PASS",scope="Design, historical value transformations, preservation and actual-size figure review only",
        paper_figures=11,evaluation_figures=7,empty_layout_figures=4,new_experiments=0,
        new_protocol_results_available=False,algorithm2_implementation="DEFERRED_BY_USER",
        draft_protocol_sha256=sha(DIR/"evaluation-design/protocol.json"),
        empty_input_schemas={p.name:sha(p) for p in (DIR/"evaluation-design/data").glob("*.csv")},
        source_v3_original_figure_sets_unchanged=len(old["figures"]),values=numerical,
        source_inputs_sha256=manifest["inputs"],local_links_checked=links,
        documents={str(d.relative_to(ROOT)):sha(d) for d in docs},
        selection_sha256=sha(ART/"paper-selection.json"),visual_review_sha256=sha(ART/"VISUAL_REVIEW.json"),
        inherited_frozen_audit_sha256=sha(ROOT/"output/agent-lease-20260908/DELIVERY_AUDIT.json"))
    (ART/"DELIVERY_AUDIT.json").write_text(json.dumps(result,indent=2,ensure_ascii=False)+"\n")
    print(json.dumps({k:result[k] for k in ["status","paper_figures","evaluation_figures","empty_layout_figures","new_experiments","local_links_checked"]}))


if __name__=="__main__":main()
