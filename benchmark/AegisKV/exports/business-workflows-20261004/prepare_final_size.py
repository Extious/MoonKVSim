#!/usr/bin/env python3
"""Prepare 168 mm vector figures and matching color/grayscale previews."""
from pathlib import Path
import fitz


def prepare():
    root = Path(__file__).resolve().parent
    review = root / 'review'
    review.mkdir(exist_ok=True)
    width = 168 / 25.4 * 72
    for language in ('zh', 'en'):
        name = f'business-workflows-{language}'
        with fitz.open(root / f'{name}.drawio.pdf') as source:
            native = source[0]
            with fitz.open() as final:
                page = final.new_page(width=width, height=native.rect.height * width / native.rect.width)
                page.show_pdf_page(page.rect, source, 0)
                final.set_metadata({'title': f'Business workflow dependencies ({language})',
                                    'subject': 'Constructed application DAGs; no measured execution overlap',
                                    'creator': 'Draw.io; vector placement with PyMuPDF'})
                final.save(root / f'{name}.pdf', garbage=4, deflate=True)
        with fitz.open(root / f'{name}.pdf') as final:
            page = final[0]
            page.get_pixmap(matrix=fitz.Matrix(4, 4), alpha=False).save(root / f'{name}.png')
            page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False).save(review / f'{name}-168mm-color.png')
            page.get_pixmap(matrix=fitz.Matrix(2, 2), colorspace=fitz.csGRAY, alpha=False).save(review / f'{name}-168mm-gray.png')
        print(f'{name}: 168 mm vector PDF and previews')


if __name__ == '__main__':
    prepare()
