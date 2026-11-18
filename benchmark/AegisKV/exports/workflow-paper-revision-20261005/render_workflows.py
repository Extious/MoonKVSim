#!/usr/bin/env python3
"""Export native editable diagrams and prepare 168-mm vector PDFs/previews."""
from pathlib import Path
import json
import os
import subprocess
import fitz

ROOT = Path(__file__).resolve().parent
CLI = '/home/comp/zhanzhao/.codex/skills/drawio/scripts/drawio-cli'


def render():
    src = ROOT / 'sources/application-workflows.drawio'
    contract = json.loads((src.parent / 'figure-contract.json').read_text())
    native = ROOT / 'native'
    review = ROOT / 'review'
    native.mkdir(exist_ok=True)
    review.mkdir(exist_ok=True)
    width = 168 / 25.4 * 72
    env = dict(os.environ, FONTCONFIG_FILE=str(ROOT / 'fontconfig.conf'))
    final_info = []
    with fitz.open() as combined:
        for number, panel in enumerate(contract['workflows'], 1):
            slug = panel['slug']
            for fmt in ('pdf', 'png', 'svg'):
                target = native / f'{slug}.drawio.{fmt}'
                args = [CLI, '-x', '-f', fmt, '-e', '-p', str(number), '-b', '0', '-o', str(target)]
                args += ['--crop'] if fmt == 'pdf' else []
                args += ['-s', '2'] if fmt == 'png' else []
                result = subprocess.run(args + [str(src)], env=env, capture_output=True, text=True, timeout=90)
                (native / f'{slug}-{fmt}.log').write_text(result.stdout + result.stderr)
                if result.returncode or not target.exists():
                    raise RuntimeError(f'Export failed for {slug}/{fmt}; see native log')
                print(f'native {slug}/{fmt}', flush=True)
            with fitz.open(native / f'{slug}.drawio.pdf') as doc:
                with fitz.open() as final:
                    page = final.new_page(width=width, height=doc[0].rect.height * width / doc[0].rect.width)
                    page.show_pdf_page(page.rect, doc, 0)
                    final.set_metadata({'title': panel['title'], 'subject': contract['evidence_level'],
                                        'creator': 'Draw.io native export; vector placement with PyMuPDF'})
                    final.save(ROOT / f'{slug}.pdf', garbage=4, deflate=True)
            with fitz.open(ROOT / f'{slug}.pdf') as doc:
                page = doc[0]
                combined.insert_pdf(doc)
                page.get_pixmap(matrix=fitz.Matrix(4, 4), alpha=False).save(ROOT / f'{slug}.png')
                page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False).save(review / f'{slug}-168mm-color.png')
                page.get_pixmap(matrix=fitz.Matrix(2, 2), colorspace=fitz.csGRAY, alpha=False).save(review / f'{slug}-168mm-gray.png')
                sizes = [s['size'] for block in page.get_text('dict')['blocks'] if 'lines' in block
                         for line in block['lines'] for s in line['spans'] if s['text'].strip()]
                final_info.append({'id': panel['id'], 'width_mm': page.rect.width / 72 * 25.4,
                                   'height_mm': page.rect.height / 72 * 25.4,
                                   'min_font_pt': min(sizes) if sizes else None})
        combined.set_metadata({'title': 'Two application workflow DAGs', 'subject': contract['evidence_level']})
        combined.save(ROOT / 'application-workflows.pdf', garbage=4, deflate=True)
    (review / 'pdf-metrics.json').write_text(json.dumps(final_info, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(final_info, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    render()
