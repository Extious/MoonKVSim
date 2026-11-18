#!/usr/bin/env python3
"""Package already aggregated measurements for the unchanged single-column plots.

Input CSVs must already carry measured evidence, actual campaign counts, and a
source_id named in the raw manifest. This command verifies and packages provenance;
it does not aggregate samples or turn model results into measurements.
"""
import argparse,csv,hashlib,json,shutil
from pathlib import Path
from plot_expanded import SPEC,verify

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def prepare(tables,raw_manifest,out):
    provenance=json.loads(raw_manifest.read_text())
    required=['raw_sources','aggregation_command','statistical_unit','sample_accounting']
    if any(not provenance.get(k) for k in required):raise ValueError('Incomplete measurement provenance: '+str(required))
    if provenance.get('measurement_class')!='physical':raise ValueError('Only physical campaigns may use measured evidence')
    specs=json.loads(SPEC.read_text());selected={};sources={s['id'] for s in provenance['raw_sources']}
    paths=sorted(tables.glob('eval-*.csv'))
    if not paths:raise ValueError('No evaluation tables found')
    out.mkdir(parents=True,exist_ok=True)
    for p in paths:
        if p.stem not in specs:raise ValueError('Unregistered figure: '+p.stem)
        rows=list(csv.DictReader(p.open()))
        if not rows or all(r.get('y','')=='' for r in rows):continue
        # Empty/scaffold templates do not manufacture a missing result.
        for r in rows:
            if r['evidence']!='measured' or int(r['independent_runs'])<1 or r['source_id'] not in sources:
                raise ValueError('Input row lacks physical-campaign provenance: '+p.name)
        selected[p.stem]=dict(specs[p.stem],evidence='measured')
        shutil.copy2(p,out/p.name)
    if not selected:raise ValueError('All tables are empty templates')
    raw_sources=[];(out/'raw-sources').mkdir(exist_ok=True)
    for i,s in enumerate(provenance['raw_sources']):
        path=raw_manifest.parent/s['path']
        if sha(path)!=s['sha256']:raise ValueError('Raw source hash mismatch: '+str(path))
        dest=out/'raw-sources'/f'{i:02d}-{path.name}';shutil.copy2(path,dest)
        raw_sources.append(dict(s,path=str(dest.relative_to(out))))
    visual=out/'figure-specs.json';visual.write_text(json.dumps(selected,indent=2)+'\n')
    manifest=dict(provenance,evidence='per-table',source_files={},raw_sources=raw_sources,
      spec_sha256=sha(visual),tables={p.name:sha(p) for p in out.glob('eval-*.csv') if p.stem in selected})
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');verify(out,visual)
    print(f'Prepared {len(selected)} measured figures at {out}; plot with --data and --spec pointing here.')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--tables',type=Path,required=True)
    p.add_argument('--raw-manifest',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();prepare(a.tables,a.raw_manifest,a.out)
