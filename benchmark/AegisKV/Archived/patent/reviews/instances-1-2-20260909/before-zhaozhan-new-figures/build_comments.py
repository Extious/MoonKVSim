#!/usr/bin/env python3
"""Native Word comments, scoped to examples 1/2; all original prose/media preserved."""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZipFile
from lxml import etree

HERE = Path(__file__).resolve().parent
PATENT = HERE.parents[1]
REPO = PATENT.parents[3]
SOURCE = PATENT / 'AegisKV专利交底书-final-version.docx'
OUTPUT = PATENT / 'AegisKV专利交底书-实例一二批注版.docx'
AUDIT = HERE / 'AUDIT.json'
W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
M = 'http://schemas.openxmlformats.org/officeDocument/2006/math'
PKG = 'http://schemas.openxmlformats.org/package/2006/relationships'
CT = 'http://schemas.openxmlformats.org/package/2006/content-types'
NS = {'w': W, 'r': R, 'm': M,
      'a': 'http://schemas.openxmlformats.org/drawingml/2006/main'}
MODIFIED = {'word/document.xml', 'word/_rels/document.xml.rels', '[Content_Types].xml'}

def sha(data):
    return hashlib.sha256(data).hexdigest()

def wt(name):
    return '{' + W + '}' + name

def el(name, **attrs):
    return etree.Element(wt(name), {wt(k): v for k, v in attrs.items()})

def text(p):
    return ''.join(p.xpath('.//w:t/text() | .//m:t/text()', namespaces=NS))

def emit_run(p, value, *, bold=False, align=None, formula=False):
    if not value:
        return
    r, props = el('r'), el('rPr')
    font = 'Cambria' if formula else 'Arial'
    props.append(el('rFonts', ascii=font, hAnsi=font, eastAsia='宋体'))
    if bold:
        props.append(el('b'))
    props.append(el('sz', val='20'))
    if align:
        props.append(el('vertAlign', val=align))
    r.append(props)
    t = el('t')
    t.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')
    t.text = value
    r.append(t)
    p.append(r)

def formula(p, value, *, bold=False):
    cursor = 0
    for match in re.finditer(r'([_^])(?:\{([^{}]+)\}|([A-Za-z0-9]))', value):
        emit_run(p, value[cursor:match.start()], bold=bold, formula=True)
        emit_run(p, match.group(2) or match.group(3), bold=bold, formula=True,
                 align='subscript' if match.group(1) == '_' else 'superscript')
        cursor = match.end()
    emit_run(p, value[cursor:], bold=bold, formula=True)

def comment_paragraph(comment, value, *, bold=False):
    assert value.count('$') % 2 == 0
    p, props = el('p'), el('pPr')
    props.append(el('spacing', after='100', line='264', lineRule='auto'))
    p.append(props)
    for i, part in enumerate(value.split('$')):
        if i % 2:
            formula(p, part, bold=bold)
        else:
            emit_run(p, part, bold=bold)
    comment.append(p)

def xml(tree):
    return etree.tostring(tree, encoding='UTF-8', xml_declaration=True, standalone=True)

