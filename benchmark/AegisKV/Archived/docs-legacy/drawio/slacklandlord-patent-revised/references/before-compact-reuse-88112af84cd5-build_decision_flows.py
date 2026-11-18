#!/usr/bin/env python3
"""Online recovery decision diagrams. Preserve page 1 and reviewed source snapshots."""
from pathlib import Path
from copy import deepcopy
from html import escape
import argparse, hashlib, json
import xml.etree.ElementTree as E
import build_diagram as native

OUT=Path(__file__).resolve().parent
SOURCE=OUT/'algorithm-2-patent-revised.drawio'
BASE=OUT/'references/before-online-review-8f438d425dc7-algorithm-2-patent-revised.drawio'
BASE_HASH='8f438d425dc7a54171c301eeeaf159ba0353c881751d2bb57a0408fde380af72'
hashfile=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()

class Flow:
 def __init__(self,key,name,width,height):
  self.key=key;self.w=width;self.h=height;self.d=E.Element('diagram',id=key,name=name)
  g=E.SubElement(self.d,'mxGraphModel',math='1',grid='0',page='1',pageWidth=str(width),pageHeight=str(height),background='#FFFFFF')
  self.r=E.SubElement(g,'root');E.SubElement(self.r,'mxCell',id='0');E.SubElement(self.r,'mxCell',id='1',parent='0');self.nodes={};self.edges=[]
  self.box('canvas','',0,0,width,height,text=True)
 def uid(self,key):return 'sla-'+self.key+'-'+key
 def box(self,key,s,x,y,w,h,*,size=28,decision=False,text=False,bold=False,align='center'):
  style=f'fontFamily=Noto Sans CJK SC;fontSize={size};fontColor=#000000;whiteSpace=wrap;html=1;align={align};verticalAlign=middle;spacing=12;strokeWidth=2;'
  style+= 'text;strokeColor=none;fillColor=none;' if text else 'strokeColor=#000000;fillColor=#FFFFFF;'+('rhombus;' if decision else 'rounded=1;arcSize=8;')
  if bold:style+='fontStyle=1;'
  if key=='canvas':style+='locked=1;connectable=0;'
  val='<div style="line-height:1.4">'+escape(s).replace('\n','<br>')+'</div>'
  c=E.SubElement(self.r,'mxCell',id=self.uid(key),value=val,style=style,vertex='1',parent='1')
  E.SubElement(c,'mxGeometry',x=str(x),y=str(y),width=str(w),height=str(h),attrib={'as':'geometry'});self.nodes[key]=(x,y,w,h)
  return c
 def edge(self,a,b,*,out=(.5,1),into=(.5,0),points=(),label='',label_at=None,dashed=False):
  key='edge-'+str(len(self.edges));self.edges.append((a,b));s='edgeStyle=orthogonalEdgeStyle;rounded=0;strokeColor=#000000;strokeWidth=2.4;endArrow=block;endFill=1;endSize=9;jettySize=20;jumpStyle=arc;jumpSize=10;'
  s+=f'exitX={out[0]};exitY={out[1]};entryX={into[0]};entryY={into[1]};'
  if dashed:s+='dashed=1;dashPattern=6 4;'
  c=E.SubElement(self.r,'mxCell',id=self.uid(key),style=s,edge='1',source=self.uid(a),target=self.uid(b),parent='1');g=E.SubElement(c,'mxGeometry',relative='1',attrib={'as':'geometry'})
  if points:
   arr=E.SubElement(g,'Array',attrib={'as':'points'})
   for x,y in points:E.SubElement(arr,'mxPoint',x=str(x),y=str(y))
  if label:
   assert label_at
   self.box(key+'-label',label,*label_at,size=24,text=True)
 def chain(self,*keys):
  for a,b in zip(keys,keys[1:]):self.edge(a,b)
 def validate(self):
  cs=list(self.r);ids={c.get('id') for c in cs};assert len(ids)==len(cs)
  for c in cs:
   for key in ('source','target','parent'):
    if c.get(key):assert c.get(key) in ids
  for key,(x,y,w,h) in self.nodes.items():assert x>=0 and y>=0 and x+w<=self.w and y+h<=self.h,(key,x,y,w,h)
  return {'cells':len(cs),'edges':len(self.edges),'page_size':[self.w,self.h],'formula_nodes':[c.get('id') for c in cs if '\\(' in c.get('value','')]}

