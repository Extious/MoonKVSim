#!/usr/bin/env python3
"""Bind all ten current publication figures to generators and unchanged evidence."""
import json
from verify_delivery import PAPER, ROOT, BASE, FIGURES, digest, read
from paper_paths import DATA, TOOLS, DOCS, BUILD, DELIVERY, TEMPLATE, ARTIFACTS

def main():
 acceptance=BASE/'campaign-v2/ACCEPTANCE.json'
 assert read(acceptance)['status']=='PASS' and read(acceptance)['measured_runs']==170
 assert read(DATA/'aligned-statistics.json')['acceptance_sha256']==digest(acceptance)
 portable=read(DATA/'publication-figure-inputs.json')
 inputs=[acceptance,BASE/'campaign-v2/PROTOCOL.json',BASE/'source-v2/SOURCE_SNAPSHOT.json',
  BASE/'MOONCAKE_REFERENCE.json',BASE/'RAW_VERIFICATION.json',BASE/'verification-v1/MANIFEST.json',
  DATA/'aligned-statistics.json',DATA/'environment.json',
  DATA/'publication-figure-inputs.json',DATA/'physical-pilot/pilot-cost-profile.json',
  ROOT/'benchmark/AegisKV/experiments/workloads/fanoutqa-dev-qwen3-8b-160.jsonl',
  ROOT/'benchmark/AegisKV/experiments/scripts/analyze_mooncake_aligned_paper.py',
  *sorted(TOOLS.glob('*.py')),*sorted((DATA/'motivation-real-cc').glob('*'))]
 inputs.extend(ROOT/n for n in ('python/moonkvsim/aegiskv/prefix_frontier.py',
  'python/moonkvsim/aegiskv/foreground_budget.py','python/moonkvsim/aegiskv/revision_runtime.py',
  'benchmark/AegisKV/docs/patent/ALGORITHMS_2_3_REVISION.md',
  'benchmark/AegisKV/experiments/results/algorithm-revision-v3/VALIDATION.json'))
 # The portable plot inputs bind every ECDF endpoint source, not just a summary.
 for name,h in portable['input_bindings'].items():
  path=ROOT/name
  assert digest(path)==h, name
  inputs.append(path)
 records={}
 for stem in FIGURES:
  native=stem in ('system-overview','commit-recovery')
  scope=('observed trace gaps and branch timestamps; inferred join; frozen modeled recovery cost' if stem=='motivation-real-cc'
         else 'revision-3 intended placement and serial event reference; not native integration evidence' if stem=='system-overview'
         else 'common independent tier commit semantics; event spacing is schematic' if native
         else 'exact-token workload description' if stem=='aligned-workload'
         else 'analytical footprint and all observed physical pilot transfer samples' if stem=='aligned-motivation-cost'
         else 'accepted CPU simulation; five paired orders; hardware service uncalibrated')
  records[stem]={'evidence_scope':scope,
   'generator':('benchmark/AegisKV/experiments/scripts/paper/build_submission_diagrams.py + official Draw.io CLI' if native
                else 'benchmark/AegisKV/experiments/scripts/paper/render_submission_figures.py + benchmark/AegisKV/experiments/scripts/paper/build_submission_diagrams.py' if stem=='motivation-real-cc'
                else 'benchmark/AegisKV/experiments/scripts/paper/render_submission_figures.py + benchmark/AegisKV/experiments/scripts/paper/figure_style.py'),
   'files':{ext:digest(PAPER/'figures'/f'{stem}.{ext}') for ext in
            (('drawio','native.pdf','native.png','pdf','png') if native else ('pdf','svg','png'))}}
 components=[*sorted((PAPER/'figures').glob('motivation-workflow.*')),
             *sorted((PAPER/'figures/motivation-panels').glob('*'))]
 result={'schema':'moonkvsim.aligned_paper_figures.v2',
  'input_bindings':{str(p.relative_to(ROOT)):digest(p) for p in sorted(set(inputs)) if p.is_file()},
  'components':{str(p.relative_to(PAPER)):digest(p) for p in components if p.is_file()},
  'figures':records,'review_scope':'visual and provenance review does not validate latency models or establish performance benefit'}
 (DATA/'figure-manifest.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
 print('Bound ten figures and all editable Motivation components to their sources')
if __name__=='__main__':main()
