from pathlib import Path
import hashlib,json,re,fitz
root=Path('/home/comp/zhanzhao/MoonKVSim');out=root/'output/pdf/aegiskv-external-review-revision-20260919';paper=root/'benchmark/AegisKV/paper'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
log=(paper/'build/main.log').read_text(errors='replace');aux=(paper/'build/main.aux').read_text(errors='replace')
cited=set(k.strip() for row in re.findall(r'\\citation\{([^}]+)\}',aux) for k in row.split(','))
defined=set(re.findall(r'\\bibcite\{([^}]+)\}',aux))
allkeys=[]
for f in [paper/'references.bib',paper/'sections/background_and_motivation.bib']:
 allkeys.extend(re.findall(r'(?mi)^\s*@\w+\s*\{\s*([^,]+),',f.read_text()))
doc=fitz.open(out/'main.pdf');renders=out/'final-renders';renders.mkdir(exist_ok=True)
rows=[];clips={};outside=[]
for i,p in enumerate(doc):
 text=p.get_text();(renders/f'page-{i+1:02}.txt').write_text(text)
 p.get_pixmap(matrix=fitz.Matrix(1.5,1.5)).save(renders/f'page-{i+1:02}.png')
 row={'page':i+1,'contains_fig3':'Figure 3.' in text,'contains_fig4':'AegisKV overview.' in text,'contains_fig5':'Figure 5.' in text,'algorithms':re.findall(r'Algorithm [123]:[^\n]*',text)}
 for b in p.get_text('dict')['blocks']:
  for line in b.get('lines',[]):
   for s in line['spans']:
    if s['text'].strip() and not p.rect.contains(fitz.Rect(s['bbox'])):outside.append({'page':i+1,'text':s['text'],'bbox':s['bbox']})
 for key,marker,files in [
  ('figure3','Figure 3.', ['figures/agent-time-literature/agent-predictability-panel.pdf','figures/design-insights/sparse-attention-survey.pdf','figures/design-insights/retry-kv-prediction.pdf']),
  ('figure4','AegisKV overview.', ['figures/system-overview-v11.drawio.pdf']),
  ('figure5','Figure 5.', ['figures/design-single/design-layer-pipeline.pdf'])]:
  if marker not in text:continue
  fonts=set()
  for f in files:
   with fitz.open(paper/f) as sdoc:
    for b in sdoc[0].get_text('dict')['blocks']:
     for ln in b.get('lines',[]):
      fonts.update(s['font'] for s in ln['spans'])
  spans=[s for b in p.get_text('dict')['blocks'] for ln in b.get('lines',[]) for s in ln['spans'] if s['font'] in fonts and s['text'].strip()]
  # Figure fonts differ from the document's LinuxLibertineT body fonts.
  if spans:
   bbox=fitz.Rect(spans[0]['bbox'])
   for s in spans[1:]:bbox|=fitz.Rect(s['bbox'])
   clips[key]={'page':i+1,'min_pdf_pt':min(s['size']for s in spans),'max_pdf_pt':max(s['size']for s in spans),'font_names':sorted(fonts),'spans':len(spans),'text_bbox':list(bbox)}
   clip=fitz.Rect(bbox.x0-7,bbox.y0-7,bbox.x1+7,bbox.y1+12)&p.rect
   p.get_pixmap(matrix=fitz.Matrix(1.5,1.5),clip=clip).save(renders/f'{key}-color.png')
   p.get_pixmap(matrix=fitz.Matrix(1.5,1.5),clip=clip,colorspace=fitz.csGRAY).save(renders/f'{key}-gray.png')
 rows.append(row)
base=root/'output/pdf/aegiskv-external-review-baseline-20260919T041842Z'
initial=json.loads((out/'INITIAL_STATE.json').read_text())
figfiles=['figures/system-overview-v11.drawio','figures/system-overview-v11.drawio.pdf','figures/system-overview-v11.drawio.png','figures/agent-time-literature/agent-predictability-panel.pdf','figures/design-insights/sparse-attention-survey.pdf','figures/design-insights/retry-kv-prediction.pdf','figures/design-single/design-layer-pipeline.pdf']
res={'evidence_scope':'paper contracts, synthetic CPU arithmetic, compilation and rendered-layout inspection; no new runtime/benchmark validation',
 'main_pdf_sha256':sha(out/'main.pdf'),'shared_main_pdf_matches':sha(out/'main.pdf')==sha(paper/'main.pdf'),'bytes':(out/'main.pdf').stat().st_size,'page_count':len(doc),
 'main_tex_unchanged':sha(paper/'main.tex')==initial['main_tex_sha256'],'frozen_baseline_pdf_unchanged':sha(base/'AegisKV-review-baseline.pdf')==initial['main_pdf_sha256'],
 'source_stability':json.loads((out/'FINAL_SOURCE_STABILITY.json').read_text()),
 'citations':{'cited':len(cited),'defined':len(defined),'unresolved':sorted(cited-defined),'duplicate_bib_keys':sorted({x for x in allkeys if allkeys.count(x)>1})},
 'warnings':{'overfull':re.findall(r'^Overfull[^\n]*',log,re.M),'underfull':re.findall(r'^Underfull[^\n]*',log,re.M),'undefined':re.findall(r'^.*undefined.*$',log,re.M),'other_warning_lines':re.findall(r'^.*Warning.*$',log,re.M)},
 'text_outside_page':outside,'embedded_figures':clips,'pages':rows,
 'figure_source_stable_against_frozen':{f:sha(paper/f)==sha(base/'source/paper'/f)for f in figfiles},
 'cpu_checks':{n:json.loads((out/n).read_text())['passed']for n in ['DEPTH_SCORE_CHECKS.json','POLICY_BOUNDARY_CHECKS.json']}}
(out/'REVISION_VALIDATION.json').write_text(json.dumps(res,indent=2,ensure_ascii=False)+'\n')
(out/'main.pdf.sha256').write_text(res['main_pdf_sha256']+'  main.pdf\n')
print(json.dumps({k:v for k,v in res.items() if k not in ['pages','figure_source_stable_against_frozen']},indent=2,ensure_ascii=False))
