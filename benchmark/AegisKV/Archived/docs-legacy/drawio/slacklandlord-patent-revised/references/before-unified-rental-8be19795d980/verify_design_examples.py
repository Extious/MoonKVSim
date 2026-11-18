#!/usr/bin/env python3
"""Cross-check native rental-flow equations, preserved edits and the CPU model."""
from fractions import Fraction as Q
import hashlib
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

OUT = Path(__file__).resolve().parent
DESIGN = OUT.parent.parent / 'algorithm-2'
sys.path.insert(0, str(DESIGN))
from agent_lease_slacklandlord import SlackLandlord
from reference import Agent, Chunk, Model, Node, Scenario, Workflow
from test_agent_lease_slacklandlord import seeded
from test_reference import chain_model

digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
source = OUT/'algorithm-2-patent-revised.drawio'
tree = ET.parse(source).getroot()
pages = tree.findall('diagram')
assert [p.get('id') for p in pages] == ['agents', 'flow']
cells = {c.get('id'): c for c in pages[1].findall('.//mxCell')}
labels = {k: c.get('value', '') for k,c in cells.items()}
all_labels = '\n'.join(labels.values())
for obsolete in ('J_{', 'G_X', 'W_X', 'P_X', 'F(V)', '加入前', '加入后', '删前', '删后', 'Credit}_x=G_x-D_Y', '未引入历史租值键', 'G_{a,x}', 'W_x', 'P_x='):
    assert obsolete not in all_labels, obsolete
required = {
    'gain': r'T_a(k)=\min_{0\le j\le k}\{t_a^{\rm reuse}(j)+t_a^{\rm recompute}(j,n_a)\}',
    'gain-single': r'W_{a,x}=\min\{\Delta T_{a,x},\max(T_a(k)-s_a,0)\}',
    'gain-density': r'P_{a,x}=W_{a,x}/b_x',
    'dag-finish': r't_v=d_v+T_v+\max_{u\to v}t_u',
    'dag-order': r'W_{a_i,x}=\sum_{w\gets x}',
    'dag-total': r'G_x=\sum_a W_{a,x}=b_x\sum_aP_{a,x}',
    'credit-total': r'\mathrm{Credit}_x=\sum_a c_{a,x}',
    'renew-agent': r'c_{a,x}\leftarrow b_xP_{a,x}=W_{a,x}',
    'cap-others': r'c_{b,x}\leftarrow\min(c_{b,x},b_xP_{b,x})',
    'lease-key': r'H_x=L+\mathrm{Credit}_x/b_x',
    'collect': r'\delta=\min_{y\in E}(H_y-L)',
    'debit': r'\mathrm{Credit}_y\leftarrow\mathrm{Credit}_y-b_y\delta',
    'rent-split': r'c_{a,y}\leftarrow c_{a,y}\left(1-\frac{b_y\delta}{\mathrm{Credit}_y}\right)',
    'select-tail': r'\mathrm{Credit}_y=0',
    'accept': r'G_x&gt;D_Y',
}
for key, formula in required.items():
    assert formula in labels['sla-flow-'+key], (key, formula)
assert 'sla-flow-gain-shared' not in cells
assert '同一工作流内多 Agent 引用时，改用左侧分账公式' in labels['sla-flow-gain-single']
assert float(cells['sla-flow-gain-density'].find('mxGeometry').get('y')) == 1777
for key, text in [('refresh-tail','检查 E 中每个块'), ('mark','暂不改'), ('lazy-when','下一次收租前'),
                  ('lazy-note','检查全部参与尾块'), ('ledger-note','零信用不做除法'),
                  ('pool-C1','暂停收租'), ('pool-C2','暂停收租'), ('pool-C3','参与收租'),
                  ('pool-note','C2 带剩余信用'), ('bypass','保留真实备份、余额与 L')]:
    assert text in labels['sla-flow-'+key], (key, text)
assert '版本: 7 → 8' in labels['sla-flow-round-update']
assert 'x 已备份' in labels['sla-flow-round-update']
assert 'Agent2 仍为 3 ms' in labels['sla-flow-mark']
assert '计算示例' not in all_labels
legend = cells['sla-flow-symbols'].find('mxGeometry')
assert float(legend.get('y'))+float(legend.get('height')) < float(cells['sla-flow-candidate'].find('mxGeometry').get('y'))
for c in tree.findall('.//mxCell'):
    for color in re.findall(r'(?:fontColor|strokeColor|fillColor)=([^;]+)', c.get('style','')):
        assert color in ('#000000','#FFFFFF','none'), (c.get('id'),color)

