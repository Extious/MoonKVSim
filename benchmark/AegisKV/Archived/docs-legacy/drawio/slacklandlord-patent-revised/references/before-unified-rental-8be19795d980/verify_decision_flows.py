#!/usr/bin/env python3
"""Check the drawn paths and existing accounting primitives; no runtime claims."""
from pathlib import Path
import xml.etree.ElementTree as E
import hashlib,json,re,sys,unittest
from collections import defaultdict

OUT=Path(__file__).resolve().parent
SOURCE=OUT/'algorithm-2-patent-revised.drawio'
BASE=OUT/'references/before-gain-credit-audit-06f9e9e4d5ea-algorithm-2-patent-revised.drawio'
hashfile=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
tree=E.parse(SOURCE)
assert [d.get('id') for d in tree.findall('diagram')]==['agents','flow','cache-hit']
def clean(node):
 return [(e.tag,e.attrib,e.text.strip() if e.text else '') for e in node.iter()]
assert clean(tree.find("diagram[@id='agents']"))==clean(E.parse(BASE).find("diagram[@id='agents']"))
checks={}
for key in ['flow','cache-hit']:
 page=tree.find(f"diagram[@id='{key}']");cs={c.get('id'):c for c in page.iter('mxCell')};assert len(cs)==len(list(page.iter('mxCell')))
 adj=defaultdict(set)
 for c in cs.values():
  for field in ('parent','source','target'):
   if c.get(field):assert c.get(field) in cs
  if c.get('edge')=='1':
   assert c.find('mxGeometry').get('relative')=='1';adj[c.get('source')].add(c.get('target'))
  label=c.get('value','')
  assert not any(s in label for s in ['按右侧','按左侧','Q_r','Q_{r}','n_a','n_{a}','P_{a,x}','Slack 简式适用'])
  assert not re.search(r'(?<![A-Za-z])E(?![A-Za-z])',label)
 prefix='sla-'+key+'-'
 def edge(a,b):assert prefix+b in adj[prefix+a],(key,a,b)
 def has(n,*tokens):
  label=cs[prefix+n].get('value','')
  for token in tokens:assert token in label,(key,n,token)
 has('benefits',r'G_x=\sum_{w\gets x}[\mathrm{WCT}_w(\mathbf T)-\mathrm{WCT}_w(\mathbf T^x)]',r't_v=d_v+T_v','每个工作流只计算一次','单工作流、单 Agent 恢复')
 assert not any(s in cs[prefix+'benefits'].get('value','') for s in ['Agent ID',r'W_{a_i,x}',r'\mathbf T^{(i)}','Credit'])
 has('allocation',r'W_{a_i,x}',r'\mathbf T^{(i-1)}',r'\mathbf T^{(i)}',r'\sum_a W_{a,x}=G_x','固定 Agent ID 顺序','Credit 分账')
 if key=='flow':
  has('recovery','已备份前 k 块时的恢复时间',r'T_a(k_a)',r'T_a(k_a+1)');edge('recovery','benefits')
  has('prefix','必要前缀已提交','源完整可读')
  assert r'\min' not in cs[prefix+'recovery'].get('value','')
  has('benefits',r'P_x=G_x/b_x')
  for a,b in [('fits','build-q'),('build-q','has-tail'),('has-tail','refresh-credit'),('refresh-credit','debit'),('debit','loss'),('loss','trim'),('trim','fits'),('has-tail','bypass'),('accept','validate'),('validate','copy'),('copy','ack'),('ack','allocation'),('allocation','commit'),('commit','allocation'),('commit','copy-failure'),('commit','done')]:edge(a,b)
  has('admission-rule',r'G_x\ge0',r'Y=\varnothing',r'G_x&gt;D_Y',r'Y\ne\varnothing')
  has('refresh-credit',r'\min(c_{a,y},W_{a,y})','首次授信或新轮尚未兑现','已兑现轮号','临时账本','检查全部 Q','未变则保留余额','所有尾块均按当前 L 更新 H','按 Credit 分账框','兑现时记录当前轮号')
  has('debit',r'\frac{b_y\delta}{\mathrm{Credit}_y}','仅推进一次 L','零余额跳过除法')
  has('loss',r'\mathbf T^{-y}','当前临时前缀')
  has('allocation','发布时的实际前缀')
  has('commit','同一分配代次仅发布一次','原子核验','记录已兑现轮号',r'H_x=L+\mathrm{Credit}_x/b_x')
  has('copy-failure','旧分配的 ACK 忽略','已释放的备份不回滚')
  # The new allocation cannot be reached before admission approval. Existing
  # tail renewal in the trial is distinct from initializing the candidate.
  pending=[prefix+'candidate'];before_gate=set()
  while pending:
   v=pending.pop()
   if v not in before_gate:
    before_gate.add(v)
    if v!=prefix+'accept':pending.extend(adj[v])
  assert prefix+'allocation' not in before_gate
 else:
  for a,b in [('committed','admit-missing'),('eligible','defer'),('defer','snapshot'),('snapshot','changed'),('changed','key'),('changed','benefits'),('benefits','allocation'),('allocation','renew'),('renew','key'),('key','validate'),('validate','restart'),('validate','done')]:edge(a,b)
  assert prefix+'done' not in adj[prefix+'changed']
  has('renew',r'\min(c_{a,x},W_{a,x})','首次授信或新轮尚未兑现','临时账本','不补回其他 Agent 已付租金','兑现时记录当前轮号')
  has('key',r'H_x=L+\mathrm{Credit}_x/b_x','无论是否重算收益')
  has('validate','原子核验并写入账本、Q','分配代次与账本版本有效')
  has('done','不推进 L','不增加物理副本')
  has('request','重复、旧轮号不覆盖当前输入')
  has('register','解除引用仍保留已兑现轮号')
  has('defer','保存余额','成为可释放尾块时继续')
 # Every execution node is reachable; layout nodes are separate native drawings.
 seen=set();todo=[prefix+('candidate' if key=='flow' else 'request')]
 while todo:
  v=todo.pop()
  if v not in seen:seen.add(v);todo.extend(adj[v])
 for c in cs.values():
  ident=c.get('id','')
  if c.get('vertex')=='1' and not any(tag in ident for tag in ['-canvas','-title','-subtitle','-symbols','-layout','-footer','-label']):assert ident in seen,(key,'unreachable',ident)
 checks[key]={'cells':len(cs),'reachable_execution_nodes':len(seen),'connected_formulas':'PASS','gain_separate_from_grant_allocation':'PASS','queue_notation':'Q only'}
