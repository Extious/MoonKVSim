#!/usr/bin/env python3
"""Export the current native diagram; legacy drawing code is archived."""
import argparse, hashlib, json, subprocess
from pathlib import Path
from urllib.parse import quote, unquote
import xml.etree.ElementTree as ET

OUT = Path(__file__).resolve().parent
STEM = 'algorithm-2-patent-revised'
SOURCE = OUT / (STEM + '.drawio')
CLI = '/home/comp/zhanzhao/.codex/skills/drawio/scripts/drawio-cli'
digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()

def export():
    import pymupdf
    from PIL import Image
    record = json.loads((OUT/'MANIFEST.json').read_text())
    assert digest(SOURCE) == record['output_sha256'][SOURCE.name]
    page_names = [(d.get('id'), d.get('name')) for d in ET.parse(SOURCE).getroot().findall('diagram')]
    outputs = [SOURCE]
    pdf = Path(str(SOURCE)+'.pdf')
    subprocess.run([CLI, '-x', '-f', 'pdf', '-e', '-b', '0', '-a', '--crop',
                    '-o', str(pdf), str(SOURCE)], check=True)
    outputs.append(pdf)
    for i, (key, _) in enumerate(page_names, 1):
        dest = OUT/f'{STEM}-{key}.drawio.png'
        subprocess.run([CLI, '-x', '-f', 'png', '-e', '-b', '0', '-s', '1',
                        '-p', str(i), '-o', str(dest), str(SOURCE)], check=True)
        outputs.append(dest)
        print(f'Native page {i}/{len(page_names)} exported: {key}', flush=True)
    preview = OUT/(STEM+'.drawio.png')
    preview.write_bytes((OUT/f'{STEM}-flow.drawio.png').read_bytes())
    outputs.append(preview)
    with pymupdf.open(pdf) as doc:
        assert len(doc) == len(page_names)
        meta = {k: v for k, v in doc.metadata.items() if k not in {'format', 'encryption'}}
        meta.update(title='SlackLandlord: unified request-driven KV rental management', subject=quote(SOURCE.read_text(), safe=''))
        doc.set_metadata(meta)
        doc.saveIncr()
        assert unquote(doc.metadata['subject']) == SOURCE.read_text()
        for n, (key, title) in enumerate(page_names):
            page = doc[n]
            assert page.get_text().strip()
            assert not any(token in page.get_text() for token in (r'\(', r'\)', r'\mathrm', r'\lambda', r'\sum'))
            for block in page.get_text('blocks'):
                assert page.rect.contains(pymupdf.Rect(block[:4])), (key, block)
            out = OUT/f'{STEM}-{key}.drawio.pdf'
            one = pymupdf.open()
            one.insert_pdf(doc, from_page=n, to_page=n)
            one.set_metadata({'title': title, 'subject': quote(SOURCE.read_text(), safe='')})
            one.save(out)
            one.close()
            outputs.append(out)
    source_pages = ET.parse(SOURCE).getroot().findall('diagram')
    for key, _ in page_names:
        with Image.open(OUT/f'{STEM}-{key}.drawio.png') as im:
            embedded = ET.fromstring(unquote(im.info['mxGraphModel']))
            restored = embedded.findall('diagram')
            assert len(restored) in (1, len(source_pages))
            wanted = {p.get('id'): p for p in source_pages}
            assert len(restored) != 1 or restored[0].get('id') == key
            for after in restored:
                before = wanted[after.get('id')]
                assert before.attrib == after.attrib
                assert [c.attrib for c in before.findall('.//mxCell')] == [c.attrib for c in after.findall('.//mxCell')]
    record['output_sha256'] = {p.name: digest(p) for p in outputs}
    record['export_checks'] = {'pdf_pages': len(page_names), 'pdf_embedded_source': 'PASS',
                               'png_embedded_cells_match_source': 'PASS', 'pdf_text_bounds': 'PASS',
                               'mathjax_without_literal_tex': 'PASS'}
    (OUT/'MANIFEST.json').write_text(json.dumps(record, ensure_ascii=False, indent=2)+'\n')
    print('Native exports and embedded-source checks passed.', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--export-only', action='store_true', required=True)
    parser.parse_args()
    export()
