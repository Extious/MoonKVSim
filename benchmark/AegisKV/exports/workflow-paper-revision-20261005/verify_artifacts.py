#!/usr/bin/env python3
"""Verify independent DAG dependencies, editable exports, manuscript evidence."""
from pathlib import Path
import importlib.util
import json
import hashlib
import re
import fitz
import xml.etree.ElementTree as ET
import urllib.parse
from PIL import Image

ROOT=Path(__file__).resolve().parent
AEGIS=ROOT.parents[1]
PAPER=AEGIS/'paper'
DOC=AEGIS/'docs/workflow-evaluation-20261005'

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def xml_structure(node):
    # Selected-page embeds need not preserve indentation outside the diagram.
    text=node.text if node.text and node.text.strip() else None
    return (node.tag,tuple(sorted(node.attrib.items())),text,
            tuple(xml_structure(child) for child in node))

def verify():
    src=ROOT/'sources/application-workflows.drawio'
    cfg=json.loads((src.parent/'figure-contract.json').read_text())
    deps=AEGIS/'docs/workload-decision-20261004/WORKFLOW_DEPENDENCIES.json'
    independent=json.loads(deps.read_text())['dependencies']
    assert sha(deps)==cfg['dependencies_source_sha256']
    results=[]
    for diagram,panel in zip(ET.parse(src).getroot().findall('diagram'),cfg['workflows']):
        cells=diagram.findall('./mxGraphModel/root/mxCell')
        nodes={c.get('id')[6:]:c for c in cells if c.get('id','').startswith('agent-')}
        drawn={(c.get('source')[6:],c.get('target')[6:]) for c in cells if c.get('edge')=='1'}
        required={(a,b) for b,ps in independent[panel['id']].items() for a in ps}
        assert set(nodes)==set(independent[panel['id']]) and drawn==required
        assert all(float(nodes[a].find('mxGeometry').get('x'))<float(nodes[b].find('mxGeometry').get('x')) for a,b in drawn)
        with Image.open(ROOT/'native'/f"{panel['slug']}.drawio.png") as img:
            payload=img.info.get('mxGraphModel',img.info.get('mxfile'))
            embedded=ET.fromstring(urllib.parse.unquote(payload)).find(f"diagram[@id='{panel['id']}']")
            assert xml_structure(embedded)==xml_structure(diagram)
        with fitz.open(ROOT/f"{panel['slug']}.pdf") as doc:
            assert abs(doc[0].rect.width/72*25.4-168)<.002
            text=re.sub(r'\s+','',doc[0].get_text())
            assert all(re.sub(r'\s+','',role) in text for role in panel['roles'].values())
        assert sha(ROOT/f"{panel['slug']}.pdf")==sha(PAPER/f"figures/{panel['slug']}.pdf")
        results.append({'application':panel['id'],'nodes':len(nodes),'edges':len(drawn),'exact_dependencies':True,'left_to_right':True,'editable_png_matches_selected_page':True})
    pdf_checks=[]
    paths=[*(ROOT/'schematics').glob('*.pdf'),ROOT/'research-report-workflow.pdf',ROOT/'repository-change-review-workflow.pdf',ROOT/'evaluation-protocol.pdf']
    for path in paths:
        with fitz.open(path) as d:
            page=d[0];spans=[s for b in page.get_text('dict')['blocks'] if 'lines' in b for l in b['lines'] for s in l['spans'] if s['text'].strip()]
            assert min(s['size'] for s in spans)>=9.9,(path,min(s['size'] for s in spans))
            # Check text ink bounds, including clipped labels at final export size.
            for s in spans:
                b=fitz.Rect(s['bbox'])
                assert b.x0>=-.2 and b.x1<=page.rect.width+.2 and b.y0>=-.2 and b.y1<=page.rect.height+.2,(path,s['text'],b)
            pdf_checks.append({'name':path.name,'width_mm':page.rect.width/72*25.4,'min_font_pt':min(s['size'] for s in spans),'raster_images':len(page.get_images())})
    with Image.open(ROOT/'native/evaluation-protocol.drawio.png') as img:
        payload=img.info.get('mxGraphModel',img.info.get('mxfile'))
        assert payload
        assert xml_structure(ET.fromstring(urllib.parse.unquote(payload)).find('diagram'))==xml_structure(ET.parse(ROOT/'sources/evaluation-protocol.drawio').getroot().find('diagram'))
    active='\n'.join(p.read_text().split(r'\iffalse')[0] for p in PAPER.glob('*.tex'))
    stale=['571.2','87.64','1{,}585.4','0.217','fig:agent_value}(b)','figures/agent_value_a.pdf','figures/kv_value.pdf']
    assert not any(x in active for x in stale)
    keys=set(re.findall(r'@\w+\{([^,]+)','\n'.join(p.read_text() for p in PAPER.glob('*.bib'))))
    cited={k.strip() for group in re.findall(r'\\cite\{([^}]+)\}',active) for k in group.split(',')}
    assert cited<=keys
    buildlog=AEGIS/'exports/latex-build/main.log'
    log=buildlog.read_text()
    assert not re.search(r'(^!|undefined|Overfull \\hbox)',log,re.M)
    specs=json.loads((DOC/'FIGURE_SPECS.json').read_text())
    assert len(specs['figures'])==11 and specs['performance_rows']==0
    campaign=json.loads((DOC/'CAMPAIGN.json').read_text())
    assert campaign['llm_calls']==campaign['physical_runs']==0 and not campaign['paper_result_claims_allowed']
    manifest=[{'path':str(p.relative_to(AEGIS)),'sha256':sha(p)} for p in [*(PAPER.glob('*.tex')),*(PAPER.glob('*.bib')),PAPER/'main.pdf',src,ROOT/'sources/evaluation-protocol.drawio',*(DOC.glob('*.md')),*(DOC.glob('*.json'))]]
    (ROOT/'DELIVERY_MANIFEST.json').write_text(json.dumps(manifest,indent=2)+'\n')
    report={'status':'PASS_STATIC_AND_COMPILE_PENDING_VISUAL_REVIEW','dag_checks':results,'pdf_checks':pdf_checks,
            'paper_pages':len(fitz.open(PAPER/'main.pdf')),'new_llm_calls':0,'new_physical_runs':0,
            'evidence':'application designs and illustrative mechanisms; measured panels await new traces',
            'compile_method':'project build_paper.sh; compile_latex_document not exposed in this session',
            'historical_lessons_limit':'Existing record fingerprint mismatch blocks global append; scoped fixes retained in this export.'}
    (ROOT/'FIGURE_REVIEW.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))

if __name__=='__main__':verify()