def legend(p,hit=False):
 p.box('title','SlackLandlord  ·  '+('Cache hit、Credit 续租与 Lazy Refresh' if hit else '新 chunk：收益分账、准入与尾块收租'),60,25,p.w-120,80,size=40,text=True,bold=True,align='left')
 p.box('subtitle','恢复收益只按 WCT 计价；黑色实线表示执行顺序，等待框由对应事件继续。',60,115,p.w-120,65,size=27,text=True,align='left')
 p.box('symbols-title','符号说明',60,210,p.w-120,65,size=31,text=True,bold=True,align='left')
 rows=[
 r'\(x\)：本次处理的物理块；\(y\)：待淘汰尾块；\(a\)：Agent；\(s_a\)：本轮 Slack；\(b_x,b_y\)：物理字节数',
 r'\(k\)：连续备份块数；\(k_a\)：待评估块之前的连续备份块数；\(t_a^{\rm reuse}(j)\)：复用前 j 块；\(t_a^{\rm recompute}(j)\)：重算其余已生成 KV',
 r'\(T_a(k_a),T_a(k_a+1)\)：不用 / 使用待评估块的恢复时间；\(W_{a,x}\)：Agent 的 WCT 收益份额；\(P_{a,x}=W_{a,x}/b_x\)',
 r'\(c_{a,x}\)：Agent 剩余信用；\(\mathrm{Credit}_x=\sum_a c_{a,x}\)；\(H_x\)：尾块租值键；\(L\)：累计租金；\(\delta\)：本次收租增量',
 r'\(Q\)：本次决策的可释放尾块优先队列；\(Y\)：计划淘汰的块；\(f\)：计划可用字节；\(G_x,D_Y\)：加入收益、累计回收损失',
 r'\(w\)：工作流；\(v,u\)：DAG 节点；\(d_v,t_v\)：正常耗时、完成时间；\(\mathbf T\)：各节点恢复耗时；\(\max\varnothing=0\)']
 if hit:
  rows[0]=r'\(x\)：本次命中的物理块；\(a\)：Agent；\(s_a\)：本轮 Slack；\(b_x\)：实际物理字节数'
  rows[3]=r'\(c_{a,x}\)：Agent 剩余信用；\(\mathrm{Credit}_x=\sum_a c_{a,x}\)；\(H_x\)：尾块租值键；\(L\)：累计租金'
  rows[4]=r'\(Q\)：可释放尾块优先队列；已兑现轮号：该 Agent 对本块最近一次完成授信或续租的请求轮号'
 for i,s in enumerate(rows):p.box('symbols-'+str(i),s,75,290+i*65,p.w-150,62,size=26,text=True,align='left')

def recovery(symbol='x',new=False):
 compare=(rf'备份 {symbol} 前：\(T_a(k_a)\)；备份后：\(T_a(k_a+1)\)' if new else rf'不保留 {symbol}：\(T_a(k_a)\)；保留 {symbol}：\(T_a(k_a+1)\)')
 return (r'计算各引用 Agent 在备份 \(k\) 块时的恢复时间'+'\n'+r'\(T_a(k)=\min_{0\le j\le k}\{t_a^{\rm reuse}(j)+t_a^{\rm recompute}(j)\}\)'+'\n'+r'先复用前 \(j\) 块，再重算其余已生成 KV'+'\n'+compare)

