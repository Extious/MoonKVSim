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
for bad in ['Agent 结束','引用解除','Lazy Refresh','尚未兑现','Q_r',
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
 ('candidate','event-state'),('event-state','skip'),('event-state','defer'),
 ('defer','candidate'),('event-state','unready'),('unready','defer'),
 ('unready','gain'),('gain','settle'),('settle','credit'),('credit','resident'),
 ('resident','renew-done'),('resident','plan'),('plan','fits'),
 ('fits','has-tail'),('has-tail','rent'),('has-tail','reject'),
 ('rent','alive'),('alive','remove'),('alive','reject'),('remove','fits'),
 ('fits','execute'),('execute','candidate'),('execute','copy-failed'),
 ('execute','done')]
for a,b in expected:edge(a,b)
assert sum(map(len,adj.values()))==len(expected)
has('candidate','Agent a 的请求到来','一个完整 KV chunk x','本请求 Slack','无副本则空分账')
has('event-state','本请求对 x 的处理状态')
has('skip','重复或过期请求不重新授信')
has('defer','不授信、不复制','回到①重读')
has('unready','需要新副本，且前缀或源未就绪')
has('gain','只计算当前 Agent a',r'G_{a,x}=\min\{T_a(k_a)-T_a(k_a+1),\max(T_a(k_a)-s_a,0)\}')
assert not any(s in cells[prefix+'gain'].get('value','') for s in ['Credit',r'\sum'])
has('settle',r'c_{u,x}\leftarrow c_{u,x}',r'\mathrm{Credit}_x\leftarrow b_x\max(H_x-L,0)',r'\frac{\mathrm{Credit}_x}{\sum_v c_{v,x}}',
    '仅已有 x ∈ Q','结算前总额','总额为 0 时跳过')
has('credit',r'c_{a,x}\leftarrow G_{a,x}',r'\mathrm{Credit}_x\leftarrow\sum_u c_{u,x}',
    r'H_x\leftarrow L+\mathrm{Credit}_x/b_x','其他 Agent 保留租后余额','暂存')
has('renew-done','保存分账','更新堆中','否则冻结份额','内部块、读取中的块同样可续租')
has('plan','临时副本',r'L^{\prime}\leftarrow L',r'Y\leftarrow\varnothing','结算并冻结',
    '必要前缀','持续在 Q 中的 H 不变')
has('symbols-3','初值 0','试算租金','时间/字节')
has('symbols-4','按 H 排序','读取','必要前缀','其他备份操作保护','释放中的块')
has('rent',r'(y,H_y)\leftarrow\min Q','物理块 ID')
has('alive',r'H_y<H_x')
has('remove',r'L^{\prime}\leftarrow H_y',r'Y\leftarrow Y\cup\{y\}',r'f\leftarrow f+b_y',
    r'H_z\leftarrow L^{\prime}+\frac{\sum_u c_{u,z}}{b_z}',
    '新暴露且可释放',r'候选 \(H_x\) 不重建')
has('reject','实际 L、已有副本及余额不变','同值也拒绝')
has('execute','先核验请求、L / Q 版本、保护与容量',r'L\leftarrow L^{\prime}',
    r'c_{a,x}\leftarrow b_x\max(H_x-L^{\prime},0)',
    '冻结 x 的租后份额','撤销 Y 恢复资格','本副本代次')
has('done','当前 L',r'H_x\leftarrow L+\mathrm{Credit}_x/b_x',
    '记录 a 本请求已授信','复制期间不收租','不重算收益、不补满 Credit')
has('copy-failed','已执行的租金推进与释放不回滚','实际状态恢复 Q')
assert adj[prefix+'credit']=={prefix+'resident'}
assert adj[prefix+'rent']=={prefix+'alive'}
assert adj[prefix+'unready']=={prefix+'gain',prefix+'defer'}
assert adj[prefix+'execute']=={prefix+'candidate',prefix+'done',prefix+'copy-failed'}
terminals={'skip','renew-done','reject','copy-failed','done'}
for t in terminals:assert not adj[prefix+t]
seen=set();todo=[prefix+'candidate']
while todo:
 v=todo.pop()
 if v not in seen:seen.add(v);todo.extend(adj[v])
for ident,c in cells.items():
 if c.get('vertex')=='1' and not any(s in ident for s in ['-canvas','-title','-subtitle','-symbols','-layout','-label','-footer']):assert ident in seen,ident
# The merged event filter and execution step have three named outcomes.
# Every remaining decision has two; conditions have not become implicit exits.
for ident,c in cells.items():
 count=len(adj[ident])
 if count>1:
  assert count==(3 if ident in {prefix+'event-state',prefix+'execute'} else 2),ident
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
 'one_event':'an Agent request arrives; one complete KV chunk x in that request is decided',
 'ordering':'request filter -> new-copy readiness -> actor benefit -> deferred rent settlement -> actor-only renewal and H update -> resident save or H/L admission',
 'first_grant':'empty physical-copy ledger plus current actor only; no historical-reference mass renewal',
 'terminal_results':sorted(terminals),'protected_patent_and_algorithm3':'UNCHANGED',
 'checks':['all execution nodes reachable','all outcomes labelled, including two three-way steps',
           'shared readiness wait and pre-execution conflict return to input read','copy failure cannot undo executed releases',
           'strict H_y < H_x before advancing trial L and selecting a victim','no box overlaps',
           'overview layout preserved','native standalone flow matches'],
 'key_conversion':{'before_nodes':19,'after_nodes':len(seen),'before_height':3410,'after_height':3620,'new_step':'deferred proportional rent settlement'},
 'scope':'control paths, formulas and box geometry; native exports reviewed separately; not runtime proof'}
(OUT/'DESIGN_CHECKS.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(report,ensure_ascii=False,indent=2))
