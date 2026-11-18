#!/usr/bin/env python3
"""Build the supplemental bibliography, CSV, and index snippets from snapshots.

Does not rewrite RELATED_WORKS.md or any manuscript source. Downloaded arXiv
versions are cited as preprints unless formal publication metadata was checked;
acceptance claims alone are retained only in the accompanying report.
"""
import csv
import json
from pathlib import Path
from urllib.parse import quote

BASE = Path(__file__).resolve().parent


def main():
    rows = json.loads((BASE / 'SOURCES.json').read_text())
    annotations = json.loads((BASE / 'ANNOTATIONS.json').read_text())
    checks = json.loads((BASE / 'PUBLISHER_CHECKS.json').read_text())
    w = next(c['summary'] for c in checks if c['key'] == 'wasma-crossref' and c['ok'])
    snippets = {}
    refs = []
    fields = ['key', 'title', 'authors', 'first_posted', 'version_date', 'arxiv_id',
              'arxiv_version', 'publication_status', 'priority', 'theme', 'summary',
              'relation_to_current_aegiskv', 'evidence_boundary', 'consensus_doi', 'publication_doi',
              'consensus_search', 'consensus_rank', 'consensus_url', 'primary_url',
              'local_pdf', 'pages', 'pdf_sha256', 'review_scope']
    with (BASE / 'LITERATURE.csv').open('w', newline='') as out:
        writer = csv.DictWriter(out, fieldnames=fields)
        writer.writeheader()
        for i, r in enumerate(rows, 1):
            a = annotations[r['key']]
            meta = r.get('primary_metadata', {})
            title = r.get('canonical_title', r['title'])
            author_list = r.get('verified_pdf_author_order', meta.get('citation_author', []))
            if r['key'] == 'wasma':
                author_list = [f"{x['family']}, {x['given']}" for x in w['author']]
            authors = ' and '.join(author_list)
            arxiv = r.get('arxiv_id')
            version = r.get('arxiv_version')
            primary = r.get('primary_url', 'https://doi.org/' + r['doi'])
            local = r.get('local_pdf', '')
            review = 'primary abstract, bibliographic page and first two PDF pages; not a full reproduction' if local else 'Consensus abstract and Crossref metadata; no full-text review'
            writer.writerow(dict(zip(fields, [
                r['key'], title, authors, '; '.join(meta.get('citation_date', [])),
                '; '.join(meta.get('citation_online_date', [])), arxiv or '',
                version or '', a['status'], a['priority'], a['theme'], a['summary'],
                a['relation'], a['boundary'], r.get('doi', ''), r.get('publication_doi', ''), r['search'],
                r['reference'], r['consensus_url'], primary, local,
                r.get('pages', ''), r.get('pdf_sha256', ''), review
            ])))
            if local:
                snippets[r['key']] = (
                    f"#### [{title}]({quote(local, safe='/')})\n"
                    f"- 身份：{a['status']}；本地版本 arXiv:{arxiv}v{version}。\n"
                    f"- 简介：{a['summary']}\n"
                    f"- 与 AegisKV 的关系：{a['relation']} {a['boundary']}\n"
                    f"- 来源：[原始页面]({primary})；[Consensus]({r['consensus_url']})"
                    f"（检索 {r['search']}，结果 [{r['reference']}]）；版本/哈希见本次增补目录。\n"
                )
                year = meta.get('citation_date', [''])[0][:4]
                bib_url = f'https://arxiv.org/abs/{arxiv}v{version}'
                refs.append(
                    f"@misc{{aegis_survey_{r['key']},\n"
                    f"  title = {{{{{title}}}}},\n"
                    f"  author = {{{authors}}},\n"
                    f"  year = {{{year}}},\n"
                    f"  archivePrefix = {{arXiv}},\n"
                    f"  eprint = {{{arxiv}}},\n"
                    f"  doi = {{10.48550/arXiv.{arxiv}}},\n"
                    f"  url = {{{bib_url}}},\n"
                    f"  urldate = {{2026-10-03}},\n"
                    f"  note = {{Downloaded arXiv version {version}; see the accompanying report for separately checked publication status}}\n"
                    f"}}\n"
                )
            label = title
            refs_line = (f"[{i}] [{label}]({r['consensus_url']}) — "
                         f"{authors or r['consensus_metadata'].split(',')[0]}；{a['status']}；"
                         f"[原始来源]({primary})")
            if local:
                refs_line += f"；[本地 PDF](../{quote(local, safe='/')})"
            refs_line += f"。Consensus 检索 {r['search']} 的结果 [{r['reference']}]。"
            (BASE / 'REFERENCE_LINES.txt').parent.mkdir(exist_ok=True)
            # Accumulate stable report-local references, independent of per-query ranks.
            snippets[f'reference_{i}'] = refs_line
    # Replace the provisional OrbitFlow preprint entry with verified publication data.
    orbit = next(c['summary'] for c in checks if c['key'] == 'orbitflow-crossref' and c['ok'])
    orbit_authors = ' and '.join(f"{x['family']}, {x['given']}" for x in orbit['author'])
    orbit_i = next(i for i, r in enumerate(rows) if r['key'] == 'orbitflow')
    refs[orbit_i] = (
        '@article{aegis_survey_orbitflow,\n'
        f"  title = {{{{{orbit['title'][0]}}}}},\n"
        f"  author = {{{orbit_authors}}},\n"
        f"  journal = {{{orbit['container-title'][0]}}},\n"
        '  year = {2026},\n'
        f"  volume = {{{orbit['volume']}}},\n"
        f"  number = {{{orbit['issue']}}},\n"
        f"  pages = {{{orbit['page'].replace('-', '--')}}},\n"
        f"  doi = {{{orbit['DOI']}}},\n"
        f"  url = {{{orbit['URL']}}},\n"
        '  urldate = {2026-10-03},\n'
        '  note = {Local PDF downloaded from arXiv:2601.10729v2; publication metadata verified via Crossref}\n'
        '}\n'
    )
    # Verified publisher metadata for the only reference-only record.
    authors = ' and '.join(f"{x['family']}, {x['given']}" for x in w['author'])
    refs.append(
        '@inproceedings{aegis_survey_wasma,\n'
        f"  title = {{{{{w['title'][0]}}}}},\n"
        f"  author = {{{authors}}},\n"
        f"  booktitle = {{{w['container-title'][0]}}},\n"
        '  year = {2026},\n'
        f"  doi = {{{w['DOI']}}},\n"
        f"  url = {{{w['URL']}}},\n"
        '  urldate = {2026-10-03},\n'
        '  note = {Publisher DOI metadata verified via Crossref; full text not acquired}\n'
        '}\n'
    )
    (BASE / 'REFERENCES.bib').write_text(
        '% Supplemental references only; does not replace paper/references.bib.\n'
        '% Conference acceptance claims in notes are not verified publication records.\n'
        + '\n'.join(refs)
    )
    (BASE / 'INDEX_SNIPPETS.json').write_text(json.dumps(snippets, ensure_ascii=False, indent=2) + '\n')
    (BASE / 'REFERENCE_LINES.txt').write_text('\n\n'.join(snippets[f'reference_{i}'] for i in range(1, len(rows) + 1)) + '\n')
    print(f'Built {len(rows)} CSV rows, {len(refs)} bibliography entries, and {sum(bool(r.get("local_pdf")) for r in rows)} index snippets')


if __name__ == '__main__':
    main()
