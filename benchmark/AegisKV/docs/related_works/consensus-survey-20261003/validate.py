#!/usr/bin/env python3
"""Offline validation of this literature update; no network access or PDF edits."""
from collections import Counter
import csv
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import urllib.parse

import fitz
from PIL import Image, ImageDraw
from pypdf import PdfReader

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalized(text):
    return set(re.findall(r'[a-z0-9]+', re.sub(r'-\s*\n', '', text.lower())))


def main():
    errors = []
    checks = {}
    before = json.loads((BASE / 'LOCAL_BEFORE.json').read_text())
    sources = json.loads((BASE / 'SOURCES.json').read_text())
    old_preserved = all((ROOT / x['path']).exists() and digest(ROOT / x['path']) == x['sha256'] for x in before)
    checks['old_pdf_files'] = len(before)
    checks['old_pdf_hashes_unchanged'] = old_preserved
    if not old_preserved:
        errors.append('An existing PDF was removed or its bytes changed')

    new_pdfs = [x for x in sources if x.get('local_pdf')]
    checks['new_pdf_files'] = len(new_pdfs)
    pdf_checks = []
    review = BASE / 'review'
    review.mkdir(exist_ok=True)
    thumbnails = []
    for row in new_pdfs:
        path = ROOT / row['local_pdf']
        result = {'key': row['key'], 'path': row['local_pdf'], 'errors': []}
        try:
            if digest(path) != row['pdf_sha256']:
                raise ValueError('Hash differs from download manifest')
            if row['local_pdf'] in {x['path'] for x in before}:
                raise ValueError('New PDF duplicates an original local path')
            reader = PdfReader(path, strict=True)
            if reader.is_encrypted:
                raise ValueError('Encrypted PDF')
            result['pypdf_strict_pages'] = len(reader.pages)
            for page in reader.pages:
                if float(page.mediabox.width) <= 0 or float(page.mediabox.height) <= 0:
                    raise ValueError('Invalid page box')
            fitz.TOOLS.mupdf_warnings(reset=True)
            with fitz.open(path) as doc:
                if len(doc) != row['pages'] or len(reader.pages) != len(doc):
                    raise ValueError('Page count mismatch')
                texts = [page.get_text() for page in doc]
                result['pages'] = len(doc)
                result['all_pages_text_extraction_completed'] = True
                result['pages_with_text'] = sum(bool(s.strip()) for s in texts)
                title = normalized(row['canonical_title'])
                overlap = len(title & normalized(texts[0])) / len(title)
                result['first_page_title_word_coverage'] = overlap
                if overlap < 0.8:
                    raise ValueError('First-page title does not match source title')
                expected_id = row['arxiv_id'] + 'v' + str(row['arxiv_version'])
                result['expected_arxiv_version'] = expected_id
                if expected_id in ''.join(texts[:2]):
                    result['version_identity_basis'] = 'embedded arXiv stamp'
                elif row.get('embedded_arxiv_stamp_expected') is False:
                    expected_url = f"https://arxiv.org/pdf/{expected_id}"
                    if row.get('pdf_url_requested') != expected_url or row.get('pdf_response_url') != expected_url:
                        raise ValueError('Missing watermark and version URL mismatch')
                    if row.get('publication_doi', 'NO_DOI') not in texts[0]:
                        raise ValueError('Missing watermark and formal first-page DOI mismatch')
                    result['version_identity_basis'] = 'version-fixed arXiv response URL plus matching title and verified first-page publication DOI; no embedded watermark'
                else:
                    raise ValueError('Expected arXiv version absent on first two pages')
                image_path = review / (row['key'] + '-page-1.png')
                doc[0].get_pixmap(dpi=140).save(image_path)
                result['rendered_page'] = 1
                result['render_dpi'] = 140
                result['render_backend'] = 'PyMuPDF'
                im = Image.open(image_path).convert('RGB')
                im.thumbnail((520, 710))
                tile = Image.new('RGB', (560, 760), 'white')
                tile.paste(im, ((560 - im.width) // 2, 35))
                ImageDraw.Draw(tile).text((15, 10), row['key'], fill='black')
                thumbnails.append(tile)
            result['mupdf_warnings'] = fitz.TOOLS.mupdf_warnings(reset=True)
            result['sha256'] = digest(path)
        except Exception as exc:
            result['errors'].append(f'{type(exc).__name__}: {exc}')
            errors.append(f"{row['key']}: {exc}")
        pdf_checks.append(result)
    for start in range(0, len(thumbnails), 6):
        tiles = thumbnails[start:start + 6]
        canvas = Image.new('RGB', (1120, 760 * ((len(tiles) + 1) // 2)), '#dedede')
        for i, tile in enumerate(tiles):
            canvas.paste(tile, ((i % 2) * 560, (i // 2) * 760))
        canvas.save(review / f'contact-{start // 6 + 1}.png')

    index = (ROOT / 'RELATED_WORKS.md').read_text()
    links = [urllib.parse.unquote(x) for x in re.findall(r'^#### \[[^\n]+\]\(([^)]+\.pdf)\)', index, re.M)]
    files = {str(p.relative_to(ROOT)) for p in ROOT.glob('[0-9][0-9][0-9][0-9]/*.pdf')}
    checks['index_pdf_entries'] = len(links)
    checks['year_directory_pdf_files'] = len(files)
    checks['missing_index_targets'] = sorted(set(links) - files)
    checks['unindexed_year_pdfs'] = sorted(files - set(links))
    checks['duplicate_index_links'] = [x for x, n in Counter(links).items() if n > 1]
    if any(checks[k] for k in ['missing_index_targets', 'unindexed_year_pdfs', 'duplicate_index_links']):
        errors.append('PDF index coverage mismatch')
    by_year = dict(sorted(Counter(p.split('/')[0] for p in files).items()))
    counts = {y: int(n) for y, n in re.findall(r'^## (\d{4})（(\d+) 篇）', index, re.M)}
    checks['year_counts'] = by_year
    if counts != by_year:
        errors.append('Declared year counts mismatch')
    themes = ['故障容错、检查点与恢复', 'Agentic Workflow 与工作流调度', 'KV Cache 管理、复用与分层存储', 'LLM Serving 调度、内存与执行系统', '资源管理、可靠性与外围参考']
    theme = None
    actual = Counter()
    for line in index.splitlines():
        if line.startswith('### ') and line[4:] in themes:
            theme = line[4:]
        if line.startswith('#### ['):
            actual[theme] += 1
    checks['theme_counts'] = dict(actual)
    expected = dict(zip(themes, [13, 25, 53, 13, 13]))
    if dict(actual) != expected:
        errors.append('Declared theme counts mismatch')

    changes = json.loads((BASE / 'INDEX_CHANGES.json').read_text())
    original = index
    for edit in reversed(changes['edits']):
        if original.count(edit['newText']) != 1:
            errors.append('Cannot reconstruct prior index from recorded edits')
            break
        original = original.replace(edit['newText'], edit['oldText'], 1)
    else:
        (BASE / 'RELATED_WORKS.before.md').write_text(original)
        checks['prior_index_reconstructed_sha256'] = hashlib.sha256(original.encode()).hexdigest()
        checks['prior_index_pdf_entries'] = len(re.findall(r'^#### \[', original, re.M))

    broken = []
    for doc in [ROOT / 'RELATED_WORKS.md', BASE / 'REPORT.md']:
        for target in re.findall(r'\]\(([^)]+)\)', doc.read_text()):
            if urllib.parse.urlsplit(target).scheme or target.startswith('#'):
                continue
            target = urllib.parse.unquote(target.split('#', 1)[0])
            if target and not (doc.parent / target).exists():
                broken.append({'document': str(doc.relative_to(ROOT)), 'target': target})
    checks['broken_document_links'] = broken
    if broken:
        errors.append('Broken document links')

    csv_rows = list(csv.DictReader((BASE / 'LITERATURE.csv').open()))
    bib = (BASE / 'REFERENCES.bib').read_text()
    bib_keys = re.findall(r'@\w+\{([^,]+),', bib)
    checks['csv_records'] = len(csv_rows)
    checks['bibtex_entries'] = len(bib_keys)
    if len(csv_rows) != 16 or len(bib_keys) != 16 or len(set(bib_keys)) != 16:
        errors.append('CSV or BibTeX record count mismatch')
    checks['bibtex_scope'] = 'brace/key/count sanity; not a LaTeX bibliography compilation'
    if bib.count('{') != bib.count('}'):
        errors.append('Unbalanced BibTeX braces')
    checks['publisher_sources_available'] = all(x['ok'] for x in json.loads((BASE / 'PUBLISHER_CHECKS.json').read_text()))
    checks['validation_scope'] = 'Strict pypdf parsing/page boxes and full PyMuPDF text extraction for 15 new PDFs; first-page rendering only. No complete visual/layout review, qpdf, or reproduction of research results.'
    report = {'validated_at_utc': dt.datetime.now(dt.timezone.utc).isoformat(), 'ok': not errors,
              'checks': checks, 'pdf_checks': pdf_checks, 'errors': errors}
    (BASE / 'VALIDATION.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'ok': report['ok'], 'checks': checks, 'errors': errors}, ensure_ascii=False, indent=2))
    raise SystemExit(bool(errors))


if __name__ == '__main__':
    main()
