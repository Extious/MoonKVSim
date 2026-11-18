#!/usr/bin/env python3
"""Data, pairing, provenance and manuscript checks; not physical validation."""
import csv
import hashlib
import json
import re
import tempfile
from pathlib import Path

import fitz

import theory
from aggregate_workflows import aggregate
from plot import read_tables

ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'exports/evaluation-expanded-20260921'


def check_pairing():
    rows=[]
    for campaign,count,delta in [('a',20,2),('b',1,6)]:
        for w in range(count):
            for policy,healthy,penalty in [('LRU',10,10),('AegisKV',20,delta)]:
                for condition,value in [('healthy',healthy),('fault',healthy+penalty)]:
                    rows.append(dict(x='16',campaign_id=campaign,pair_id='pair',workflow_id=str(w),
                        policy=policy,condition=condition,wct_s=str(value),status='completed'))
    stats,ledger=aggregate(rows,'LRU','penalty')
    result={r['series']:r for r in stats}
    assert result['AegisKV']['independent_runs']==2
    assert result['AegisKV']['y']==4  # campaign weighted, not 46/21 workflow weighted
    differences,_=aggregate(rows,'LRU','difference')
    assert next(r for r in differences if r['series']=='AegisKV')['y']==6
    try:aggregate(rows[:-1],'LRU','penalty')
    except ValueError:pass
    else:raise AssertionError('Missing paired condition was accepted')
    altered=[dict(r) for r in rows]
    altered[0]['status']='timeout';altered[0]['wct_s']=''
    _,ledger=aggregate(altered,'LRU','penalty')
    assert ledger['excluded_incomplete_cases'][16.0]==1
    return 'PASS: own-policy healthy mates, campaign unit, missing pairs, timeout ledger'


def main():
    cfg=json.loads(theory.CONFIG.read_text());theory.self_check(cfg)
    data=theory.OUT;tables,manifest=read_tables(data,'analytical')
    rows=list(csv.DictReader((data/'scenario-results.csv').open()))
    assert len({r['scenario_id'] for r in rows})==36 and len(rows)==180
    by={}
    for r in rows:by.setdefault(r['scenario_id'],{})[r['policy']]=r
    for policies in by.values():
        best=float(policies['Feasible oracle']['objective_s'])
        for r in policies.values():assert best<=float(r['objective_s'])+1e-9
    demotion=[r for r in tables['safe-demotion'] if r['series']=='Physical DRAM']
    assert next(r['y'] for r in demotion if r['x']==5)==24
    assert next(r['y'] for r in demotion if r['x']==5.5)==16
    tiny=theory.Group('one-chunk',.25,1,1)
    exact=cfg['floor_s']+.25/cfg['dram_read_GiB_s']+.25/cfg['shared_link_GiB_s']+.25/cfg['h2d_GiB_s']+cfg['replay_s']
    assert abs(theory.restore([tiny],{0},cfg)[0]-exact)<1e-9
    with tempfile.TemporaryDirectory(prefix='aegiskv-provenance-check-') as tmp:
        d=Path(tmp);fake=dict(manifest,evidence='measured')
        (d/'manifest.json').write_text(json.dumps(fake))
        try:read_tables(d,'measured')
        except ValueError:pass
        else:raise AssertionError('Theory relabel accepted without raw provenance')
    pairing=check_pairing()
    paper=ROOT/'paper';tex='\n'.join(p.read_text() for p in paper.glob('*.tex'))
    expected={'main.tex','abstract.tex','background_and_motivation.tex','system_design.tex'}
    assert {p.name for p in paper.glob('*.tex')}==expected
    assets=sorted(set(re.findall(r'\\includegraphics(?:\[[^]]*\])?\{([^}]+)\}',tex)))
    for asset in assets:assert (paper/asset).is_file(),asset
    log=(ROOT/'exports/latex-build/main.log').read_text()
    problems=[line for line in log.splitlines() if re.search(r'Overfull|undefined|LaTeX Error|Emergency stop',line)]
    assert not problems,'\n'.join(problems)
    pdf=fitz.open(paper/'main.pdf')
    references=next((i+1 for i,p in enumerate(pdf) if 'References' in p.get_text().splitlines()),None)
    # The user explicitly removed the draft-stage 12-page constraint on Sep 21.
    assert references is not None
    source_snapshot=json.loads((ROOT/'exports/eurosys-complete-20260920/source-snapshot.json').read_text())
    old_figure_consistency={}
    for name in ['workflow','workflow-gaps','recovery-exposure']:
        p=paper/'figures'/f'{name}.pdf'
        key=str(p.relative_to(ROOT.parents[1]))
        # The repository-relative baseline is used when available.
        old=source_snapshot['figure_pdfs'].get(key)
        old_figure_consistency[name]=old is None or hashlib.sha256(p.read_bytes()).hexdigest()==old
    report={'checks':'PASS','scope':'arithmetic, analytical model, data provenance, statistical pairing and manuscript build; no physical execution',
        'analytical_tables':len(tables),'scenario_rows':len(rows),'independent_physical_runs':0,
        'pairing':pairing,'pdf_pages':len(pdf),'references_start_page':references,
        'technical_content_last_page':references,'figure_assets':len(assets),
        'latex_overfull_or_undefined':problems,'preserved_motivation_figures':old_figure_consistency,
        'paper_sha256':hashlib.sha256((paper/'main.pdf').read_bytes()).hexdigest(),
        'source_hashes':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in sorted(paper.glob('*.tex'))}}
    (OUT/'CHECKS.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
