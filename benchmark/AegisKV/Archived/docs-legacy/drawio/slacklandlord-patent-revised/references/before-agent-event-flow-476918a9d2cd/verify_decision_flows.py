#!/usr/bin/env python3
"""Check the current diagram's paths/notation, without runtime claims."""
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
all_labels='\n'.join(unescape(c.get('value','')) for c in tree.iter('mxCell'))
for bad in ['Agent 结束','引用解除','Lazy Refresh','尚未兑现','H_x','H_y','Q_r','Q_{r}',
            'n_a','n_{a}',r'\mathbf T','W_{a','W_x','D_Y','Agent ID','工作流节点',
            r'G_x=',r'G_x>',r'\sum_a G']:
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
 value=unescape(c.get('value',''))
 assert value.count(r'\(')==value.count(r'\)'),c.get('id')

def has(name,*terms):
 value=unescape(cells[prefix+name].get('value',''))
 for term in terms:assert term in value,(name,term)
def edge(a,b):assert prefix+b in adj[prefix+a],(a,b)
for a,b in [('candidate','resident'),('resident','renew'),('resident','prefix'),
 ('prefix','gain'),('prefix','wait-prefix'),('gain','initial'),('initial','plan'),
 ('plan','fits'),('fits','queue'),('queue','has-tail'),('has-tail','rent'),
 ('has-tail','no-space'),('rent','alive'),('alive','remove'),('alive','no-space'),
 ('remove','fits'),('fits','copy'),('copy','done'),('copy','copy-failed'),
 ('renew','renew-done')]:edge(a,b)
has('prefix','必要前缀已提交','源完整可读')
has('gain',r'G_{a,x}=\min\{T_a(k_a)-T_a(k_a+1),\max(T_a(k_a)-s_a,0)\}',
    '逐个计算各引用 Agent','内部块按')
assert not any(s in cells[prefix+'gain'].get('value','') for s in ['Credit',r'\sum'])
has('initial',r'c_{a,x}\leftarrow G_{a,x}',r'\mathrm{Credit}_x\leftarrow\sum_a c_{a,x}','尚未分配')
has('renew','新 Slack','首次复用',r'c_{a,x}\leftarrow G_{a,x}','其他 Agent 余额不变','重复事件保留原余额')
has('rent',r'\mathrm{Credit}_x/b_x',r'\min_{y\in Q}\mathrm{Credit}_y/b_y',
    r'c_{a,y}(1-b_y\delta/\mathrm{Credit}_y)',r'y\in Q\cup\{x\}','零余额跳过除法')
has('alive',r'\mathrm{Credit}_x>0')
has('remove','Credit = 0',r'Y\leftarrow Y\cup\{y\}',r'f\leftarrow f+b_y')
has('no-space','已有备份与余额不变','同时归零也拒绝')
has('done','保留竞争后的信用余额','不重新授信','本请求已授信')
has('copy','核验代次与余额版本','释放 Y 后')
has('renew-done','立即保存','内部块、读取中的块也可续租')
has('copy-failed','旧 ACK 不发布','已释放的备份不回滚')
seen=set();todo=[prefix+'candidate']
while todo:
 v=todo.pop()
 if v not in seen:seen.add(v);todo.extend(adj[v])
for ident,c in cells.items():
 if c.get('vertex')=='1' and not any(s in ident for s in ['-canvas','-title','-subtitle','-symbols','-layout','-label','-footer']):assert ident in seen,ident
assert adj[prefix+'renew']=={prefix+'renew-done'}
assert adj[prefix+'rent']=={prefix+'alive'}  # Candidate tie check before victim removal.
assert adj[prefix+'done']==set()             # No post-copy grant refill.
g=cells[prefix+'wait-prefix'].find('mxGeometry')
assert [g.get(k) for k in ['x','y','width','height']]==['53','1115','960','150']
alias=E.parse(OUT/'algorithm-2-rental-management.drawio')
assert [d.get('id') for d in alias.findall('diagram')]==['flow']
assert [c.attrib for c in alias.iter('mxCell')]==[c.attrib for c in page.iter('mxCell')]
protected={OUT.parent.parent/'patent/AegisKV专利交底书-final-version.docx':'d80de557e63edfc0d77a860a262470bf3dca666340724e9a6bfe7f34a507ecb9',OUT.parent/'algorithm-3-guarded-aimd/algorithm-3-guarded-aimd.drawio':'f9122c59c70ef0e4f56ae668a8b4fdf70b57117597ef5e50d30ca5263505273c'}
for path,digest in protected.items():assert sha(path)==digest
report={
 'status':'PASS','source_sha256':sha(SOURCE),'pages':2,'decision_pages':1,
 'execution_nodes':len(seen),'overview_geometry_preserved':True,
 'manual_missing_prefix_box_preserved':True,'overview_updated_labels':list(OVERVIEW_LABELS),
 'valuation':'independent Agent benefits; only remaining Credit is summed',
 'renewal':'actual actor only, once per request, immediately including internal/pinned blocks',
 'rent':'candidate and physical tails; proportional sublease debit; candidate loses ties',
 'protected_patent_and_algorithm3':'UNCHANGED',
 'checks':['no joint workflow vector or ordered Agent allocation',
           'connected independent benefit, initial grant and actor-only renewal formulas',
           'candidate survives rent before selecting a victim','zero-credit free-space path',
           'post-copy preserves remaining credit','all execution nodes reachable',
           'native pages and standalone match','balanced TeX delimiters'],
 'scope':'drawn control paths and formulas; exact arithmetic in SEMANTIC_AUDIT.json; no serving implementation'}
(OUT/'DESIGN_CHECKS.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(report,ensure_ascii=False,indent=2))
