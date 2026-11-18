#!/usr/bin/env node
// Real mxGraph codec checks for every native page; never mutate the source file.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const {JSDOM} = require('jsdom');
const dom = new JSDOM('<!doctype html><html><body></body></html>', {url: 'https://localhost/'});
global.window = dom.window; global.document = dom.window.document;
for (const k of ['DOMParser','XMLSerializer','Node','HTMLElement','Element']) global[k]=dom.window[k];
Object.defineProperty(global,'navigator',{value:dom.window.navigator,configurable:true});
const mx=require('mxgraph')({mxLoadResources:false,mxLoadStylesheets:false}); Object.assign(window,mx);
const filename=path.join(__dirname,'algorithm-2-patent-revised.drawio');
const source=fs.readFileSync(filename,'utf8');
const parse=s=>mx.mxUtils.parseXml(s);
const decode=doc=>{const model=new mx.mxGraphModel();new mx.mxCodec(doc).decode(doc.getElementsByTagName('mxGraphModel')[0],model);return model;};
const doc=parse(source);
const pages=[...doc.getElementsByTagName('diagram')];assert.deepEqual(pages.map(p=>p.getAttribute('id')),['agents','flow']);
const reports=[];
for(const page of pages){
  const standalone=parse(mx.mxUtils.getXml(page.getElementsByTagName('mxGraphModel')[0]));
  const model=decode(standalone);const cells=[...standalone.getElementsByTagName('mxCell')];
  for(const node of cells){
    const id=node.getAttribute('id');assert(!(id in []) && !(id in {}),'prototype collision: '+id);
    const cell=model.getCell(id);assert(cell instanceof mx.mxCell,'not editable: '+id);
    if(node.hasAttribute('parent'))assert.equal(cell.parent.id,node.getAttribute('parent'));
    for(const [attr,sourceEnd] of [['source',true],['target',false]])
      if(node.hasAttribute(attr))assert.equal(cell.getTerminal(sourceEnd).id,node.getAttribute(attr));
  }
  assert.equal(Object.keys(model.cells).length,cells.length);
  const editableNode=cells.find(c=>c.getAttribute('vertex')==='1' && !c.getAttribute('id').endsWith('-canvas'));
  const editable=model.getCell(editableNode.getAttribute('id'));
  const moved=editable.geometry.clone();moved.x+=7;model.setGeometry(editable,moved);model.setValue(editable,editable.value+' [check]');
  const saved=mx.mxUtils.getXml(new mx.mxCodec().encode(model));const reopened=decode(parse(saved));
  assert.equal(reopened.getCell(editable.id).geometry.x,moved.x);assert(reopened.getCell(editable.id).value.endsWith('[check]'));
  assert.equal(Object.keys(reopened.cells).length,cells.length);
  reports.push({page:page.getAttribute('id'),cells:cells.length,legacy_decode:'PASS',edit_save_reopen:'PASS'});
}
const broken=parse(mx.mxUtils.getXml(pages[1].getElementsByTagName('mxGraphModel')[0]));
for(const cell of broken.getElementsByTagName('mxCell'))for(const attr of ['id','source','target','parent'])
  if(cell.getAttribute(attr)==='sla-flow-candidate')cell.setAttribute(attr,'pop');
let reproducedError;
assert.throws(()=>{try{decode(broken);}catch(e){reproducedError=e.message;throw e;}},/setId is not a function/);
const report={status:'PASS',parser:'mxgraph@'+require('mxgraph/package.json').version,dom:'jsdom@'+require('jsdom/package.json').version,
  source_sha256:crypto.createHash('sha256').update(source).digest('hex'),reproduced_error:reproducedError,pages:reports};
fs.writeFileSync(path.join(__dirname,'COMPATIBILITY.json'),JSON.stringify(report,null,2)+'\n');
console.log(JSON.stringify(report,null,2));dom.window.close();
