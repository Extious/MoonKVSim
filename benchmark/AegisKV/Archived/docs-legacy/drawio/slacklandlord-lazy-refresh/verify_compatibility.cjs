#!/usr/bin/env node
// Run with mxgraph@4.2.2 and jsdom@26.1.0 available via NODE_PATH.
// Exercises the real legacy codec, not a substitute XML validator.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const {JSDOM} = require('jsdom');
const dom = new JSDOM('<!doctype html><html><body></body></html>', {url: 'https://localhost/'});
global.window = dom.window;
global.document = dom.window.document;
for (const k of ['DOMParser', 'XMLSerializer', 'Node', 'HTMLElement', 'Element']) {
  global[k] = dom.window[k];
}
Object.defineProperty(global, 'navigator', {value: dom.window.navigator, configurable: true});
const mx = require('mxgraph')({mxLoadResources: false, mxLoadStylesheets: false});
Object.assign(window, mx);

const filename = path.join(__dirname, 'slacklandlord-lazy-refresh.drawio');
const source = fs.readFileSync(filename, 'utf8');
const parse = text => mx.mxUtils.parseXml(text);
function decode(doc) {
  const model = new mx.mxGraphModel();
  const codec = new mx.mxCodec(doc);
  codec.decode(doc.getElementsByTagName('mxGraphModel')[0], model);
  return model;
}

// Reintroduce just the previous "pop" collision and require the same failure.
const broken = parse(source);
for (const cell of broken.getElementsByTagName('mxCell')) {
  for (const attr of ['id', 'source', 'target', 'parent']) {
    if (cell.getAttribute(attr) === 'slr-pop') cell.setAttribute(attr, 'pop');
  }
}
let reproducedError;
assert.throws(() => {
  try { decode(broken); } catch (e) { reproducedError = e.message; throw e; }
}, /setId is not a function/);

const doc = parse(source);
const model = decode(doc);
const cells = [...doc.getElementsByTagName('mxCell')];
for (const node of cells) {
  const id = node.getAttribute('id');
  assert(!(id in []) && !(id in {}), 'ID collides with prototype: ' + id);
  const cell = model.getCell(id);
  assert(cell instanceof mx.mxCell, 'not an editable mxCell: ' + id);
  if (node.hasAttribute('parent')) assert.equal(cell.parent.id, node.getAttribute('parent'));
  for (const [attr, sourceEnd] of [['source', true], ['target', false]]) {
    if (node.hasAttribute(attr)) assert.equal(cell.getTerminal(sourceEnd).id, node.getAttribute(attr));
  }
}
assert.equal(Object.keys(model.cells).length, cells.length);

// Edit a label and geometry in memory, then save/reopen through mxCodec.
const editable = model.getCell('slr-pop');
const originalX = editable.geometry.x;
const moved = editable.geometry.clone();
moved.x += 10;
model.setGeometry(editable, moved);
model.setValue(editable, editable.value + ' [compatibility check]');
const saved = mx.mxUtils.getXml(new mx.mxCodec().encode(model));
const reopened = decode(parse(saved));
assert.equal(reopened.getCell('slr-pop').geometry.x, originalX + 10);
assert(reopened.getCell('slr-pop').value.endsWith('[compatibility check]'));
assert.equal(Object.keys(reopened.cells).length, cells.length);

const report = {
  status: 'PASS',
  parser: 'mxgraph@' + require('mxgraph/package.json').version,
  dom: 'jsdom@' + require('jsdom/package.json').version,
  source_sha256: crypto.createHash('sha256').update(source).digest('hex'),
  reproduced_error: reproducedError,
  legacy_decode: 'PASS', cell_types_and_references: 'PASS', edit_save_reopen: 'PASS',
  cells: cells.length,
  vertices: cells.filter(c => c.getAttribute('vertex') === '1').length,
  edges: cells.filter(c => c.getAttribute('edge') === '1').length,
};
fs.writeFileSync(path.join(__dirname, 'COMPATIBILITY.json'), JSON.stringify(report, null, 2) + '\n');
console.log(JSON.stringify(report, null, 2));
dom.window.close();