# Run only matching existing accounting primitives. The historical reference's
# strict admission gate and REUSE shortcut do NOT implement the new drawn paths.
sys.path.insert(0,str(OUT.parent.parent/'algorithm-2'))
from test_agent_lease_slacklandlord import AgentLeaseTests
names=[
 'test_one_physical_rent_is_split_without_double_charging',
 'test_only_requesting_agent_renews_and_event_is_idempotent',
 'test_same_workflow_shared_value_is_not_summed_twice',
 'test_pending_rounds_coalesce_without_accumulating_grants',
 'test_newly_exposed_tail_preserves_spent_balance_without_new_round',
 'test_all_tails_checked_when_an_old_nonminimum_key_drops',
 'test_detach_and_reattach_same_round_does_not_reissue_credit',
 'test_failed_trial_does_not_collect_rent_or_consume_pending_renewal']
result=unittest.TextTestRunner(verbosity=1).run(unittest.TestSuite(AgentLeaseTests(n) for n in names))
assert result.wasSuccessful()
protected={OUT.parent.parent/'patent/AegisKV专利交底书-final-version.docx':'d80de557e63edfc0d77a860a262470bf3dca666340724e9a6bfe7f34a507ecb9',OUT.parent/'algorithm-3-guarded-aimd/algorithm-3-guarded-aimd.drawio':'f9122c59c70ef0e4f56ae668a8b4fdf70b57117597ef5e50d30ca5263505273c'}
for p,sha in protected.items():assert hashfile(p)==sha
# Exact examples check both current endpoints and already-generated suffix work.
# Values are illustrative cost tables for a fixed observed prefix, not measurements.
from fractions import Fraction

def evaluate(load,recompute,k):
 # The current design assumes a longer reused prefix always recovers faster.
 totals=[load[j]+recompute[j] for j in range(len(load))]
 assert all(later<=earlier for earlier,later in zip(totals,totals[1:]))
 before=totals[k];after=totals[k+1]
 return before,after
new_before,new_after=evaluate([0,1,2,3],[12,9,5,0],2)
assert (new_before,new_after)==(7,3)
old_before,old_after=evaluate([0,1,2,3,4],[18,15,11,6,0],1)
assert (old_before,old_after)==(16,13)
assert old_after!=2 # Loading the existing second block leaves known suffix work.
# The single-Agent closed form equals the DAG path-loss reduction for all slacks.
for slack in range(22):
 for before,after in [(new_before,new_after),(old_before,old_after)]:
  assert min(before-after,max(before-slack,0))==max(before-slack,0)-max(after-slack,0)
horizon_checks={'new_chunk_endpoint':[7,3],'existing_tail_known_suffix':[16,13],
                'naive_suffix_omission_rejected':True,'single_agent_slack_identity_cases':44,
                'scope':'full-prefix recovery under the user-stated reuse-faster assumption; exact illustrative arithmetic, not measured latency'}
report={'status':'PASS','source_sha256':hashfile(SOURCE),'scope':'drawn control paths and eight existing exact-rational accounting checks; not implementation of the new hit/admission paths','first_page_preserved':True,'protected_patent_and_algorithm3':'UNCHANGED','pages':checks,'recovery_scope_checks':horizon_checks,'accounting_checks':names,'not_validated':['new zero-gain admission runtime','Cache hit event integration','concurrent copy/allocator implementation','performance or paper-scale readability']}
(OUT/'DESIGN_CHECKS.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(report,ensure_ascii=False,indent=2))
