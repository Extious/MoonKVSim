#!/usr/bin/env python3
"""Path, notation and transaction boundary checks for the Agent event diagram."""
from collections import defaultdict
from pathlib import Path
from html import unescape
import hashlib,json
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
labels='\n'.join(unescape(c.get('value','')) for c in tree.iter('mxCell'))
for bad in ['Agent 结束','引用解除','Lazy Refresh','尚未兑现','H_x','H_y','Q_r',
            'Q_{r}','n_a','n_{a}',r'\mathbf T','W_{a','W_x','D_Y','Agent ID',
            '工作流节点',r'G_x=',r'G_x>',r'\sum_a G','逐个计算各引用 Agent']:
 assert bad not in labels,bad
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
 value=unescape(c.get('value',''))
 assert value.count(r'\(')==value.count(r'\)'),c.get('id')
def has(name,*terms):
 value=unescape(cells[prefix+name].get('value',''))
 for term in terms:assert term in value,(name,term)
def edge(a,b):assert prefix+b in adj[prefix+a],(a,b)
expected=[
 ('candidate','state'),('state','busy'),('busy','defer'),('defer','state'),
 ('busy','duplicate'),('duplicate','duplicate-done'),('duplicate','gain'),
 ('gain','credit'),('credit','aggregate'),('aggregate','resident'),
 ('resident','renew-done'),('resident','prefix'),('prefix','wait-prefix'),
 ('prefix','plan'),('plan','fits'),('fits','queue'),('queue','has-tail'),
 ('has-tail','rent'),('has-tail','reject'),('rent','alive'),('alive','remove'),
 ('alive','reject'),('remove','fits'),('fits','validate'),('validate','retry'),
 ('retry','state'),('validate','copy'),('copy','copy-result'),
 ('copy-result','copy-failed'),('copy-result','done')]
for a,b in expected:edge(a,b)
assert sum(map(len,adj.values()))==len(expected)
has('candidate','当前 Agent a','当前有效请求','完整块 x')
has('state','无副本则建立空分账','元数据操作串行执行')
has('busy','未完成的备份或释放操作')
has('duplicate','a 的本请求已处理或过期')
has('gain','只计算当前 Agent a',r'G_{a,x}=\min\{T_a(k_a)-T_a(k_a+1),\max(T_a(k_a)-s_a,0)\}')
assert not any(s in cells[prefix+'gain'].get('value','') for s in ['Credit',r'\sum'])
has('credit',r'c_{a,x}\leftarrow G_{a,x}','只改 a 的份额','其他 Agent 保留已扣租的余额')
has('aggregate',r'\mathrm{Credit}_x\leftarrow\sum_a c_{a,x}','临时记录')
has('renew-done','保存 a 的份额','内部块、读取中的块也立即续租')
has('prefix','必要前缀已提交','源完整可读')
has('wait-prefix','丢弃本次临时分账')
has('plan','保护必要前缀',r'Y\leftarrow\varnothing','临时记录')
has('queue','其他备份的操作保护块','释放中块')
has('rent',r'\mathrm{Credit}_x/b_x',r'\min_{y\in Q}\mathrm{Credit}_y/b_y',
    r'c_{a,y}(1-b_y\delta/\mathrm{Credit}_y)',r'y\in Q\cup\{x\}',
    '扣租前总余额','零余额跳过除法')
has('alive',r'\mathrm{Credit}_x>0')
has('remove','Credit = 0',r'Y\leftarrow Y\cup\{y\}',r'f\leftarrow f+b_y')
has('reject','已有备份与余额不变','同时归零也拒绝')
has('copy','等待操作结果','匹配本代次的确认')
has('copy-result','释放、分配与复制均成功')
has('done','竞争后的剩余信用','记录 a 本请求已授信','不补满 Credit',
    '其他 Agent 事件随后逐个处理')
has('validate','状态、请求版本、读保护与容量仍有效')
has('retry','丢弃未执行的试算')
has('copy-failed','已执行的扣租与释放不回滚')
assert adj[prefix+'credit']=={prefix+'aggregate'}
assert adj[prefix+'rent']=={prefix+'alive'}
terminals={'duplicate-done','renew-done','wait-prefix','reject','copy-failed','done'}
for t in terminals:assert not adj[prefix+t]
seen=set();todo=[prefix+'candidate']
while todo:
 v=todo.pop()
 if v not in seen:seen.add(v);todo.extend(adj[v])
for ident,c in cells.items():
 if c.get('vertex')=='1' and not any(s in ident for s in ['-canvas','-title','-subtitle','-symbols','-layout','-label','-footer']):assert ident in seen,ident
# All decisions have named outcomes; loops are either a rent step or an
# explicit wait/revalidation retry, not an implicit fall-through.
for ident,c in cells.items():
 if 'rhombus;' in c.get('style',''):
  assert len(adj[ident])==2,ident
  for e in cells.values():
   if e.get('edge')=='1' and e.get('source')==ident:
    assert e.get('id')+'-label' in cells,e.get('id')
# No substantive boxes overlap: exclude detached text labels and background.
boxes=[]
for ident,c in cells.items():
 if c.get('vertex')=='1' and 'strokeColor=#000000;' in c.get('style',''):
  g=c.find('mxGeometry');boxes.append((ident,*[float(g.get(k,'0')) for k in ['x','y','width','height']]))
for i,(name,x,y,w,h) in enumerate(boxes):
 for other,ox,oy,ow,oh in boxes[i+1:]:
  assert min(x+w,ox+ow)<=max(x,ox) or min(y+h,oy+oh)<=max(y,oy),(name,other)
alias=E.parse(OUT/'algorithm-2-rental-management.drawio')
assert [d.get('id') for d in alias.findall('diagram')]==['flow']
assert [c.attrib for c in alias.iter('mxCell')]==[c.attrib for c in page.iter('mxCell')]
protected={OUT.parent.parent/'patent/AegisKV专利交底书-final-version.docx':'d80de557e63edfc0d77a860a262470bf3dca666340724e9a6bfe7f34a507ecb9',OUT.parent/'algorithm-3-guarded-aimd/algorithm-3-guarded-aimd.drawio':'f9122c59c70ef0e4f56ae668a8b4fdf70b57117597ef5e50d30ca5263505273c'}
for path,digest in protected.items():assert sha(path)==digest
report={
 'status':'PASS','source_sha256':sha(SOURCE),'pages':2,'decision_pages':1,
 'execution_nodes':len(seen),'execution_edges':len(expected),
 'overview_geometry_preserved':True,'overview_updated_labels':list(OVERVIEW_LABELS),
 'one_event':'one current Agent/request/complete chunk; busy wait precedes duplicate guard',
 'ordering':'duplicate guard -> actor benefit -> actor credit -> aggregate -> resident or new-copy decision',
 'first_grant':'empty physical-copy ledger plus current actor only; no historical-reference mass renewal',
 'terminal_results':sorted(terminals),'protected_patent_and_algorithm3':'UNCHANGED',
 'checks':['all execution nodes reachable','two labelled outcomes per decision',
           'busy and conflict loops return to state read','copy failure cannot undo executed releases',
           'candidate rent survival before victim selection','no box overlaps',
           'overview layout preserved','native standalone flow matches'],
 'scope':'control paths, formulas and box geometry; native exports reviewed separately; not runtime proof'}
(OUT/'DESIGN_CHECKS.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(report,ensure_ascii=False,indent=2))
