#!/usr/bin/env python3
"""Structural audit of the unified design; no deployed-runtime claims."""
from collections import defaultdict
from pathlib import Path
import hashlib,json,re
import xml.etree.ElementTree as E
from build_decision_flows import OVERVIEW_LABELS, BASE

OUT=Path(__file__).resolve().parent
SOURCE=OUT/'algorithm-2-patent-revised.drawio'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
tree=E.parse(SOURCE)
assert [d.get('id') for d in tree.findall('diagram')]==['agents','flow']
base=E.parse(BASE)
old={c.get('id'):c for c in base.find("diagram[@id='agents']").iter('mxCell')}
now={c.get('id'):c for c in tree.find("diagram[@id='agents']").iter('mxCell')}
assert old.keys()==now.keys()
for ident,c in old.items():
 a,b=dict(c.attrib),dict(now[ident].attrib)
 if ident in {'sla-agents-'+s for s in OVERVIEW_LABELS}:a.pop('value');b.pop('value')
 assert a==b,ident
 ga,gb=c.find('mxGeometry'),now[ident].find('mxGeometry')
 if ga is not None:assert [(x.tag,x.attrib) for x in ga.iter()]==[(x.tag,x.attrib) for x in gb.iter()],ident
all_labels='\n'.join(c.get('value','') for c in tree.iter('mxCell'))
for bad in ['Agent 结束','引用解除','Lazy Refresh','尚未兑现','H_x','H_y','Q_r','Q_{r}','n_a','n_{a}','L\\leftarrow']:
 assert bad not in all_labels,bad
page=tree.find("diagram[@id='flow']")
cells={c.get('id'):c for c in page.iter('mxCell')}
assert len(cells)==len(list(page.iter('mxCell')))
adj=defaultdict(set);prefix='sla-flow-'
for c in cells.values():
 for f in ['parent','source','target']:
  if c.get(f):assert c.get(f) in cells
 if c.get('edge')=='1':
  assert c.find('mxGeometry').get('relative')=='1'
  adj[c.get('source')].add(c.get('target'))

def has(name,*terms):
 value=cells[prefix+name].get('value','')
 for term in terms:assert term in value,(name,term)
def edge(a,b):assert prefix+b in adj[prefix+a],(a,b)
for a,b in [('candidate','resident'),('resident','allocation'),('resident','prefix'),('prefix','gain'),('prefix','wait-prefix'),('gain','plan'),('plan','fits'),('fits','queue'),('queue','has-tail'),('has-tail','revalue'),('revalue','rent'),('rent','remove'),('remove','fits'),('has-tail','no-space'),('fits','accept'),('accept','copy'),('accept','reject'),('copy','allocation'),('copy','copy-failed'),('allocation','credit'),('credit','done')]:edge(a,b)
has('prefix','必要前缀已提交','源完整可读')
has('gain',r'G_x=\sum_{w\gets x}',r'\mathbf T^x','单工作流、单 Agent 恢复')
assert not any(s in cells[prefix+'gain'].get('value','') for s in ['Agent ID',r'W_{a_i,x}','Credit'])
has('allocation',r'W_{a_i,x}',r'\sum_a W_{a,x}=G_x','内部块也按到 x 的前缀评估')
has('credit','a 复用且本轮未授信',r'\min(c_{a,x},W_{a,x})','记录本轮续租已处理','其他 Agent 已花掉的信用不补回')
has('revalue',r'\min(c_{a,y},W_{a,y})','没有实际复用就不续租')
has('rent',r'\delta=\min_{y\in Q}\frac{\mathrm{Credit}_y}{b_y}',r'\frac{b_y\delta}{\mathrm{Credit}_y}','零余额跳过除法')
has('remove',r'\mathbf T^{-y}','删除 y 后的恢复耗时',r'D_Y\leftarrow D_Y+')
has('accept',r'G_x\ge0',r'Y=\varnothing',r'G_x&gt;D_Y',r'Y\ne\varnothing')
has('done','原子保存','内部块、读取中的块保留余额')
has('copy','复制成功才进入授信')
has('copy-failed','旧 ACK 不授信','已释放备份不回滚')
seen=set();todo=[prefix+'candidate']
while todo:
 v=todo.pop()
 if v not in seen:seen.add(v);todo.extend(adj[v])
for ident,c in cells.items():
 if c.get('vertex')=='1' and not any(s in ident for s in ['-canvas','-title','-subtitle','-symbols','-layout','-label','-footer']):assert ident in seen,ident
# The hit path is not forced through a frontier/rental test before refresh.
assert adj[prefix+'allocation']=={prefix+'credit'}
assert adj[prefix+'credit']=={prefix+'done'}
# The standalone source contains the same one native flow.
alias=E.parse(OUT/'algorithm-2-rental-management.drawio')
assert [d.get('id') for d in alias.findall('diagram')]==['flow']
assert [c.attrib for c in alias.iter('mxCell')]==[c.attrib for c in page.iter('mxCell')]
protected={OUT.parent.parent/'patent/AegisKV专利交底书-final-version.docx':'d80de557e63edfc0d77a860a262470bf3dca666340724e9a6bfe7f34a507ecb9',OUT.parent/'algorithm-3-guarded-aimd/algorithm-3-guarded-aimd.drawio':'f9122c59c70ef0e4f56ae668a8b4fdf70b57117597ef5e50d30ca5263505273c'}
for path,digest in protected.items():assert sha(path)==digest
report={'status':'PASS','source_sha256':sha(SOURCE),'pages':2,'decision_pages':1,'execution_nodes':len(seen),'overview_geometry_preserved':True,'overview_updated_labels':list(OVERVIEW_LABELS),'new_event_semantics':'reuse renews immediately including internal/pinned blocks; no Agent end event or pending-round settlement','rent_semantics':'explicit physical credit debit; no H/L state','protected_patent_and_algorithm3':'UNCHANGED','checks':['gain and allocation separated','shared credit sum defined','reuse bypasses capacity and frontier tests','only actual reuse authorizes renewal','tail revaluation cannot renew','piecewise zero gain admission','physical rent and conditional loss separated','copy success before credit publication','native pages and standalone match'],'scope':'drawn control paths and formulas; numerical checks in SEMANTIC_AUDIT.json, no concurrent runtime implementation'}
(OUT/'DESIGN_CHECKS.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps(report,ensure_ascii=False,indent=2))
