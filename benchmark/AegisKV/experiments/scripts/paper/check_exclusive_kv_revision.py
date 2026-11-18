#!/usr/bin/env python3
"""Document/figure arithmetic audit; not a serving-controller implementation test."""
from pathlib import Path
import hashlib,json,re,math,xml.etree.ElementTree as E
import pymupdf as fitz
ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'exports/exclusive-kv-master-20260921'
PAPER=ROOT/'paper'
checks=[]
def check(name,condition,detail=''):
    if not condition: raise AssertionError(name+': '+str(detail))
    checks.append(dict(name=name,result='pass',detail=detail))
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
tex=(PAPER/'system_design.tex').read_text();md=(PAPER/'paper_draft.md').read_text()
subtitles=['Workflow-aware Request Value','Prefix and Block Value',
'Three-Tier Placement and Peer Acceleration','Renewable Credit and Online Management']
a=tex.index('\\subsection{KV Master:');b=tex.index('\\subsection{Adapter:',a)
check('four ordered KV Master subsections',re.findall(r'\\subsubsection\{([^}]+)\}',tex[a:b])==subtitles)
check('markdown uses matching order',re.findall(r'^#### 3\.5\.\d (.+)$',md,re.M)==subtitles)
check('six design sections',len(re.findall(r'\\subsection\{',tex))==6)
check('four root TeX files',sorted(p.name for p in PAPER.glob('*.tex'))==['abstract.tex','background_and_motivation.tex','main.tex','system_design.tex'])
for tag in ['alg:workflow-tracker','alg:adapter']:
    before=(OUT/'before/paper/system_design.tex').read_text()
    def body(s):
        start=s.index('\\refstepcounter{designalgorithm}\\label{'+tag+'}')
        return s[start:s.index('\\end{minipage}',start)]
    check(tag+' unchanged',body(before)==body(tex))
for token in ['462.96','506.39','512.67','477.86','466.76']:
    check('negative result retained '+token,token in md and token in (PAPER/'main.tex').read_text())
changed=[]
for old in (OUT/'before/paper').rglob('*'):
    if old.is_file():
        rel=old.relative_to(OUT/'before/paper');new=PAPER/rel
        check('retained file '+str(rel),new.exists())
        if sha(old)!=sha(new): changed.append(str(rel))
allowedfig={'system-overview','sparse-recovery','renewable-credit','recovery-pipeline'}
check('unrelated figures unchanged',all(Path(p).stem in allowedfig for p in changed if p.startswith('figures/')),changed)
# Verify the constructed ownership map, not just its caption.
layout=json.loads((OUT/'data/exclusive-layout.json').read_text())
rows=layout['owners'];counts={x:sum(r.count(x) for r in rows) for x in 'PDS'}
check('12 cells have one tier each',len(rows)==3 and all(len(r)==4 and set(r)<=set('PDS') for r in rows) and sum(counts.values())==12,counts)
check('L/K match grid',layout['peer_layers']==2 and [r.count('P') for r in rows]==[2,1,0])
check('demand paths match ownership',[rows[0][b] for b in layout['layer1_demand']]==list('PDS'))
for name in ['system-overview','sparse-recovery','renewable-credit']:
    E.parse(OUT/'sources'/f'{name}.drawio')
    check('published native exports '+name,sha(PAPER/'figures'/f'{name}.pdf')==sha(OUT/'figures'/f'{name}.pdf') and sha(PAPER/'figures/preview'/f'{name}.png')==sha(OUT/'figures'/f'{name}.png'))
# Independent arithmetic for the forward-prefix example and lower-tier ledger.
penalty=[max(0,t-6) for t in [12,7,5]]
check('prefix increments telescope',[penalty[i]-penalty[i+1] for i in [0,1]]==[5,1] and sum([5,1])==penalty[0]-penalty[-1])
grants=[3.,2.];paid=[2*g/sum(grants) for g in grants]
check('proportional paid rent conserved',math.isclose(sum(paid),2.))
check('value update keeps paid rent',[round(g-d,2) for g,d in zip([4.,2.],paid)]==[2.8,1.2])
check('A use does not renew B',round(sum([4.,2.-paid[1]]),2)==5.2)
# Frozen analysis must retain its original inputs/timings; only residency accounting changes.
pipeline=json.loads((OUT/'data/pipeline-provenance.json').read_text())
for file,expected in pipeline['source_sha256'].items():
    check('frozen analysis input '+file,sha(ROOT/file)==expected)
for file,expected in pipeline['preserved_source_hashes'].items():
    check('original calibration input '+file,sha(ROOT.parents[1]/file)==expected)
for case in pipeline['cases']:
    check('equal unique coverage case '+str(case['case']),math.isclose(case['peer_mib']+case['dram_mib']+case['storage_mib'],1024))
check('exclusive Peer offsets DRAM',math.isclose(pipeline['cases'][3]['dram_mib'],1024-pipeline['cases'][3]['peer_mib']))
check('pipeline remains analysis',pipeline['new_physical_runs']==0)
# Native PDF and actual manuscript checks.
log=(ROOT/'exports/latex-build/main.log').read_text(errors='replace')
check('no overflow or unresolved references',not any(x in log for x in ['Overfull','undefined references','undefined citations','multiply defined']))
doc=fitz.open(PAPER/'main.pdf');text='\n'.join(p.get_text() for p in doc)
for title in subtitles:
    check('PDF contains heading '+title,title in text)
font_report=json.loads((OUT/'review/font-audit.json').read_text())
check('all changed figures meet placed 10pt',all(r['min_font_pt']>=10 and not r['has_replacement_glyph'] for r in font_report))
record={'scope':'source synchronization, frozen figure arithmetic and rendered-PDF metadata; not controller tests or performance evidence',
'checks':checks,'changed_paper_files':changed,'pdf_pages':len(doc),'pdf_sha256':sha(PAPER/'main.pdf'),
'new_physical_runs':0,'sources':{str(p.relative_to(ROOT)):sha(p) for p in [Path(__file__).resolve(),ROOT/'experiments/scripts/paper/build_exclusive_kv_figures.py',ROOT/'experiments/scripts/paper/render_exclusive_pipeline.py']}}
(OUT/'REVISION_CHECKS.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'checks':len(checks),'pages':len(doc),'changed_paper_files':changed,'pdf_sha256':record['pdf_sha256']},ensure_ascii=False,indent=2))