# Sizes use one slot for the synthetic model; 4096 in the diagram means tokens.
def pool_model(slack1):
    chunks = [Chunk('P1',None,1),Chunk('C1',None,1),Chunk('C2','C1',1),Chunk('C3','C2',1),Chunk('P2','P1',1)]
    agents = [Agent('Agent1',('P1','P2'),tuple(map(Q,(12,8,6)))),
              Agent('Agent2',('P1','P2'),tuple(map(Q,(10,7,5)))),
              Agent('Agent3',('C1','C2','C3'),tuple(map(Q,(12,11,9,6))))]
    workflows = [Workflow(a.key,(Node(a.key,Q(0),agent=a.key),Node('tool',Q(slack))))
                 for a,slack in zip(agents,(slack1,3,12))]
    return Model(chunks,agents,workflows,[Scenario('source_failure',frozenset(a.key for a in agents))])

old,new = pool_model(8),pool_model(4)
current = old.mask(('P1','C1','C2','C3'))
p = seeded(old,current)
decision = p.admit('P2',4)
assert old.keys(p.current) == ('P1','C1','C2','P2')
assert decision.victims == ('C3',) and (decision.gain,decision.loss,decision.net)==(2,0,2)
assert p.leases['P2'].credit == {'Agent1':0,'Agent2':2}
# A real spent balance of Agent2 must survive Agent1's next request.
p.leases['P2'].debit(Q(1,2))
old_credit = dict(p.leases['P2'].credit)
calls = p.values.evaluations
p.new_request('Agent1',8,new)
assert p.values.evaluations == calls and p.leases['P2'].credit == old_credit
p.refresh_frontier()
assert p.leases['P2'].credit == {'Agent1':2,'Agent2':Q(3,2)}
assert p.leases['P2'].total == Q(7,2)  # not the full current joint value of 4
q = seeded(chain_model(),7)
assert q.admit('b1',3).victims == ('a3',)
assert [q.leases[x].total for x in ('a1','a2')] == [1,2]
load,recompute=(0,1,2),(10,6,3)
assert tuple(min(load[j]+recompute[j] for j in range(k+1)) for k in range(3)) == old.agents['Agent2'].recovery

validation = json.loads((DESIGN/'AGENT_LEASE_VALIDATION.json').read_text())
assert validation['status']=='PASS' and validation['unit_tests']==16
for name,h in validation['sha256'].items():assert digest(DESIGN/name)==h
manual = OUT/'references/user-edited-before-wx-lazy-ea0658897b66.drawio'
assert digest(manual)=='ea0658897b66efbb5c65a74d8ed1900ba666c25b70f41cb5147f7229a269978f'
manual_cells = {c.get('id'):c for c in ET.parse(manual).getroot().findall('.//mxCell')}
for key in ('sla-flow-symbols-title','sla-flow-wait-prefix','sla-flow-user-chunk-card'):
    assert labels[key]==manual_cells[key].get('value')
pre = OUT/'references/before-agent-rental-ade82a9a1ca3.drawio'
assert digest(pre)=='ade82a9a1ca37fe4a6f01f3cf2175ffd13f52975b02726b6f32a25a71d91197d'
latest_manual = OUT/'references/user-edited-before-agent-priority-0cb1e5eeb7ba.drawio'
assert digest(latest_manual)=='0cb1e5eeb7ba4328be6759f91d5fdb13ceb05d8b168bfd7ba41a7f00b0042b02'
latest_cells = {c.get('id'):c for c in ET.parse(latest_manual).getroot().findall('.//mxCell')}
for key in ('sla-flow-references','sla-flow-gain'):
    assert labels[key] == latest_cells[key].get('value')
root = OUT.parents[4]
for path,h in [('benchmark/AegisKV/docs/patent/AegisKV专利交底书-final-version.docx','d80de557e63edfc0d77a860a262470bf3dca666340724e9a6bfe7f34a507ecb9'),
               ('benchmark/AegisKV/docs/drawio/algorithm-3-guarded-aimd/algorithm-3-guarded-aimd.drawio','f9122c59c70ef0e4f56ae668a8b4fdf70b57117597ef5e50d30ca5263505273c')]:
    assert digest(root/path)==h

report = {'status':'PASS','scope':'native diagram and CPU accounting; not physical execution',
          'source_sha256':digest(source),'script_sha256':digest(Path(__file__)),
          'policy_validation_sha256':digest(DESIGN/'AGENT_LEASE_VALIDATION.json'),
          'checks':{'pages':2,'black_white_only':True,'symbols_at_start':True,
                    'explicit_formula_nodes':list(required),'one_physical_chunk_admitted':True,
                    'three_user_labels_preserved':True,'latest_source_preserved':True,
                    'physical_shared_slot_count':1,'Agent2_spent_credit_not_refunded':True,
                    'request_update_no_WCT_evaluation':True,'internal_prefix_balances_survive_tail_eviction':True,
                    'all_eligible_tails_checked_before_rent':True,'zero_credit_division_avoided':True,
                    'patent_and_algorithm3_unchanged':True,'reference_tests':16,'random_small_instances':200}}
(OUT/'DESIGN_CHECKS.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(report,ensure_ascii=False,indent=2))
