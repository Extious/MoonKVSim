#!/usr/bin/env python3
"""Snapshot public primary sources and validate newly acquired literature PDFs.

Run from any working directory. Existing PDFs are never overwritten. Requires
installed PyMuPDF; no package installation or code from papers is performed.
Only SELECTION.json entries with an arXiv ID are downloaded. Publisher-only
leads remain reference-only unless independently obtained later.
"""
from __future__ import annotations

import concurrent.futures
import datetime as dt
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import urllib.request

import fitz

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.meta = {}
        self.text = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'meta' and attrs.get('name', '').startswith('citation_'):
            self.meta.setdefault(attrs['name'], []).append(attrs.get('content', ''))

    def handle_data(self, data):
        if data.strip():
            self.text.append(data.strip())


def fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'AegisKV-literature-review/1.0'})
    with urllib.request.urlopen(req, timeout=90) as response:
        return response.read(), response.url, response.headers.get('Content-Type', '')


def acquire(paper):
    row = dict(paper)
    row['retrieved_at_utc'] = dt.datetime.now(dt.timezone.utc).isoformat()
    row['errors'] = []
    if not paper.get('arxiv_id'):
        row['status'] = 'reference-only; primary source not downloaded'
        return row
    key = paper['key']
    try:
        url = f"https://arxiv.org/abs/{paper['arxiv_id']}"
        data, resolved, content_type = fetch(url)
        (BASE / 'sources' / f'{key}.html').write_bytes(data)
        page = Page()
        page.feed(data.decode('utf-8', 'replace'))
        row.update(primary_url=resolved, primary_metadata=page.meta,
                   primary_html_sha256=hashlib.sha256(data).hexdigest())
        if not page.meta.get('citation_title'):
            raise ValueError('No citation_title on primary page; refusing PDF acquisition')
        title = page.meta['citation_title'][0]
        text = '\n'.join(page.text)
        (BASE / 'sources' / f'{key}.txt').write_text(text + '\n')
        versions = re.findall(r'\[v(\d+)\]', text)
        version = max(map(int, versions)) if versions else None
        row['arxiv_version'] = version
        pdf_url = f"https://arxiv.org/pdf/{paper['arxiv_id']}" + (f'v{version}' if version else '')
        year = paper['arxiv_id'][:2]
        year = str(2000 + int(year))
        filename = re.sub(r'[/:*?"<>|]', ' - ', title)
        filename = re.sub(r'\s+', ' ', filename).strip() + '.pdf'
        destination = ROOT / year / filename
        destination.parent.mkdir(exist_ok=True)
        if destination.exists():
            pdf_data = destination.read_bytes()
            row['download_action'] = 'preserved existing file'
            row['pdf_response_url'] = None
        else:
            pdf_data, response_url, pdf_type = fetch(pdf_url)
            row['pdf_response_url'] = response_url
            row['pdf_content_type'] = pdf_type
            if not pdf_data.startswith(b'%PDF-'):
                raise ValueError(f'Not a PDF: {pdf_type}')
            # Validate before publishing to the year directory.
            with fitz.open(stream=pdf_data, filetype='pdf') as doc:
                if doc.is_encrypted or not doc.page_count:
                    raise ValueError('Encrypted or empty PDF')
                if not doc[0].get_text().strip():
                    raise ValueError('First page has no extractable text')
            with destination.open('xb') as out:
                out.write(pdf_data)
            row['download_action'] = 'downloaded new public PDF'
        with fitz.open(stream=pdf_data, filetype='pdf') as doc:
            first_pages = '\n\n'.join(doc[i].get_text() for i in range(min(2, len(doc))))
            (BASE / 'sources' / f'{key}-first-pages.txt').write_text(first_pages)
            row.update(pages=len(doc), pdf_metadata=doc.metadata,
                       pdf_arxiv_ids=sorted(set(re.findall(r'arXiv\s*:\s*(\d{4}\.\d{4,5}(?:v\d+)?)', first_pages, re.I))))
        row.update(status='primary page and public PDF acquired; content review separate',
                   canonical_title=title, pdf_url_requested=pdf_url,
                   local_pdf=str(destination.relative_to(ROOT)),
                   pdf_sha256=hashlib.sha256(pdf_data).hexdigest(), pdf_bytes=len(pdf_data))
    except Exception as exc:
        row['status'] = 'acquisition incomplete'
        row['errors'].append(f'{type(exc).__name__}: {exc}')
    return row


def main():
    (BASE / 'sources').mkdir(exist_ok=True)
    selection = json.loads((BASE / 'SELECTION.json').read_text())
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(acquire, selection))
    (BASE / 'SOURCES.json').write_text(json.dumps(results, ensure_ascii=False, indent=2) + '\n')
    for row in results:
        print(json.dumps({k: row.get(k) for k in ['key', 'status', 'arxiv_version', 'pages', 'canonical_title', 'errors']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
