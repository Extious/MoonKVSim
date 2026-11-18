#!/usr/bin/env python3
"""Check the delivered comments/images and render their intended placement."""
from pathlib import Path
from zipfile import ZipFile
from datetime import datetime, timezone
from urllib.parse import unquote
import hashlib
import importlib.util
import json
import xml.etree.ElementTree as E
import fitz
from PIL import Image
import docx

HERE = Path(__file__).resolve().parent
PATENT = HERE.parents[1]
FIGURES = PATENT / 'figures/instances-1-2'
spec = importlib.util.spec_from_file_location('builder', HERE / 'build_comments.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)
sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
audit = json.loads((HERE / 'AUDIT.json').read_text())
assert sha(builder.SOURCE) == audit['source_sha256']
assert sha(builder.OUTPUT) == audit['output_sha256']
entries = json.loads((HERE / 'comments.json').read_text())['comments']
rent_checks = json.loads((HERE / 'RENT_CHECKS.json').read_text())
assert rent_checks['status'] == 'PASS'
assert rent_checks['source_sha256'] == sha(FIGURES / 'figure-3-slacklandlord.drawio')
assert rent_checks['comment_spec_sha256'] == sha(HERE / 'comments.json')
with ZipFile(builder.SOURCE) as z:
    original = {name: z.read(name) for name in z.namelist()}
checks = builder.validate(original, entries, builder.OUTPUT)
assert checks == audit['checks']
document = docx.Document(builder.OUTPUT)
assert len(document.comments) == 20
assert {c.author for c in document.comments} == {'zhaozhan'}
assert {c.initials for c in document.comments} == {'ZZ'}
assert len(document.inline_shapes) == 4 and len(document.tables) == 3

plate = fitz.open()
mm = 72 / 25.4
reports = []
roles = {}
for item in builder.FIGURE_UPDATES:
    graph = E.parse(FIGURES / (item['stem'] + '.drawio'))
    labels = '\n'.join(c.get('value','') for c in graph.findall('.//mxCell'))
    if item['paragraph'] == 115:
        assert all(token not in labels for token in ['Credit', 'H_x', 'c_{u,x}', 'L^{', '结算', '续租'])
        assert 'G_{a,x}=' in labels and 'P_{a,x}=G_{a,x}/b_x' in labels
        roles[item['stem']] = 'Benefit mapping only'
    else:
        assert 'T_a(' not in labels and 's_a' not in labels
        assert all(token in labels for token in ['Credit', 'c_{u,x}', 'H_y', 'H_x', 'L^{', '附图 2'])
        cells = {c.get('id'): c for c in graph.findall('.//mxCell')}
        edges = {(c.get('source'), c.get('target')) for c in cells.values() if c.get('edge') == '1'}
        assert ('input', 'resident') in edges, 'backup state must be checked before granting credit'
        assert {b for a, b in edges if a == 'resident'} == {'settle', 'initialize'}
        assert ('settle', 'renew') in edges and not any(a == 'renew' for a, b in edges)
        assert ('initialize', 'trial') in edges
        assert '\\(x\\notin Q\\)' in cells['initialize'].get('value', '')
        assert '已提交备份' in cells['symbols'].get('value', '')
        roles[item['stem']] = 'Credit and rental decisions; consumes G from figure 2'
for item in builder.FIGURE_UPDATES:
    stem = item['stem']
    png, pdf, source = [FIGURES / (stem + suffix) for suffix in ['.drawio.png', '.drawio.pdf', '.drawio']]
    with Image.open(png) as im:
        iw, ih = im.size
        embedded = im.info.get('mxGraphModel') or im.info.get('mxfile')
        assert embedded, 'native PNG lacks embedded Draw.io source'
        assert unquote(embedded) == source.read_text(), 'native PNG embeds a different source revision'
    native = fitz.open(pdf)
    assert len(native) == 1
    page = native[0]
    assert not page.get_images(), 'native PDF should contain vector diagram content'
    scale = 168 * mm / page.rect.width
    spans = [s for block in page.get_text('dict')['blocks'] if 'lines' in block
             for line in block['lines'] for s in line['spans'] if s['text'].strip()]
    min_pt = min(s['size'] * scale for s in spans)
    assert min_pt >= 7.5, (stem, min_pt)
    assert all(fitz.Rect(s['bbox']).intersects(page.rect) for s in spans)
    page.get_pixmap(matrix=fitz.Matrix(scale*150/72,scale*150/72),alpha=False).save(str(HERE/(stem+'-pdf-review.png')))
    p = plate.new_page(width=210*mm,height=297*mm)
    x, y, w = (210-168)*mm/2, 25.4*mm, 168*mm
    h = w*ih/iw
    p.insert_image(fitz.Rect(x,y,x+w,y+h),filename=str(png))
    p.insert_font(fontname='NotoCJK',fontfile='/home/comp/zhanzhao/.local/share/fonts/noto-cjk/NotoSansCJKsc-Regular.otf')
    remaining = p.insert_textbox(fitz.Rect(19.05*mm,y+h+3*mm,190.95*mm,271.6*mm),
                                item['caption'],fontname='NotoCJK',fontsize=10.5,align=1)
    assert remaining >= 0
    reports.append({'stem':stem,'source_sha256':sha(source),'png_sha256':sha(png),'pdf_sha256':sha(pdf),
                    'placed_width_mm':168,'placed_height_mm':h/mm,'effective_png_ppi':iw/(168/25.4),
                    'native_pdf_min_text_pt_at_placement':min_pt,'native_pdf_pages':1,
                    'native_pdf_raster_images':0,'embedded_png_drawio_source':True})
plate.save(str(HERE/'figures-at-word-size.pdf'),garbage=4,deflate=True)
plate.close()
with fitz.open(HERE/'figures-at-word-size.pdf') as reloaded:
    for page, item in zip(reloaded,builder.FIGURE_UPDATES):
        page.get_pixmap(matrix=fitz.Matrix(150/72,150/72),alpha=False).save(str(HERE/(item['stem']+'-placement.png')))

audit['independent_reader_check'] = {'library':'python-docx '+docx.__version__,'native_comments_read':20,
                                    'authors':['zhaozhan'],'initials':['ZZ'],'inline_images':4,'tables':3,'status':'PASS'}
audit['figure_placement_review_pdf'] = str(HERE/'figures-at-word-size.pdf')
audit['figure_placement_review_scope'] = 'Exact embedded PNGs at DOCX dimensions on A4; not a full Word/WPS render.'
audit['figure_role_separation_check'] = roles
audit['rent_semantic_checks'] = {'path': str(HERE / 'RENT_CHECKS.json'),
                                 'sha256': sha(HERE / 'RENT_CHECKS.json'),
                                 'status': 'PASS', 'evidence_class': rent_checks['evidence_class']}
(HERE/'AUDIT.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n')
report = {'created_utc':datetime.now(timezone.utc).isoformat(timespec='seconds'),
          'evidence_class':'design_schematic','figures':reports,'docx_sha256':sha(builder.OUTPUT),
          'source_docx_unchanged':True,'native_package_and_placement_checks':'PASS',
          'visual_review':'pending final inspection','word_wps_full_document_render':'UNVERIFIED'}
(FIGURES/'FIGURE_REVIEW.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(report,ensure_ascii=False,indent=2))
