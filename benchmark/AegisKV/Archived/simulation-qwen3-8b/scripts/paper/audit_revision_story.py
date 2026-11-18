"""Check provenance, paired data, completed sweeps and actual-size exports."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import json
import re
from pathlib import Path

import pymupdf as fitz
import numpy as np

from render_revision_scaling import ROOT, ART, OUT, SYSTEMS, sha


def load(p):
    return json.loads(p.read_text())


def check_bindings(bindings):
    for path,digest in bindings.items():
        p=Path(path)
        if not p.is_absolute():p=ROOT/p
        assert sha(p)==digest, path


def csv_rows(path):
    with path.open() as f:return list(csv.DictReader(f))


def check_diagnostics():
    data={s:load(ROOT/f'output/agent-lease-20260908/data/f0-base/{s}.json') for s in SYSTEMS}
    workflows={s:{w['workflow_id']:w for w in data[s]['workflows']} for s in SYSTEMS}
    rows=csv_rows(OUT/'eval-workflow-delay.csv');assert len(rows)==480
    for r in rows:
        base=workflows['mooncake'][r['workflow_id']]['wct_s']
        value=workflows[r['system']][r['workflow_id']]['wct_s']
        assert np.isclose(value,float(r['wct_s']))
        assert np.isclose(value-base,float(r['delta_wct_s']))
        assert np.isclose(100*(value/base-1),float(r['overhead_pct']))
    rows=csv_rows(OUT/'eval-initial-reuse.csv');assert len(rows)==480
    for r in rows:
        requests=[q for q in data[r['system']]['requests'] if q['workflow_id']==r['workflow_id'] and q['span_id'].endswith(':revisit-1')]
        assert requests
        prompt=sum(q['prompt_tokens'] for q in requests)
        hit=sum(q['dram_hit_tokens'] for q in requests)
        assert prompt==int(r['revisit_prompt_tokens']) and hit==int(r['revisit_dram_hit_tokens'])
        assert np.isclose(100*hit/prompt,float(r['revisit_initial_dram_token_hit_pct']))
    focal=csv_rows(OUT/'eval-fault-paired-wct.csv');assert len(focal)==9
    for r in focal:
        f1=load(ROOT/f'output/agent-lease-20260908/data/f1-q{r["legacy_progress_pct"]}/{r["system"]}.json')
        value=next(w['wct_s'] for w in f1['workflows'] if w['workflow_id']==r['workflow_id'])
        base=workflows[r['system']][r['workflow_id']]['wct_s']
        assert np.isclose(value,float(r['f1_wct_s'])) and np.isclose(base,float(r['f0_wct_s']))
    tokens=csv_rows(OUT/'eval-fault-token-source.csv')
    old=csv_rows(ROOT/'output/pdf/aegiskv-evaluation-20260909/eval-failure-kv.csv')
    key=lambda r:(r['case_id'],r['system'],r['source'])
    assert {key(r):int(r['tokens']) for r in tokens}=={key(r):int(float(r['tokens'])) for r in old}
    progress=csv_rows(OUT/'eval-preemption-progress.csv')
    assert {r['system'] for r in progress}==set(SYSTEMS)
    assert {r['focus_span_id'] for r in progress}=={'fanoutqa:3d0739b161908b67:2ff5a0169b37cd46:revisit-1'}
    for r in progress:
        assert np.isclose((int(r['timestamp_ns'])-int(r['workflow_release_ns']))/1e9,float(r['relative_time_s']))
    return dict(paired_wct_points=480,revisit_hit_points=480,focal_pairs=9,recovery_token_components=len(tokens),progress_boundaries=len(progress))


def check_workflow_contrasts():
    points=load(ART/'scaling/points.json')
    by_cell={}
    for r in points:
        p=Path(r['data_path']);p=p if p.is_absolute() else ROOT/p
        by_cell[r['concurrency'],r['system']]={w['workflow_id']:w['wct_s'] for w in load(p)['workflows']}
    main=csv_rows(OUT/'eval-concurrency-workflow.csv');assert len(main)==480
    all_rows=csv_rows(OUT/'eval-concurrency-workflow-all-concurrency.csv');assert len(all_rows)==1920
    for r in main+all_rows:
        c,s,w=int(r['concurrency']),r['system'],r['workflow_id']
        assert np.isclose(float(r['wct_s']),by_cell[c,s][w])
        assert np.isclose(float(r['mooncake_wct_s']),by_cell[c,'mooncake'][w])
        assert np.isclose(float(r['delta_wct_s']),by_cell[c,s][w]-by_cell[c,'mooncake'][w])
    aegis=[float(r['delta_wct_s']) for r in main if r['system']=='aegis']
    assert sum(v<0 for v in aegis)==65 and sum(v>0 for v in aegis)==95
    rows=csv_rows(OUT/'eval-fixed-event-wct.csv');assert len(rows)==21
    data={(k,s):load(ART/f'scaling-rate/data/k{k}-{s}.json') for k in [1,2] for s in SYSTEMS}
    for r in rows:
        s,w=r['system'],r['workflow_id']
        pair=[]
        for k in [1,2]:
            d=data[k,s]
            wct=next(q['wct_s'] for q in d['workflows'] if q['workflow_id']==w)
            requests=[q for q in d['requests'] if q['workflow_id']==w]
            release=min(q['released_ns'] for q in requests)/1e9
            completion=max(q['completed_ns'] for q in requests)/1e9
            assert np.isclose(completion-release,wct)
            pair.append((wct,release,completion))
        assert pair[0][1]==pair[1][1]
        assert np.isclose(float(r['plotted_wct_k1_s']),pair[0][0])
        assert np.isclose(float(r['plotted_wct_k2_s']),pair[1][0])
        assert np.isclose(float(r['plotted_delta_s']),pair[1][0]-pair[0][0])
        assert np.isclose(float(r['plotted_delta_s']),pair[1][2]-pair[0][2])
    assert len({r['workflow_id'] for r in rows})==7
    prefix=load(ART/'scaling-rate/FIXED_EVENT_PREFIX_AUDIT.json')
    assert prefix['status']=='PASS'
    full=load(ART/'scaling-rate/data/fixed-event-all-workflows.json')
    assert full['status']=='PASS' and full['prefix_audit_sha256']==sha(ART/'scaling-rate/FIXED_EVENT_PREFIX_AUDIT.json')
    check_bindings(full['source_sha256'])
    assert len(full['rows'])==480
    assert len({(r['system'],r['workflow_id']) for r in full['rows']})==480
    for r in full['rows']:
        s,w=r['system'],r['workflow_id']
        control=[q for q in data[1,s]['requests'] if q['workflow_id']==w]
        treatment=[q for q in data[2,s]['requests'] if q['workflow_id']==w]
        for tag,requests in [('control',control),('treatment',treatment)]:
            assert r[f'release_{tag}_ns']==min(q['released_ns'] for q in requests)
            assert r[f'completion_{tag}_ns']==max(q['completed_ns'] for q in requests)
        dr=r['release_treatment_ns']-r['release_control_ns']
        dc=r['completion_treatment_ns']-r['completion_control_ns']
        assert r['delta_release_ns']==dr and r['delta_completion_ns']==dc
        assert r['delta_wct_ns']==dc-dr
        assert r['identity_residual_ns']==0
        assert np.isclose(r['delta_wct_s'],(dc-dr)/1e9)
    return dict(concurrency_same_id_points=len(all_rows),fixed_added_event_points=len(rows),fixed_added_event_equal_release_pairs=len(rows),all_workflow_release_completion_identities=480)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare-visuals',action='store_true')
    args=parser.parse_args()
    selection=load(ART/'paper-selection.json')
    assert selection['template_sha256']==sha(Path(__file__).with_name('templates')/'revision-draft.md')
    assert selection['generator_sha256']==sha(Path(__file__).with_name('build_revision_story.py'))
    assert selection['captions_sha256']==sha(Path(__file__).with_name('revision_draft_captions.py'))
    planned=selection['planned_figures']
    assert planned['status']=='PLANNED_NOT_RUN' and sha(ROOT/planned['path'])==planned['sha256']
    specification=load(ROOT/planned['path'])
    plans=specification['groups']
    assert len(plans)==planned['groups']==8
    assert sum(len(r['plots']) for r in plans)==planned['candidate_figures']==10
    assert [r['id'] for r in plans]==[f'P{i}' for i in range(1,9)]
    for r in plans:
        assert r['status']=='PLANNED_NOT_RUN'
        assert all(r[k].strip() for k in ['key','title','question','protocol','expected','refutation','data','placement'])
        for p in r['plots']:assert all(p[k].strip() for k in ['id','type','x','y','series'])
    figures=selection['figures']
    assert Counter(r['section'] for r in figures)==dict(Motivation=3,**{'System Design':1},Evaluation=len(figures)-4)
    assert [r['id'] for r in figures]==[str(i) for i in range(1,len(figures)+1)]
    assert len({r['name'] for r in figures})==len(figures)
    assert [n for g in selection['layout_groups'] for n in g]==[r['name'] for r in figures]
    for r in figures:
        for ext,digest in r['files'].items():assert sha(OUT/f'{r["name"]}.{ext}')==digest
    assert len(figures)==13 and not any(r['name'].endswith('-tail') for r in figures)
    for name in ['diagnostics-manifest.json','scaling-manifest.json','concurrency-workflow-manifest.json','fixed-event-wct-manifest.json']:
        m=load(OUT/name); check_bindings(m['inputs'])
    motivation=load(OUT/'motivation-recompute-manifest.json')
    check_bindings(motivation['sources'])
    assert sha(ROOT/motivation['generator']['path'])==motivation['generator']['sha256']
    source_rows=csv_rows(OUT/'sources/motivation-recompute/legacy-data.csv')
    selected_rows=[r for r in source_rows if r['model'] in ['Qwen3-8B','Qwen3-32B'] and r['path_key']=='recompute']
    assert len(selected_rows)==8 and csv_rows(OUT/'motivation-recompute.csv')==selected_rows
    overview=load(OUT/'overview-manifest.json')
    assert sha(ROOT/overview['sources'][0])==overview['source_sha256']
    diagnostics=check_diagnostics()
    diagnostics['historical_recompute_predictions']=8
    diagnostics.update(check_workflow_contrasts())
    prior=load(ROOT/'output/evaluation-redesign-20260909/paper-selection.json')
    for r in prior['figures']:
        for ext,digest in r['files'].items():
            assert sha(ROOT/f'output/pdf/aegiskv-evaluation-20260909/{r["name"]}.{ext}')==digest
    for r in load(ART/'before-revision/REVISION_BASE.json'):
        assert sha(ROOT/r['copy'])==r['sha256']
    # Verify the immutable algorithm snapshot itself, not just its manifest name.
    source=ROOT/'output/agent-lease-20260908/source-v3'
    snap=load(source/'MECHANISM_SOURCE_SNAPSHOT.json')
    bindings=snap.get('files',snap.get('inputs'))
    if isinstance(bindings,dict):
        for path,digest in bindings.items():
            if isinstance(digest,dict):digest=digest['sha256']
            assert sha(source/path)==digest, path
    else:
        for r in bindings:
            assert sha(source/r['path'])==r['sha256']
    # Independently recheck every completed scaling point from its reduced data.
    checks=[]
    reference=load(ROOT/'output/agent-lease-20260908/data/f0-base/mooncake.json')
    expected_spans={r['span_id'] for r in reference['requests']}
    expected_workflows={r['workflow_id'] for r in reference['workflows']}
    for sweep in ['scaling','scaling-rate']:
        p=ART/sweep/'points.json'
        if not p.exists():
            assert sweep=='scaling-rate' and not selection['rate_figures']
            continue
        rows=load(p);assert len(rows)==12
        for r in rows:
            assert r['completed_workflows']==r['expected_workflows']==160
            assert r['completed_requests']==r['expected_requests']==2608
            if 'data_path' in r:
                dp=Path(r['data_path']);dp=dp if dp.is_absolute() else ROOT/dp
                if 'data_sha256' in r:assert sha(dp)==r['data_sha256']
                data=load(dp)
                assert len(data['workflows'])==160 and len(data['requests'])==2608
                assert {q['span_id'] for q in data['requests']}==expected_spans
                assert {q['workflow_id'] for q in data['workflows']}==expected_workflows
                assert np.isclose(np.percentile([w['wct_s'] for w in data['workflows']],95),r['p95_wct_s'])
                if sweep=='scaling-rate':
                    window_completions=sum(max(q['completed_ns'] for q in data['requests'] if q['workflow_id']==wid)<=480_000_000_000 for wid in expected_workflows)
                    assert window_completions==r['window_completed_workflows']
                    assert np.isclose(window_completions/480,r['window_workflows_per_second'])
                    assert r['failure_rate_per_cluster_hour']==r['failure_count']*3600/480
            checks.append(dict(sweep=sweep,system=r['system'],point=r.get('concurrency',r.get('failure_rate_per_cluster_hour'))))
    doc=ROOT/'benchmark/AegisKV/experiments/Paper_Draft.md'
    text=doc.read_text()
    assert re.findall(r'^## (.+)$',text,re.M)==['Motivation','System Design','Evaluation']
    assert text.count('<img src=')==len(figures)
    assert re.findall(r'<aside class="planned-figure" id="planned-([^"]+)"',text)==[r['key'] for r in plans]
    assert text.count('（尚无结果）')==len(plans)
    # This turn revises the manuscript and plans, not the existing numerical exports.
    prior_story=load(ART/'draft-refinement/before/paper-selection.json')
    assert {r['name']:r['files'] for r in figures}=={r['name']:r['files'] for r in prior_story['figures']}
    assert '{{' not in text and '先评价联合终点' not in text and 'G_x=' not in text
    previews=ROOT/'tmp/pdfs/revision-review';previews.mkdir(parents=True,exist_ok=True)
    metadata=[]
    for r in figures:
        pdf=fitz.open(OUT/f'{r["name"]}.pdf');assert len(pdf)==1
        page=pdf[0]
        assert abs(page.rect.width/72-r['width_in'])<.02
        spans=[s for b in page.get_text('dict')['blocks'] if 'lines' in b for line in b['lines'] for s in line['spans'] if s['text'].strip()]
        # Math superscripts are conventionally scaled relative to a 10 pt base.
        # The copied log-axis figure has exactly five 7 pt power digits 0..4.
        scripts=[s for s in spans if s['size']<9.85]
        if scripts:
            assert r['name']=='motivation-branch-gap'
            assert [s['text'] for s in scripts]==list('01234')
            assert all(s['flags']&1 and np.isclose(s['size'],7) for s in scripts)
        minimum=min(s['size'] for s in spans if s['size']>=9.85)
        assert minimum>=9.85,(r['name'],minimum)
        overflow=[s['text'] for s in spans if s['bbox'][0]<-.75 or s['bbox'][1]<-.75 or s['bbox'][2]>page.rect.width+.75 or s['bbox'][3]>page.rect.height+.75]
        assert not overflow,(r['name'],'text beyond PDF page',overflow)
        metadata.append(dict(name=r['name'],width_in=page.rect.width/72,min_body_font_pt=minimum,min_font_pt=min(s['size'] for s in spans),mathematical_superscripts_below_body_size=len(scripts),pdf_sha256=sha(OUT/f'{r["name"]}.pdf')))
        if args.prepare_visuals:page.get_pixmap(matrix=fitz.Matrix(2,2),alpha=False).save(previews/f'{r["name"]}.png')
    proof=fitz.open(OUT/'paper-placement.pdf')
    if args.prepare_visuals:
        for i,page in enumerate(proof):page.get_pixmap(matrix=fitz.Matrix(1.5,1.5),alpha=False).save(previews/f'placement-{i+1:02}.png')
    (ART/'PDF_METADATA.json').write_text(json.dumps(metadata,indent=2)+'\n')
    if args.prepare_visuals:
        print(json.dumps({'prepared_figures':len(figures),'proof_pages':len(proof)}));return
    visual=load(ART/'VISUAL_REVIEW.json')
    assert visual['status']=='PASS'
    assert visual['paper_selection_sha256']==sha(ART/'paper-selection.json')
    assert visual['paper_placement_sha256']==sha(OUT/'paper-placement.pdf')
    assert visual['pdf_hashes']=={r['name']:sha(OUT/f'{r["name"]}.pdf') for r in figures}
    placement=load(ART/'PLACEMENT_VISUAL_REVIEW.json')
    assert placement['status']=='PASS' and placement['paper_placement_sha256']==sha(OUT/'paper-placement.pdf')
    assert placement['pages_reviewed']==len(proof)
    layout=load(ART/'MARKDOWN_LAYOUT.json')
    assert layout['source_sha256']==sha(doc) and layout['images']==len(figures) and layout['loaded']
    assert layout['planned_groups']==len(plans) and layout['planned_images']==0
    assert layout['overflow']['document']<=layout['overflow']['viewport']
    audit=dict(status='PASS',scope='provenance, completed simulated points, figure exports and visually checked placement; not native performance certification',
        paper_figures=len(figures),scaling_points_checked=len(checks),historical_figures_unchanged=len(prior['figures']),
        planned_groups=len(plans),unexecuted_candidate_figures=planned['candidate_figures'],new_simulations_in_draft_refinement=0,
        new_complete_scaling_simulations=15 if selection['rate_figures'] else 6,
        reused_unique_complete_scaling_simulations=6,
        shared_points_between_sweeps=3 if selection['rate_figures'] else 0,
        immutable_source_files=len(bindings),algorithm2_implementation_changed=False,
        independent_numeric_checks=diagnostics,
        paper_sha256=sha(doc),selection_sha256=sha(ART/'paper-selection.json'),
        visual_review_sha256=sha(ART/'VISUAL_REVIEW.json'),markdown_layout_sha256=sha(ART/'MARKDOWN_LAYOUT.json'))
    (ART/'DELIVERY_AUDIT.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(audit,ensure_ascii=False))


if __name__=='__main__':main()
