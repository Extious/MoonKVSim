#!/usr/bin/env python3
"""Package only sources reachable from the revised paper and bound evidence."""
import hashlib,json,re,tarfile,zipfile
from pathlib import Path
from verify_delivery import PAPER,ROOT,BASE,FIGURES,reachable
from paper_paths import DATA, TOOLS, DOCS, BUILD, DELIVERY, TEMPLATE, ARTIFACTS

def digest(p):
 with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def main():
 checks=json.loads((DATA/'delivery-checks.json').read_text());assert checks['status']=='PASS'
 assert checks['checks']['reviewed-manuscript']['evidence']['pdf_sha256']==digest(PAPER/'main.pdf'), 'Delivery audit refers to a different PDF'
 out=DELIVERY;out.mkdir(exist_ok=True)
 selected=set(reachable())
 selected.update(PAPER/x for x in ('references.bib','README.md','build.sh','acmart.cls','ACM-Reference-Format.bst'))
 selected.update(DOCS.glob('*.md'))
 selected.update((TOOLS/'templates').glob('*.tex'))
 selected.add(BUILD/'main.bbl')
 selected.add(BUILD/'main.log')
 selected.update((DATA).rglob('*'))
 selected.update((TOOLS).glob('*.py'))
 selected.update((ROOT/'benchmark/AegisKV/docs/drawio').rglob('*'))
 selected.add(ROOT/'docs/development/mooncake-aegiskv-three-way-design-implementation.md')
 selected.add(PAPER/'main.pdf')
 selected.update((PAPER/'figures').glob('motivation-workflow.*'))
 selected.update((PAPER/'figures/motivation-panels').glob('*'))
 for stem in FIGURES:
  selected.update((PAPER/'figures').glob(stem+'.*'))
 selected.add(DATA/'figure-inputs/descriptive-data.json')
 selected.add(ARTIFACTS/'review/final-review.json')
 selected.update((ARTIFACTS/'review').glob('page-*.png'))
 scripts=ROOT/'benchmark/AegisKV/experiments/scripts'
 selected.update(scripts/name for name in ('build_aegiskv_design_figures.py','build_aligned_workload_figures.py',
   'analyze_mooncake_aligned_paper.py','run_mooncake_aligned_paper.py','check_mooncake_controller_alignment.py',
   'check_mooncake_gate_alignment.py','mooncake_controller_probe.cpp'))
 # Evidence summaries and exact frozen sources are separate from the LaTeX bundle.
 paperzip=out/'aegiskv-aligned-paper-source.zip'
 with zipfile.ZipFile(paperzip,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
  for p in sorted(selected):
   if p.is_file():z.write(p,'aegiskv-paper/'+str(p.relative_to(ROOT)))
 figures=out/'aegiskv-aligned-editable-figures.zip'
 editable=set()
 for stem in (*FIGURES,'motivation-workflow'):
  editable.update((PAPER/'figures').glob(stem+'.*'))
 editable.update((PAPER/'figures/motivation-panels').glob('*'))
 editable.update((TOOLS).glob('*.py'))
 editable.update((DATA/'motivation-real-cc').glob('*'))
 editable.update(DATA/n for n in ('figure-manifest.json','publication-figure-inputs.json',
  'aligned-statistics.json','physical-pilot/pilot-cost-profile.json'))
 editable.update(DOCS/n for n in ('FIGURE_REVISION.md','RELATED_FIGURE_REVIEW.md','REPRODUCE.md','SUBMISSION_READINESS.md'))
 with zipfile.ZipFile(figures,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
  for p in sorted(editable):
   if p.is_file():z.write(p,'aegiskv-figures/'+str(p.relative_to(ROOT)))
  z.writestr('aegiskv-figures/README.md',
   'Editable publication figures: benchmark/AegisKV/paper/figures/\n'
   'From this extracted root, run benchmark/AegisKV/experiments/scripts/paper/render_submission_figures.py, '
   'then benchmark/AegisKV/experiments/scripts/paper/build_submission_diagrams.py --cli /path/to/drawio.\n'
   'See benchmark/AegisKV/docs/paper/REPRODUCE.md for environment and evidence boundaries. No simulations are run.\n')
 sourcezip=out/'aegiskv-aligned-simulation-source.tar.gz'
 with tarfile.open(sourcezip,'w:gz',compresslevel=6) as z:
  snapshot=json.loads((BASE/'source-v2/SOURCE_SNAPSHOT.json').read_text())
  for n in sorted([*snapshot['files'],'SOURCE_SNAPSHOT.json']):
   z.add(BASE/'source-v2'/n,arcname='aegiskv-simulation/source-v2/'+n)
  z.add(BASE/'test-support',arcname='aegiskv-simulation/test-support')
  z.add(BASE/'verification-v1',arcname='aegiskv-simulation/verification-v1')
  for n in ('MOONCAKE_REFERENCE.json','TEST_VALIDATION.json','RAW_VERIFICATION.json','alignment-tests-v2.log','regression-tests-v2-with-fixture.log','regression-tests-v2.log','raw-verification-v2.log','raw-verification-v2-adapter.log'):
   z.add(BASE/n,arcname='aegiskv-simulation/'+n)
  for n in ('alignment.json','gate-alignment.json'):
   z.add(BASE/'native-conformance'/n,arcname='aegiskv-simulation/native-conformance/'+n)
  # Preserve the actual referenced source contents, not just its dirty Git HEAD.
  ref=json.loads((BASE/'MOONCAKE_REFERENCE.json').read_text())
  for n,h in ref['files'].items():
   p=Path(ref['reference_root'])/n;assert digest(p)==h
   z.add(p,arcname='aegiskv-simulation/mooncake-reference/'+n)
  for n in ('PROTOCOL.json','EXECUTION.json','ACCEPTANCE.json','PLANS_READY.json'):
   z.add(BASE/'campaign-v2'/n,arcname='aegiskv-simulation/accepted-campaign/'+n)
  z.add(BASE/'campaign-v2/plans',arcname='aegiskv-simulation/accepted-campaign/plans')
  z.add(DOCS/'REPRODUCE.md',arcname='aegiskv-simulation/REPRODUCE.md')
  z.add(DATA/'aligned-statistics.json',arcname='aegiskv-simulation/accepted-campaign/aligned-statistics.json')
 manifest={'schema':'moonkvsim.aligned_paper_packages.v1','files':{p.name:{'sha256':digest(p),'bytes':p.stat().st_size} for p in (paperzip,figures,sourcezip)},
           'paper_pdf_sha256':digest(PAPER/'main.pdf'),
           'raw_evidence':'Compressed raw executions remain in output/paper-simulation-8b/20260906-alignment/campaign-v2/runs; all hashes are in ACCEPTANCE.json. They are not silently substituted by summary JSON in these packages.'}
 (out/'MANIFEST.json').write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n');print(json.dumps(manifest,indent=2))
if __name__=='__main__':main()