DAG=('对每组 '+r'\(\mathbf T^{(i)}\)'+' 按拓扑顺序计算工作流完成时间\n'+r'\(t_v=d_v+T_v+\max_{u\to v}t_u,\quad\mathrm{WCT}_w(\mathbf T)=\max_{v\in w}t_v\)'+'\n受故障影响的 Agent 节点取其恢复耗时；其余节点取 0')
def ordered(symbol):
 return ('共享引用按固定 Agent ID 顺序排列：'+r'\(a_1,\ldots,a_m\)'+'\n'+rf'\(\mathbf T^{{(i)}}\)：前 i 个引用 Agent 使用 {symbol}，其余引用 Agent 不用 {symbol}'+'\n'+r'使用时取 \(T_a(k_a+1)\)，不用时取 \(T_a(k_a)\)；其他节点保持当前恢复时间')

def shares(symbol):
 return ('计算不重复计价的 Agent 收益份额\n'+rf'\(W_{{a_i,{symbol}}}=\sum_{{w\gets {symbol}}}\left[\mathrm{{WCT}}_w(\mathbf T^{{(i-1)}})-\mathrm{{WCT}}_w(\mathbf T^{{(i)}})\right]\)'+'\n'+rf'\(w\gets {symbol}\)：引用 {symbol} 的工作流；每个工作流按此顺序分账一次')
def joint_and_slack(symbol):
 return (shares(symbol)+'\n仅单个 Agent 需要恢复时，上式等价于：\n'+rf'\(W_{{a,{symbol}}}=\min\{{T_a(k_a)-T_a(k_a+1),\max(T_a(k_a)-s_a,0)\}}\)')

def renew(symbol):
 return ('Lazy Refresh：在临时账本中逐 Agent 更新信用\n'+rf'\(c_{{a,{symbol}}}\leftarrow\begin{{cases}}0,&\text{{Agent 结束或引用解除}};\\W_{{a,{symbol}}},&\text{{首次引用或新轮尚未兑现}};\\\min(c_{{a,{symbol}}},W_{{a,{symbol}}}),&\text{{本轮已兑现}}.\end{{cases}}\)'+'\n临时记录已兑现轮号；解除引用后也保留去重记录')

