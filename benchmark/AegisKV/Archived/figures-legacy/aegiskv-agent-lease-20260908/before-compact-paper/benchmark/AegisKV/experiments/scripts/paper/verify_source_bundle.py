#!/usr/bin/env python3
"""Rebuild extracted paper and figures; compare rendered pixels with delivery."""
import hashlib, json, os, subprocess, sys, tarfile, zipfile
from pathlib import Path
import pymupdf
from verify_delivery import PAPER, ROOT, BASE, FIGURES, digest, read
from paper_paths import DATA, TOOLS, DOCS, BUILD, DELIVERY, TEMPLATE, ARTIFACTS

def identical_pages(left,right):
 with pymupdf.open(left) as a,pymupdf.open(right) as b:
  assert len(a)==len(b), (left,len(a),len(b))
  rows=[]
  for i in range(len(a)):
   aa=a[i].get_pixmap(matrix=pymupdf.Matrix(1.5,1.5));bb=b[i].get_pixmap(matrix=pymupdf.Matrix(1.5,1.5))
   h=lambda x:hashlib.sha256(x.samples).hexdigest()
   same=aa.width==bb.width and aa.height==bb.height and h(aa)==h(bb)
   assert same, (left,i+1)
   rows.append(dict(page=i+1,identical_pixels=True,reference_raster_sha256=h(aa),rebuilt_raster_sha256=h(bb)))
  return rows

def main():
 out=DELIVERY;manifest=read(out/'MANIFEST.json')
 for name,item in manifest['files'].items():assert digest(out/name)==item['sha256'],name
 archive=out/'aegiskv-aligned-paper-source.zip'
 target=ARTIFACTS/'source-bundle-check'
 target.mkdir(parents=True,exist_ok=True)
 with zipfile.ZipFile(archive) as z:
  assert z.testzip() is None
  for n in z.namelist():assert not n.startswith('/') and '..' not in Path(n).parts
  z.extractall(target)
 paper=target/'aegiskv-paper/benchmark/AegisKV/paper'
  # Extracted tree has the same repository-relative tool and input layout.
 command=['sh','build.sh']
 log=target/'source-bundle-build.log'
 overrides={}
 with log.open('w') as f:subprocess.run(command,cwd=paper,env={**os.environ,**overrides},stdout=f,stderr=subprocess.STDOUT,check=True)
 pages=identical_pages(PAPER/'main.pdf',paper/'main.pdf')
 # Regenerate all figures from the extracted portable inputs, without campaign
 # access or inference. The official Draw.io exporter is installed locally.
 figure_log=target/'figure-rebuild.log'
 with figure_log.open('w') as f:
  for name in ('render_submission_figures.py','build_submission_diagrams.py'):
   subprocess.run([sys.executable,str(paper.parent/'experiments/scripts/paper'/name)],cwd=paper,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'},stdout=f,stderr=subprocess.STDOUT,check=True)
 figures={stem:identical_pages(PAPER/'figures'/f'{stem}.pdf',paper/'figures'/f'{stem}.pdf') for stem in FIGURES}
 count=0
 with tarfile.open(out/'aegiskv-aligned-simulation-source.tar.gz') as z:
  snapshot=json.load(z.extractfile('aegiskv-simulation/source-v2/SOURCE_SNAPSHOT.json'))
  for n,h in snapshot['files'].items():
   actual=hashlib.file_digest(z.extractfile('aegiskv-simulation/source-v2/'+n),'sha256').hexdigest()
   assert actual==h,n
   count+=1
 result=dict(schema='moonkvsim.paper_source_build.v2',status='PASS',archive_crc='PASS',
  source_zip_sha256=digest(archive),reference_pdf_sha256=digest(PAPER/'main.pdf'),rebuilt_pdf_sha256=digest(paper/'main.pdf'),
  working_directory=str(paper.relative_to(ROOT)),command=command,environment_overrides=overrides,
  build_log=str(log.relative_to(ROOT)),build_log_sha256=digest(log),
  figure_build_log=str(figure_log.relative_to(ROOT)),figure_build_log_sha256=digest(figure_log),
  pages=pages,figures=figures,simulation_source_files_verified=count,raster_scale=1.5,
  pdf_binary_equality_required=False,pdf_binary_note='Timestamps and identifiers can differ; all page and figure pixels must match.')
 (out/'source-build-check.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
 print(json.dumps(dict(status='PASS',paper_pages=len(pages),regenerated_figures=len(figures),frozen_source_files=count)))
if __name__=='__main__':main()