def validate(original, entries, path):
    with ZipFile(path) as z:
        assert z.testzip() is None
        assert set(z.namelist()) == set(original) | {'word/comments.xml'}
        updated = {name: z.read(name) for name in z.namelist()}
    for name, data in original.items():
        if name not in MODIFIED:
            assert updated[name] == data, ('unrelated part changed', name)
    for name, data in updated.items():
        if name.endswith(('.xml', '.rels')):
            etree.fromstring(data)
    doc = etree.fromstring(updated['word/document.xml'])
    comments = etree.fromstring(updated['word/comments.xml'])
    ids = {str(i) for i in range(len(entries))}
    assert {c.get(wt('id')) for c in comments} == ids
    assert len(comments) == len(ids)
    pars = doc.xpath('//w:body//w:p', namespaces=NS)
    for cid, entry in enumerate(entries):
        p = pars[entry['paragraph']]
        assert 108 <= entry['paragraph'] < 128
        assert entry.get('anchor', '') in text(p)
        for local in ('commentRangeStart', 'commentRangeEnd', 'commentReference'):
            nodes = p.xpath('.//w:' + local, namespaces=NS)
            assert [n.get(wt('id')) for n in nodes] == [str(cid)]
        assert text(comments[cid]).strip()
        assert comments[cid].get(wt('author')) == 'Codex'
    for local in ('commentRangeStart', 'commentRangeEnd', 'commentReference'):
        assert len(doc.xpath('//w:' + local, namespaces=NS)) == len(entries)
    stripped = copy.deepcopy(doc)
    for local in ('commentRangeStart', 'commentRangeEnd'):
        for node in list(stripped.iter(wt(local))):
            node.getparent().remove(node)
    for node in list(stripped.iter(wt('commentReference'))):
        run = node.getparent()
        assert run.tag == wt('r')
        assert all(child.tag in {wt('rPr'), wt('commentReference')} for child in run)
        run.getparent().remove(run)
    source_doc = etree.fromstring(original['word/document.xml'])
    assert etree.tostring(stripped, method='c14n') == etree.tostring(source_doc, method='c14n'), 'body/format changed'
    assert not doc.xpath('//w:ins | //w:del', namespaces=NS)
    rels = etree.fromstring(updated['word/_rels/document.xml.rels'])
    links = [x for x in rels if x.get('Type') == R + '/comments']
    assert len(links) == 1 and links[0].get('Target') == 'comments.xml'
    assert len({x.get('Id') for x in rels}) == len(rels)
    ct = etree.fromstring(updated['[Content_Types].xml'])
    assert len([x for x in ct if x.get('PartName') == '/word/comments.xml']) == 1
    ct_text = text(comments)
    assert '$' not in ct_text
    assert not any(glyph in ct_text for glyph in 'ₚᵢₓᵣᵧʳ')
    return {
        'native_comments': len(entries),
        'example_1_comments': sum(e['paragraph'] < 117 for e in entries),
        'example_2_comments': sum(e['paragraph'] >= 117 for e in entries),
        'figure_comments': sum('image_relationship' in e for e in entries),
        'all_comment_anchors_within_examples_1_and_2': True,
        'original_body_and_formatting_preserved_after_removing_markers': True,
        'all_unrelated_zip_members_and_original_media_byte_identical': True,
        'tracked_body_edits': 0,
        'native_subscript_runs': len(comments.xpath('.//w:vertAlign[@w:val="subscript"]', namespaces=NS)),
        'zip_xml_ranges_and_relationships': 'PASS'
    }

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--replace-generated', action='store_true')
    args = parser.parse_args()
    spec_path = HERE / 'comments.json'
    spec = json.loads(spec_path.read_text())
    entries = spec['comments']
    source_bytes = SOURCE.read_bytes()
    assert sha(source_bytes) == spec['source_sha256'], 'source changed; reread before editing'
    if OUTPUT.exists():
        if not args.replace_generated:
            raise FileExistsError(OUTPUT)
        assert sha(OUTPUT.read_bytes()) == json.loads(AUDIT.read_text())['output_sha256'], 'review copy has user edits'
    with ZipFile(SOURCE) as z:
        infos = z.infolist()
        original = {info.filename: z.read(info.filename) for info in infos}
    assert 'word/comments.xml' not in original
    doc = etree.fromstring(original['word/document.xml'])
    assert not doc.xpath('//w:commentRangeStart | //w:commentReference', namespaces=NS)
    pars = doc.xpath('//w:body//w:p', namespaces=NS)
    assert text(pars[108]).startswith('4.5.1') and text(pars[117]).startswith('4.5.2')
    assert text(pars[128]).startswith('4.5.3')
    comments = etree.Element(wt('comments'), nsmap={'w': W})
    date = datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
    for cid, entry in enumerate(entries):
        p = pars[entry['paragraph']]
        if 'anchor' in entry:
            assert text(p).startswith(entry['anchor']), entry['paragraph']
        if 'image_relationship' in entry:
            assert p.xpath('.//a:blip/@r:embed', namespaces=NS) == [entry['image_relationship']]
        c = el('comment', id=str(cid), author='Codex', initials='CX', date=date)
        comment_paragraph(c, '【建议更新】' + entry['title'], bold=True)
        for line in entry['lines']:
            comment_paragraph(c, line)
        comments.append(c)
        start = 1 if len(p) and p[0].tag == wt('pPr') else 0
        p.insert(start, el('commentRangeStart', id=str(cid)))
        p.append(el('commentRangeEnd', id=str(cid)))
        r, props = el('r'), el('rPr')
        props.append(el('vertAlign', val='superscript'))
        r.append(props)
        r.append(el('commentReference', id=str(cid)))
        p.append(r)
    rels = etree.fromstring(original['word/_rels/document.xml.rels'])
    rid = 'rIdAegisKVReviewComments'
    assert rid not in {x.get('Id') for x in rels}
    etree.SubElement(rels, '{' + PKG + '}Relationship', Id=rid, Type=R + '/comments', Target='comments.xml')
    ct = etree.fromstring(original['[Content_Types].xml'])
    etree.SubElement(ct, '{' + CT + '}Override', PartName='/word/comments.xml',
                     ContentType='application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml')
    replacement = {'word/document.xml': xml(doc), 'word/_rels/document.xml.rels': xml(rels),
                   '[Content_Types].xml': xml(ct), 'word/comments.xml': xml(comments)}
    fd, temp_name = tempfile.mkstemp(prefix='.review-', suffix='.docx', dir=HERE)
    os.close(fd)
    temp = Path(temp_name)
    try:
        with ZipFile(temp, 'w') as z:
            for info in infos:
                z.writestr(copy.copy(info), replacement.get(info.filename, original[info.filename]))
            z.writestr('word/comments.xml', replacement['word/comments.xml'], compress_type=8)
        checks = validate(original, entries, temp)
        os.replace(temp, OUTPUT)
    finally:
        temp.unlink(missing_ok=True)
    design = REPO / 'benchmark/AegisKV/docs/drawio/slacklandlord-patent-revised'
    report = {
        'created_utc': date, 'review_mode': 'native_word_comments_only', 'basis': spec['basis'],
        'source': str(SOURCE), 'source_sha256': sha(source_bytes),
        'source_sha256_after': sha(SOURCE.read_bytes()),
        'output': str(OUTPUT), 'output_sha256': sha(OUTPUT.read_bytes()),
        'comment_spec_sha256': sha(spec_path.read_bytes()),
        'design_sources': [{'path': str(design / f), 'sha256': sha((design / f).read_bytes())}
                           for f in ('README.md', 'algorithm-2-rental-management.drawio')],
        'checks': checks,
        'anchors': [{'comment_id': i, 'paragraph': e['paragraph'], 'title': e['title']}
                    for i, e in enumerate(entries)],
        'figure_review': 'Original embedded figures 2/3 extracted and visually inspected; images unchanged, update instructions in comments.',
        'word_wps_visual_render': 'UNVERIFIED: Word/WPS/LibreOffice unavailable; package checks are not application rendering.',
        'storage_note': 'Review and supporting materials are stored in the project patent directory.',
        'format_reference': 'https://learn.microsoft.com/en-us/office/open-xml/word/how-to-insert-a-comment-into-a-word-processing-document'
    }
    assert report['source_sha256'] == report['source_sha256_after']
    AUDIT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'output': str(OUTPUT), 'audit': str(AUDIT), **checks}, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
