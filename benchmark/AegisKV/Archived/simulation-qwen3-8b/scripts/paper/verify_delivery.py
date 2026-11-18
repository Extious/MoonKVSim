#!/usr/bin/env python3
"""Verify revised-study bindings and reviewed PDF; not a scientific peer review."""
from __future__ import annotations
import argparse, datetime, hashlib, json, re
from pathlib import Path
import pymupdf
from paper_paths import PAPER, ROOT, DATA, TOOLS, DOCS, BUILD, DELIVERY, TEMPLATE, ARTIFACTS
BASE=ROOT/'output/paper-simulation-8b/20260906-alignment'
CAMPAIGN=BASE/'campaign-v2'
FIGURES=('motivation-real-cc','aligned-motivation-cost','system-overview','commit-recovery',
         'aligned-workload','aligned-healthy','aligned-failure','aligned-recovery',
         'aligned-ablations','aligned-sensitivity')
def digest(p):
 with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def read(p):return json.loads(p.read_text())
def canonical(d):return hashlib.sha256(json.dumps(d,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def require(x,msg):
 if not x:raise ValueError(msg)
def source():
 p=BASE/'source-v2';s=read(p/'SOURCE_SNAPSHOT.json')
 for n,h in s['files'].items():require(digest(p/n)==h,'frozen source drift: '+n)
 protocol=read(CAMPAIGN/'PROTOCOL.json')
 require(protocol['source_sha256']==canonical(s),'protocol source mismatch')
 require(protocol['fingerprint']==canonical({k:v for k,v in protocol.items() if k!='fingerprint'}),'protocol fingerprint')
 return dict(verified_files=len(s['files']),source_sha256=canonical(s),protocol=protocol['fingerprint'])
def evidence():
 v=read(BASE/'RAW_VERIFICATION.json')
 require(v['status']=='PASS' and v['acceptance_sha256']==digest(CAMPAIGN/'ACCEPTANCE.json'),'raw verification binding')
 require(v['adapter_sha256']==digest(BASE/'verification-v1/verify_mooncake_aligned_paper.py'),'verification adapter drift')
 a=read(CAMPAIGN/'ACCEPTANCE.json');p=read(CAMPAIGN/'PROTOCOL.json')
 require(a['status']=='PASS' and a['measured_runs']==p['expected_measured_runs']==170,'incomplete campaign')
 require(a['contract']==p['fingerprint'],'acceptance contract')
 jobs={tuple(x['job']):x for x in a['accepted_runs']}
 require(len(jobs)==170 and set(jobs)=={tuple(x) for x in p['jobs']},'acceptance population')
 stats=read(DATA/'aligned-statistics.json')
 require(stats['acceptance_sha256']==digest(CAMPAIGN/'ACCEPTANCE.json'),'analysis acceptance drift')
 require(stats['generator_sha256']==digest(ROOT/'benchmark/AegisKV/experiments/scripts/analyze_mooncake_aligned_paper.py'),'analysis generator drift')
 for n,h in stats['input_bindings'].items():require(digest(CAMPAIGN/n)==h,'analysis input drift: '+n)
 for job,item in jobs.items():
  point,seed,f,arm=job;q=CAMPAIGN/'runs'/point/f'seed{seed}'/f'{f}-{arm}.json';d=read(q)
  require(d['identity']['job']==list(job) and d['identity']['contract']==a['contract'],'checkpoint identity')
  require(d['raw_evidence']['sha256']==item['raw_sha256'],'raw binding mismatch')
  # Raw data was independently reloaded and audited before acceptance. Hash it
  # again here; this check does not merely trust a copied PASS flag.
  require(digest(q.with_suffix('.raw.json.gz'))==item['raw_sha256'],'raw artifact drift')
 return dict(measured_runs=170,acceptance_sha256=digest(CAMPAIGN/'ACCEPTANCE.json'),analysis_sha256=digest(DATA/'aligned-statistics.json'))
def conformance():
 validation=read(BASE/'TEST_VALIDATION.json')
 require(validation['status']=='PASS' and validation['source_snapshot_sha256']==digest(BASE/'source-v2/SOURCE_SNAPSHOT.json'),'test source binding')
 for suite in validation['suites'].values():
  require(digest(BASE/suite['log'])==suite['log_sha256'],'test log drift')
  for n,h in suite['test_source_sha256'].items():require(digest(BASE/'source-v2'/n)==h,'tested source drift: '+n)
 ref=read(BASE/'MOONCAKE_REFERENCE.json');r=Path(ref['reference_root'])
 for n,h in ref['files'].items():require(digest(r/n)==h,'reference drift: '+n)
 for name,count in [('alignment.json',260),('gate-alignment.json',6)]:
  d=read(BASE/'native-conformance'/name);require(d['status']=='PASS' and d['case_count']==count,'native check incomplete')
  require(digest(BASE/'native-conformance'/name)==validation['native'][name]['sha256'],'native result drift')
  if isinstance(d['reference_sha256'],dict):
   for n,h in d['reference_sha256'].items():require(digest(Path(n))==h,'native harness/reference drift')
  else:
   require(d['generator_sha256']==digest(ROOT/'benchmark/AegisKV/experiments/scripts/check_mooncake_gate_alignment.py'),'gate harness drift')
 for name,count in [('alignment-tests-v2.log',127),('regression-tests-v2-with-fixture.log',184)]:
  text=(BASE/name).read_text();require(re.search(rf'\b{count} passed\b',text) and not re.search(r'\d+ (failed|errors)',text),'regression incomplete: '+name)
 return dict(native_policy_cases=260,native_gate_sequences=6,targeted_tests=127,related_regression_tests=184,scope='selected suites; not a whole-repository green claim')
def reachable():
 seen={};pending=[PAPER/'main.tex']
 while pending:
  p=pending.pop()
  if p in seen:continue
  t=p.read_text();seen[p]=t
  pending += [PAPER/(n if Path(n).suffix else n+'.tex') for n in re.findall(r'\\input\{([^}]+)\}',t)]
 return seen

def figures(review):
 manifest=read(DATA/'figure-manifest.json');require(set(manifest['figures'])==set(FIGURES),'figure population')
 for n,h in manifest['input_bindings'].items():require(digest(ROOT/n)==h,'figure input drift: '+n)
 for n,h in manifest.get('components',{}).items():require(digest(PAPER/n)==h,'figure component drift: '+n)
 result={}
 for stem in FIGURES:
  item=manifest['figures'][stem]
  for ext,h in item['files'].items():require(digest(PAPER/'figures'/f'{stem}.{ext}')==h,'figure output drift: '+stem)
  require(review['figures'][stem]['status']=='VISUALLY_CHECKED' and review['figures'][stem]['pdf_sha256']==item['files']['pdf'],'stale figure review: '+stem)
  with pymupdf.open(PAPER/'figures'/f'{stem}.pdf') as pdf:
   require(len(pdf)==1,'figure multiple pages: '+stem)
   require(not pdf[0].get_images(full=True),'raster embedded in vector figure: '+stem)
   spans=[s for b in pdf[0].get_text('dict')['blocks'] if 'lines' in b for l in b['lines'] for s in l['spans'] if s['text'].strip()]
   minimum=min(s['size'] for s in spans)*504/pdf[0].rect.width
   require(minimum>=9.99,'figure scales below 10 PDF pt: '+stem)
   result[stem]={'embedded_min_font_pt':minimum,'pdf_sha256':item['files']['pdf']}
 return result

def manuscript(review):
 claims=read(DATA/'claim-bindings.json')
 require(claims['status']=='PASS' and claims['statistics_sha256']==digest(DATA/'aligned-statistics.json'),'claim input binding')
 require(claims['generator_sha256']==digest(TOOLS/'write_result_sections.py'),'claim writer drift')
 require(claims['template_sha256']==digest(TEMPLATE),'claim template drift')
 for n,h in claims['output_sha256'].items():require(digest(PAPER/'sections'/n)==h,'claim output drift: '+n)
 tex=reachable();text='\n'.join(tex.values())
 require(not re.search(r'working draft|working section|awaiting the|Numerical analysis is in progress|TODO|TBD',text,re.I),'unfinished manuscript')
 require(set(re.findall(r'\\includegraphics(?:\[[^]]*\])?\{figures/([^}]+)\.pdf\}',text))==set(FIGURES),'compiled figures differ')
 log=(BUILD/'main.log').read_text(encoding='latin-1')
 bad=re.findall(r'Overfull[^\n]*|LaTeX Warning: (?:Reference|Citation)[^\n]*undefined[^\n]*|There were undefined references|Float too large[^\n]*|^!.*$',log,re.M)
 require(not bad,'unresolved build problems: '+str(bad))
 h=digest(PAPER/'main.pdf');require(review['manuscript']['pdf_sha256']==h,'stale manuscript review')
 with pymupdf.open(PAPER/'main.pdf') as pdf:
  texts=[p.get_text() for p in pdf];refs=[i+1 for i,t in enumerate(texts) if re.search(r'(?m)^References\s*$',t)]
  require(len(refs)==1,'cannot locate unique references heading')
  require('\\clearpage\n\\bibliographystyle' in tex[PAPER/'main.tex'],'references must start after all technical content')
  require(refs[0]-1<=12,'technical material exceeds 12 pages')
  require(not any(re.search(r'Figure \d+\.|Algorithm \d+',t) for t in texts[refs[0]-1:]),'technical floats appear after references')
  joined='\n'.join(texts)
  for i in range(1,11):require(f'Figure {i}.' in joined,'missing figure caption '+str(i))
  for i in range(1,4):require(f'Algorithm {i}' in joined,'missing algorithm '+str(i))
  pages=review['manuscript']['pages'];require(len(pages)==len(pdf) and all(x['status']=='VISUALLY_CHECKED' for x in pages),'incomplete page review')
  for i,x in enumerate(pages):require(x['page']==i+1 and digest(ARTIFACTS/x['render'])==x['sha256'],'page review binding')
  return dict(pdf_sha256=h,pages=len(pdf),references_start_page=refs[0],technical_pages=refs[0]-1,source_sha256={str(p.relative_to(PAPER)):digest(p) for p in tex})
def motivation():
 import xml.etree.ElementTree as ET
 folder=DATA/'motivation-real-cc'
 reconstruction=read(folder/'RAW_RECONSTRUCTION.json')
 require(reconstruction['status']=='PASS' and reconstruction['sessions']==393 and reconstruction['qualifying_workflows']==124,'motivation population')
 require(reconstruction['generator_sha256']==digest(TOOLS/'verify_motivation_trace.py'),'motivation checker drift')
 require(reconstruction['max_csv_error_s']<1e-8,'observed gap mismatch')
 require(digest(Path(reconstruction['trace_path']))==reconstruction['trace_sha256'],'motivation raw trace drift')
 for item in read(folder/'IMPORT.json')['files']:
  require(digest(folder/item['copy'])==item['sha256'],'historical motivation import drift')
 for stem in ('motivation-workflow','system-overview','commit-recovery'):
  xml=ET.parse(PAPER/'figures'/f'{stem}.drawio')
  require(xml.getroot().tag=='mxfile' and len(xml.findall('.//mxGraphModel'))==1,'invalid editable diagram')
 return {k:reconstruction[k] for k in ('sessions','qualifying_workflows','max_csv_error_s','trace_sha256','latency_prediction_reexecuted','latency_model_calibrated_to_trace_hardware','boundary')}

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,default=DATA/'delivery-checks.json');a=p.parse_args()
 checks={}
 def check(n,fn):
  try:checks[n]={'status':'PASS','evidence':fn()}
  except Exception as e:checks[n]={'status':'INCOMPLETE_OR_FAILED','reason':f'{type(e).__name__}: {e}'}
 check('frozen-source',source);check('accepted-raw-and-analysis',evidence);check('reference-and-tests',conformance);check('historical-motivation',motivation)
 try:review=read(ARTIFACTS/'review/final-review.json')
 except Exception:review={}
 check('ten-reviewed-figures',lambda:figures(review));check('reviewed-manuscript',lambda:manuscript(review))
 failed=[n for n,c in checks.items() if c['status']!='PASS']
 result=dict(schema='moonkvsim.aligned_paper_delivery.v1',status='PASS' if not failed else 'INCOMPLETE_OR_FAILED',checked_at=datetime.datetime.now(datetime.UTC).isoformat(),checks=checks,open_checks=failed,scope='artifact consistency plus separately recorded visual review; not physical performance validation')
 a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n');print(json.dumps({'status':result['status'],'open_checks':failed}));return bool(failed)
if __name__=='__main__':raise SystemExit(main())