def layout(p,x,y,w=790,hit=False):
 p.box('layout-title','KV 布局示意',x,y,w,70,text=True,bold=True,size=31)
 p.box('layout-card',('共享块 x' if hit else '共享块 P1')+'\nAgent 1 → 本轮 Slack\nAgent 2 → 本轮 Slack\n'+(r'\(b_x\)：实际 bytes；内容：4096 tokens' if hit else r'\(b_{P1}\)：实际 bytes；内容：4096 tokens'),x,y+105,w,220,size=28)
 p.box('layout-agent-a','Agent 1',x,y+380,180,75,text=True,size=26)
 p.box('layout-agent-b','Agent 2',x,y+550,180,75,text=True,size=26)
 for row,yy,keys in [('a',y+380,['x','A2','A3'] if hit else ['P1','A2','x']),('b',y+550,['x','B2'] if hit else ['P1','B2'])]:
  for i,k in enumerate(keys):
   name=f'layout-{row}-{i}';p.box(name,k,x+205+i*185,yy,155,75,size=28)
   if i:p.edge(f'layout-{row}-{i-1}',name,out=(1,.5),into=(0,.5))
 p.box('layout-pool-title',('Peer HBM Pool · 共享 x 只占一份空间' if hit else 'Peer HBM Pool · 同一 P1 只占一份空间'),x,y+750,w,80,text=True,size=27)
 for i,k in enumerate(['x','A2','A3','B2','C1','空闲'] if hit else ['P1','A2','B2','C1','C2','空闲']):p.box('layout-slot-'+str(i),k,x+(i%3)*260,y+860+(i//3)*110,235,85,size=28)
 p.box('layout-note',('x 为命中的共享内部块，有后继时先延迟刷新\n本图仅示意物理位置与共享关系' if hit else '实线框：已提交备份；箭头：前缀依赖\nx：候选块；本图仅示意物理位置与共享关系'),x,y+1130,w,115,text=True,size=26)


def admission():
 p=Flow('flow','2 · 新 chunk：完整准入决策',3820,7970);legend(p)
 X=1450;W=1300;C=2100;LX=80;LW=1160
 def main(k,s,y,h=150,**kw):return p.box(k,s,X,y,W,h,**kw)
 def left(k,s,y,h=150,**kw):return p.box(k,s,LX,y,LW,h,**kw)
 main('candidate','① 新的完整 KV chunk x 到来\n按前缀顺序逐块决策',780,115)
 p.box('prefix','源完整可读，且必要前缀均已提交？',1640,1010,920,170,decision=True)
 left('wait-prefix','BYPASS：本轮不备份 x\n前缀未备份，后续也不再备份（Prefix Cache）',1030,130,size=28)
 main('inputs','② 读取引用 Agent、本轮 Slack、轮号与恢复代价\n新请求只更新 Agent 表；请求内 Slack 不变，不逐块重设 Credit',1270,155)
 main('recovery',recovery(new=True),1510,270,size=27)
 main('dag',DAG,2155,175,size=27)
 main('ordered',ordered('x'),1880,160,size=27)
 main('shares','③ '+joint_and_slack('x'),2415,275,size=26)
 main('priority','④ 计算优先级与本块总收益\n'+r'\(P_{a,x}=W_{a,x}/b_x,\qquad G_x=\sum_a W_{a,x}\)',2790,145,size=30)
 main('init','⑤ 复制余额与轮号到临时账本，保护 x 的必要前缀\n'+r'\(Y\leftarrow\varnothing,\quad D_Y\leftarrow0,\quad f\leftarrow\text{Pool 可用字节}\)'+'\n回收试算按 x 可恢复时的前缀计算；通过准入前不改真实账本',3050,185,size=27)
 p.box('fits','可用空间足够？\n'+r'\(f\ge b_x\)',1675,3390,850,170,decision=True,size=29)
 main('admission-rule',r'\(\boxed{\begin{cases}G_x\ge0,&Y=\varnothing\quad\text{无需淘汰已有块};\\[2mm]G_x>D_Y,&Y\ne\varnothing\quad\text{需要淘汰已有块}.\end{cases}}\)',3660,200,size=29)
 p.box('accept','满足准入条件？',1675,3970,850,170,decision=True,size=29)
 p.box('validate','⑥ 输入、容量、读取状态\n及租金账本版本仍有效？',1640,4240,920,170,decision=True,size=27)
 main('release','⑦ 提交回收计划与扣租记录\n'+r'\(Y\ne\varnothing\)：释放 Y，等待对应物理释放 ACK'+'\n'+r'\(Y=\varnothing\)：跳过释放',4510,155,size=28)
 main('copy','⑧ 为 x 分配空间并复制全部分片',4770,115,size=29)
 p.box('ack','全部分片成功，且提交条件仍有效？',1640,5000,920,170,decision=True,size=28)
 main('grant-value','⑨ 按实际前缀与当前已生成 KV 重算收益份额\n'+r'\(W_{a_i,x}=\sum_{w\gets x}[\mathrm{WCT}_w(\mathbf T^{(i-1)})-\mathrm{WCT}_w(\mathbf T^{(i)})]\)'+'\n'+r'\(P_{a,x}=W_{a,x}/b_x\)',5250,285,size=26)
 main('commit','⑩ 发布 COMMITTED，初始化各 Agent 的信用\n'+r'\(c_{a,x}\leftarrow b_xP_{a,x}=W_{a,x},\quad\mathrm{Credit}_x=\sum_a c_{a,x}\)'+'\n发布前原子重验计算版本，并记录已兑现轮号；零收益时 Credit = 0',5620,200,size=28)
 p.box('new-tail','x 当前是可释放尾块？',1675,5930,850,170,decision=True,size=29)
 main('publish-key',r'\(H_x\leftarrow L+\mathrm{Credit}_x/b_x\)'+'\n将 x 加入 Q；若变成内部块，保留余额并退出尾块竞争',6210,150,size=29)
 main('done','本次备份完成；处理下一个完整 chunk',6540,100,size=29)
 # Connected rental branch: all decision calculations are inside executable flow nodes.
 left('build-q','更新 Q：已提交、无后继、可独立释放的尾块\n排除 x、必要前缀与正在读取的块',3140,150,size=27)
 p.box('has-tail','有可释放尾块？\n'+r'\(Q\ne\varnothing\)',235,3390,850,170,decision=True,size=29)
 left('refresh-inputs','逐个检查 Q 中的尾块 y\n读取引用 Agent 的轮号、Slack 及相关工作流前缀 / 代价版本',3660,140,size=27)
 p.box('tail-dirty','新暴露尾块，或输入版本已变化？',235,3890,850,150,decision=True,size=27)
 left('tail-time',recovery('y'),4130,250,size=25)
 left('tail-share','为 y 按固定 Agent 顺序构造恢复时间，再联合分账\n'+r'\(t_v=d_v+T_v+\max_{u\to v}t_u,\quad\mathrm{WCT}_w=\max_v t_v\)'+'\n'+r'\(W_{a_i,y}=\sum_{w\gets y}[\mathrm{WCT}_w(\mathbf T^{(i-1)})-\mathrm{WCT}_w(\mathbf T^{(i)})]\)'+'\n'+r'固定 Agent 顺序；使用 y 取 \(T_a(k_a+1)\)，不用时取 \(T_a(k_a)\)',4440,240,size=25)
 left('refresh-credit',renew('y'),4780,285,size=27)
 left('tail-key','汇总余额，更新当前尾块租值键\n'+r'\(\mathrm{Credit}_y=\sum_a c_{a,y},\quad H_y\leftarrow L+\mathrm{Credit}_y/b_y\)',5165,145,size=29)
 p.box('more-tails','Q 中还有未检查的尾块？',235,5415,850,150,decision=True,size=28)
 left('collect','计算本次租金增量\n'+r'\(\delta=\min_{y\in Q}(H_y-L)\)',5675,120,size=30)
 left('debit','每个物理块只收一份租金，按扣租前余额分摊\n'+r'\(c_{a,y}\leftarrow c_{a,y}\left(1-\frac{b_y\delta}{\mathrm{Credit}_y}\right)\)'+'\n'+r'\(\mathrm{Credit}_y\leftarrow\sum_a c_{a,y}\)'+'\n'+r'全 Q 分摊完成后，仅推进一次：\(L\leftarrow L+\delta\)'+'\nCredit = 0 时跳过除法；内部块与固定读取块不在 Q 中',5895,275,size=26)
 left('select-tail','选择一个 Credit = 0 的尾块 y\n同值时按物理块 ID 决定',6255,130,size=29)
 left('loss','计算删除 y 的当前条件恢复损失\n'+r'\(G_y=\sum_{w\gets y}[\mathrm{WCT}_w(\mathbf T^{-y})-\mathrm{WCT}_w(\mathbf T)]\)'+'\n'+r'\(\mathbf T^{-y}\)：从当前临时前缀中删除 y 后的恢复耗时',6485,200,size=27)
 left('trim','仅更新临时计划\n'+r'\(Y\leftarrow Y\cup\{y\},\quad D_Y\leftarrow D_Y+G_y,\quad f\leftarrow f+b_y\)',6785,150,size=27)
 left('expose','从 Q 移除 y，加入新暴露的可释放尾块\n新尾块沿用剩余余额，进入下一轮版本检查',7035,150,size=28)
 left('bypass','BYPASS：不备份 x\n丢弃临时计划；已有备份、真实余额与 L 保持不变',7500,140,size=28)
 # Side items connected to decisions are exits; the separate top panel is layout only.
 layout(p,2930,810,790)
 p.box('gate-bypass','BYPASS：不做备份\n丢弃临时回收计划',2910,3985,850,130,size=28)
 p.box('retry','状态改变：丢弃临时计划\n从②重新读取输入、当前已有 KV 与账本后重规划',2910,4260,850,130,size=28)
 p.box('copy-failure','分片未齐：等待其余分片\n失败：清理本次分配，重规划\n已经释放的旧备份不视为可回滚',2910,4990,850,190,size=27)
 p.box('pause','内部块 / 固定读取块\n保存 c 与已兑现轮号\n成为可释放尾块时再更新 H',2910,5940,850,160,size=28)
 p.chain('candidate','prefix');p.edge('prefix','wait-prefix',out=(0,.5),into=(1,.5),label='否',label_at=(1285,1030,75,45));p.edge('prefix','inputs',label='是',label_at=(2125,1200,75,45))
 p.chain('inputs','recovery','ordered','dag','shares','priority')
 p.chain('priority','init','fits');p.edge('fits','build-q',out=(0,.5),into=(1,.5),points=[(1410,3475),(1410,3215)],label='否',label_at=(1500,3420,75,45));p.chain('build-q','has-tail');p.edge('fits','admission-rule',label='是',label_at=(2125,3585,75,45));p.chain('admission-rule','accept')
 p.edge('accept','gate-bypass',out=(1,.5),into=(0,.5),label='否',label_at=(2680,4000,75,45));p.edge('accept','validate',label='是',label_at=(2125,4160,75,45))
 p.edge('validate','retry',out=(1,.5),into=(0,.5),label='否',label_at=(2680,4280,75,45));p.edge('validate','release',label='是',label_at=(2125,4435,75,45));p.chain('release','copy','ack')
 p.edge('ack','copy-failure',out=(1,.5),into=(0,.5),label='否',label_at=(2680,5020,75,45));p.edge('ack','grant-value',label='是',label_at=(2125,5200,75,45));p.chain('grant-value','commit','new-tail')
 p.edge('new-tail','publish-key',label='是',label_at=(2125,6140,75,45));p.edge('new-tail','pause',out=(1,.5),into=(0,.5),label='否',label_at=(2690,5960,75,45));p.chain('publish-key','done');p.edge('pause','done',out=(.5,1),into=(1,.5),points=[(3335,6590)])
 p.edge('has-tail','bypass',out=(0,.5),into=(0,.5),points=[(25,3475),(25,7570)],label='否',label_at=(60,3500,75,45));p.edge('has-tail','refresh-inputs',label='是',label_at=(685,3585,75,45))
 p.chain('refresh-inputs','tail-dirty');p.edge('tail-dirty','tail-time',label='是',label_at=(690,4060,75,45));p.edge('tail-dirty','tail-key',out=(1,.5),into=(1,.5),points=[(1280,3965),(1280,5237.5)],label='否',label_at=(1135,3910,75,45));p.chain('tail-time','tail-share','refresh-credit','tail-key','more-tails');p.edge('more-tails','refresh-inputs',out=(0,.5),into=(0,.5),points=[(55,5490),(55,3730)],label='是',label_at=(125,5435,75,45));p.edge('more-tails','collect',label='否',label_at=(690,5590,75,45));p.chain('collect','debit','select-tail','loss','trim','expose')
 p.edge('expose','fits',out=(1,.5),into=(.25,1),points=[(1350,7110),(1350,3610),(1887.5,3610)])
 p.box('footer','设计图：只考虑当前已有 KV 的恢复 WCT；共享收益按固定顺序分账。逐块贪心不保证全局最优；本图不构成部署或性能验证。',65,7820,p.w-130,85,text=True,size=25,align='left')
 return p


def cache_hit():
 p=Flow('cache-hit','3 · Cache hit：续租与 Lazy Refresh',3350,5960);legend(p,True)
 X=930;W=1300
 def main(k,s,y,h=150,**kw):return p.box(k,s,X,y,W,h,**kw)
 main('request','① 新请求开始：只更新该 Agent 的轮号、Slack 与代价引用\n同一轮只登记一次；不遍历全部 KV，不重置任何块的 Credit',780,150,size=28)
 main('candidate','② Agent a 命中一个已有完整 KV chunk x',1040,100,size=29)
 p.box('committed','本 Pool 中已有可恢复的 COMMITTED 副本？',1105,1260,950,170,decision=True,size=27)
 p.box('admit-missing','本 Pool 无副本\n从首个未备份的完整块开始\n按前缀顺序执行第 2 页准入',60,1255,690,175,size=27)
 main('register','③ 核对物理块与前缀版本，登记 Agent a → x\n读取期间固定该分配；引用解除后保留已兑现轮号，防止同轮重新授信',1530,160,size=27)
 p.box('eligible','x 已无备份后继，且没有固定读取？',1105,1800,950,170,decision=True,size=28)
 p.box('defer','Lazy Refresh：先保留余额\n本次只登记引用与当前轮号\n暂不计算 W，不重置 Credit 或 H',60,2075,690,185,size=27)
 p.box('wake','读取完成，或后继删除后\nx 成为可释放尾块\n继续检查当前版本',60,2390,690,170,size=27)
 main('versions','④ 比较全部引用 Agent 的轮号、引用与工作流恢复输入版本\n复制 x 的余额、轮号与 L 到临时账本，并记录版本',2080,145,size=27)
 p.box('changed','首次加入 Q，或有尚未处理的版本变化？',1105,2340,950,170,decision=True,size=27)
 p.box('unchanged','同轮、同版本重复命中\n保留 Credit，不重复续租\n本次完成',2420,2340,850,170,size=28)
 main('recovery',recovery(),2630,270,size=27)
 main('dag',DAG,3270,170,size=27)
 main('ordered',ordered('x'),3000,160,size=27)
 main('shares','⑤ '+joint_and_slack('x'),3530,275,size=26)
 main('priority','按本次恢复收益计算 Agent 优先级\n'+r'\(P_{a,x}=W_{a,x}/b_x\)',3905,130,size=30)
 main('renew','⑥ '+renew('x'),4145,305,size=28)
 main('credit','汇总新的剩余信用与租值键\n'+r'\(\mathrm{Credit}_x=\sum_a c_{a,x},\quad H_x=L+\mathrm{Credit}_x/b_x\)',4550,160,size=30)
 p.box('validate','x 仍可释放，且输入与租金账本版本未变？',1105,4820,950,170,decision=True,size=27)
 main('commit','⑦ 原子写入各 Agent 的余额、已兑现轮号与当前版本\n更新 x 在 Q 中的租值键；本次命中不推进 L、不复制第二份备份',5090,170,size=28)
 main('done','Credit 刷新完成\n其他尚未访问或参与收租的 KV 继续保留待刷新状态',5420,140,size=28)
 p.box('restart','状态已变化\n丢弃本次计算结果\n从③读取当前引用与版本重试',2420,4810,850,180,size=28)
 layout(p,2450,820,790,hit=True)
 p.chain('request','candidate','committed');p.edge('committed','admit-missing',out=(0,.5),into=(1,.5),label='否',label_at=(790,1290,75,45));p.edge('committed','register',label='是',label_at=(1610,1455,75,45));p.chain('register','eligible')
 p.edge('eligible','defer',out=(0,.5),into=(.5,0),points=[(405,1885)],label='否',label_at=(805,1830,75,45));p.edge('eligible','versions',label='是',label_at=(1610,1995,75,45));p.chain('defer','wake');p.edge('wake','versions',out=(1,.5),into=(0,.5),points=[(860,2475),(860,2152.5)])
 p.chain('versions','changed');p.edge('changed','unchanged',out=(1,.5),into=(0,.5),label='否',label_at=(2250,2370,75,45));p.edge('changed','recovery',label='是',label_at=(1610,2540,75,45));p.chain('recovery','ordered','dag','shares','priority')

 p.chain('priority','renew','credit','validate');p.edge('validate','restart',out=(1,.5),into=(0,.5),label='否',label_at=(2250,4850,75,45));p.edge('validate','commit',label='是',label_at=(1610,5020,75,45));p.chain('commit','done')
 p.box('footer','命中是引用与刷新事件，不额外增加命中收益。同一轮重复命中不补信用；只有对应 Agent 的新轮资格可以续租，其他 Agent 不返还已付租金。',65,5760,p.w-130,120,text=True,size=25,align='left')
 return p


def write():
 if not BASE.exists():
  assert hashfile(SOURCE)==BASE_HASH,'Preserve new manual changes before running this builder.'
  BASE.write_bytes(SOURCE.read_bytes())
 old=json.loads((OUT/'MANIFEST.json').read_text())
 accepted={BASE_HASH,old.get('output_sha256',{}).get(SOURCE.name)}
 assert hashfile(SOURCE) in accepted,'Manual edits detected; incorporate them first.'
 book=E.Element('mxfile',host='app.diagrams.net',version='31.1.5')
 book.append(deepcopy(E.parse(BASE).find("diagram[@id='agents']")))
 flows=[admission(),cache_hit()];checks={p.key:p.validate() for p in flows}
 for p in flows:book.append(p.d)
 E.indent(book);E.ElementTree(book).write(SOURCE,encoding='utf-8',xml_declaration=True)
 for p,stem in [(flows[0],'algorithm-2-admission'),(flows[1],'algorithm-2-cache-hit')]:
  b=E.Element('mxfile',host='app.diagrams.net',version='31.1.5');b.append(deepcopy(p.d));E.indent(b);E.ElementTree(b).write(OUT/(stem+'.drawio'),encoding='utf-8',xml_declaration=True)
 old.update(status='COMPLETE_DECISION_FLOWS_DESIGN_NOT_DEPLOYED',date='2026-09-08',previous_diagram={'path':str(BASE),'sha256':hashfile(BASE)},pages={'agents':old['pages']['agents'],**checks},visual_review='PENDING',export_checks='PENDING')
 old['output_sha256']={SOURCE.name:hashfile(SOURCE)}
 old['decision_flow_revision']={'new_chunk':'all recovery/share/lease/rental/admission/commit steps connected in page 2','cache_hit':'page 3; hit records references; safe tail refresh on access; pending internal/pinned blocks settle on exposure','symbol':'Q only','scope':'native design diagrams; no production or CPU policy changes','side_panels':'KV record and physical layout only; connected branches are executable steps'}
 old['generator_components_sha256']['build_decision_flows.py']=hashfile(Path(__file__))
 old['manual_edits_incorporated']='Previous reviewed 8f438d425dc7 source preserved; page 1 unchanged; pages 2 and 3 rebuilt with online known-work recovery and a single WCT attribution path.'
 (OUT/'MANIFEST.json').write_text(json.dumps(old,ensure_ascii=False,indent=2)+'\n')
 print('Written 3 native pages and 2 standalone editable decision flows.',flush=True)

def export_standalones(render=True):
 import subprocess
 import pymupdf
 from PIL import Image
 from urllib.parse import quote,unquote
 record=json.loads((OUT/'MANIFEST.json').read_text())
 for stem in ['algorithm-2-admission','algorithm-2-cache-hit']:
  source=OUT/(stem+'.drawio')
  if render:
   for fmt in ['png','pdf']:
    command=[native.CLI,'-x','-f',fmt,'-e','-b','0','-o',str(source)+'.'+fmt,str(source)]
    if fmt=='pdf':command.insert(1,'--crop')
    subprocess.run(command,check=True)
  with pymupdf.open(str(source)+'.pdf') as doc:
   assert len(doc)==1
   assert not any(t in doc[0].get_text() for t in [r'\(',r'\begin',r'\mathrm'])
   for block in doc[0].get_text('blocks'):assert doc[0].rect.contains(pymupdf.Rect(block[:4]))
   meta={k:v for k,v in doc.metadata.items() if k not in ['format','encryption']}
   meta.update(subject=quote(source.read_text(),safe=''))
   doc.set_metadata(meta);doc.saveIncr()
   assert unquote(doc.metadata['subject'])==source.read_text()
  with Image.open(str(source)+'.png') as im:
   embedded=E.fromstring(unquote(im.info['mxGraphModel']))
   assert [c.attrib for c in embedded.iter('mxCell')]==[c.attrib for c in E.parse(source).iter('mxCell')]
  for suffix in ['', '.png','.pdf']:
   f=Path(str(source)+suffix);record['output_sha256'][f.name]=hashfile(f)
 record['export_checks']['standalone_sources_embedded']='PASS'
 (OUT/'MANIFEST.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--xml-only',action='store_true');args=parser.parse_args();write()
 if not args.xml_only:
  native.export();export_standalones()
