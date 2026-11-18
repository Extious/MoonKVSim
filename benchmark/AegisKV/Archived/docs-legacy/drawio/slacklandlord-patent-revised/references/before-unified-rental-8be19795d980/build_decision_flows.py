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
BASE=OUT/'references/before-gain-credit-audit-06f9e9e4d5ea-algorithm-2-patent-revised.drawio'
BASE_HASH='06f9e9e4d5eaef238f27f984559f5af4165f0a0e3476ad84b30131b29211af25'
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
 p.box('title','SlackLandlord  ·  '+('Cache hit：收益评估与 Credit 续租' if hit else '新 chunk：收益评估、准入与 Credit 授信'),60,25,p.w-120,80,size=40,text=True,bold=True,align='left')
 p.box('subtitle','复用完整备份前缀；只计已生成 KV 的恢复 WCT。先评估收益，再分配授信额度。',60,115,p.w-120,65,size=27,text=True,align='left')
 p.box('symbols-title','符号说明',60,210,p.w-120,65,size=31,text=True,bold=True,align='left')
 rows=[
 r'\(x\)：本次物理块；\(y\)：待淘汰尾块；\(a\)：Agent；\(s_a\)：本轮 Slack；\(b_x,b_y\)：实际物理字节数',
 r'\(T_a(k)\)：Agent a 已备份前 k 块时的恢复时间；\(k_a\)：待评估块之前的连续备份块数',
 r'\(G_x\)：块的总 WCT 收益；\(P_x=G_x/b_x\)：收益密度；\(W_{a,x}\)：分给 Agent 的授信额度',
 r'\(c_{a,x}\)：Agent 剩余信用；\(\mathrm{Credit}_x=\sum_a c_{a,x}\)；\(H_x\)：尾块租值键；\(L,\delta\)：累计租金、本次增量',
 r'\(Q\)：可释放尾块队列；\(Y\)：计划淘汰块；\(f\)：计划可用字节；\(D_Y\)：累计删除损失',
 r'\(w\gets x\)：引用 x 的工作流；\(v,u\)：DAG 节点；\(d_v,t_v\)：正常耗时、完成时间；\(\mathbf T\)：节点恢复耗时；\(\max\varnothing=0\)']
 if hit:
  rows[0]=r'\(x\)：命中的物理块；\(a\)：Agent；\(s_a\)：本轮 Slack；\(b_x\)：实际物理字节数'
  rows[2]=r'\(G_x\)：保留 x 的总 WCT 收益；\(W_{a,x}\)：分给 Agent 的授信额度；不用于决定此次命中是否准入'
  rows[3]=r'\(c_{a,x}\)：Agent 剩余信用；\(\mathrm{Credit}_x=\sum_a c_{a,x}\)；\(H_x\)：尾块租值键；\(L\)：累计租金'
  rows[4]=r'\(Q\)：可释放尾块队列；已兑现轮号：该 Agent 对本块最近一次完成授信或续租的请求轮号'
 for i,line in enumerate(rows):p.box('symbols-'+str(i),line,75,290+i*65,p.w-150,62,size=26,text=True,align='left')


def recovery():
 return (r'\(T_a(k)\)：Agent a 已备份前 k 块时的恢复时间'+'\n'+r'不使用 x：\(T_a(k_a)\)；使用 x：\(T_a(k_a+1)\)')


def benefits(hit=False):
 return ('收益评估：每个工作流只计算一次\n'+r'\(\mathbf T\)：相关引用不使用 x；\(\mathbf T^x\)：相关引用均使用 x；其他节点不变'+'\n'+r'\(t_v=d_v+T_v+\max_{u\to v}t_u,\quad\mathrm{WCT}_w=\max_{v\in w}t_v\)'+'\n'+r'\(G_x=\sum_{w\gets x}[\mathrm{WCT}_w(\mathbf T)-\mathrm{WCT}_w(\mathbf T^x)]\)'+('' if hit else r'，\(P_x=G_x/b_x\)')+'\n'+r'单工作流、单 Agent 恢复：\(G_x=\min\{T_a(k_a)-T_a(k_a+1),\max(T_a(k_a)-s_a,0)\}\)')


def allocation(new=False):
 return ('Credit 分账：'+('按发布时的实际前缀重算收益，再分配额度' if new else '将本次收益分配为 Agent 授信额度')+'\n'+r'固定 Agent ID 顺序；\(\mathbf T^{(i)}\)：前 i 个 Agent 使用 x，其余不用'+'\n'+r'\(W_{a_i,x}=\sum_{w\gets x}[\mathrm{WCT}_w(\mathbf T^{(i-1)})-\mathrm{WCT}_w(\mathbf T^{(i)})]\)'+'\n'+r'\(\sum_a W_{a,x}=G_x\)；顺序只用于分账；尾块刷新时将 x 换为 y')


def renewal(symbol):
 return rf'\(c_{{a,{symbol}}}\leftarrow\begin{{cases}}0,&\text{{Agent 结束或引用解除}};\\W_{{a,{symbol}}},&\text{{首次授信或新轮尚未兑现}};\\\min(c_{{a,{symbol}}},W_{{a,{symbol}}}),&\text{{本轮已兑现}}.\end{{cases}}\)'


def layout(p,x,y,w=790,hit=False):
 p.box('layout-title','KV 引用与 Peer HBM 布局',x,y,w,60,text=True,bold=True,size=30)
 p.box('layout-card',('共享内部块 x' if hit else '共享块 P1')+'\nAgent 1 → 本轮 Slack\nAgent 2 → 本轮 Slack\n'+(r'\(b_x\)：实际 bytes；内容：4096 tokens' if hit else r'\(b_{P1}\)：实际 bytes；内容：4096 tokens'),x,y+80,w,200,size=27)
 for row,yy,keys in [('a',y+330,['x','A2','A3'] if hit else ['P1','A2','x']),('b',y+450,['x','B2'] if hit else ['P1','B2'])]:
  p.box('layout-agent-'+row,'Agent '+('1' if row=='a' else '2'),x,yy,180,70,text=True,size=26)
  for i,k in enumerate(keys):
   name=f'layout-{row}-{i}';p.box(name,k,x+205+i*185,yy,155,70,size=27)
   if i:p.edge(f'layout-{row}-{i-1}',name,out=(1,.5),into=(0,.5))
 p.box('layout-pool-title','Pool · 共享块只占一份空间',x,y+560,w,60,text=True,size=27)
 for i,k in enumerate(['x','A2','A3','B2','C1','空闲'] if hit else ['P1','A2','B2','C1','C2','空闲']):
  p.box('layout-slot-'+str(i),k,x+(i%3)*260,y+650+(i//3)*100,235,75,size=27)


def admission():
 p=Flow('flow','2 · 新 chunk：先评估收益，再授信',3820,4540);legend(p)
 def main(k,t,y,h=150,**kw):return p.box(k,t,1450,y,1300,h,**kw)
 def left(k,t,y,h=150,**kw):return p.box(k,t,80,y,1160,h,**kw)
 main('candidate',r'完整新块 x（Agent a 的第 \(k_a+1\) 块）到来，按前缀顺序决策'+'\n已备份则转第 3 页；复制中则合并事件，不重复分配',770,140,size=27)
 p.box('prefix','必要前缀已提交，且源完整可读？',1640,1010,920,130,decision=True,size=27)
 left('wait-prefix','本轮不备份 x 及后续块',1010,130,size=28)
 main('recovery','读取引用 Agent 的 Slack、轮号与代价版本\n'+recovery(),1240,150,size=26)
 main('benefits',benefits(),1480,280,size=25)
 main('init','建立临时账本，保护 x 的前缀；试算中将 x 视为可恢复\n'+r'\(Y\leftarrow\varnothing,\quad D_Y\leftarrow0,\quad f\leftarrow\text{Pool 可用字节}\)',1850,145,size=27)
 p.box('fits','容量足够？\n'+r'\(f\ge b_x\)',1675,2090,850,150,decision=True,size=28)
 main('admission-rule',r'\(\begin{cases}G_x\ge0,&Y=\varnothing\quad\text{无需淘汰};\\[2mm]G_x>D_Y,&Y\ne\varnothing\quad\text{需要淘汰}.\end{cases}\)',2350,160,size=29)
 p.box('accept','满足准入条件？',1675,2600,850,130,decision=True,size=28)
 p.box('validate','输入、容量、读取与账本版本仍有效？',1640,2820,920,130,decision=True,size=27)
 main('copy','锁定分配代次，提交回收计划与临时账本\n释放 Y 并等待 ACK，再原子检查容量、分配并复制 x\nY 为空则跳过释放；分配或复制失败走清理分支',3040,180,size=26)
 p.box('ack','本次分配的全部分片成功且提交条件有效？',1640,3320,920,140,decision=True,size=26)
 main('allocation',allocation(new=True),3560,255,size=25)
 main('commit','同一分配代次仅发布一次；原子核验并初始化信用\n'+r'\(c_{a,x}=W_{a,x},\quad\mathrm{Credit}_x=\sum_a c_{a,x}=G_x\)'+'\n'+r'可释放尾块：\(H_x=L+\mathrm{Credit}_x/b_x\)'+'\n记录已兑现轮号与分配代次；更新 Q',3910,225,size=26)
 main('done','备份完成，处理下一个完整 chunk',4240,80,size=28)
 left('build-q','更新 Q：已提交、无后继、可释放的物理尾块\n排除 x、受保护前缀、读取中及释放中的块',1890,140,size=27)
 p.box('has-tail','有可释放尾块？\n'+r'\(Q\ne\varnothing\)',235,2140,850,140,decision=True,size=28)
 left('refresh-credit','Lazy Refresh：逐个检查全部 Q，结果写临时账本\n引用、轮号或价值版本变化：按 Credit 分账框计算当前额度（x 换为 y）\n'+renewal('y')+'\n'+r'\(\mathrm{Credit}_y=\sum_a c_{a,y},\quad H_y=L+\mathrm{Credit}_y/b_y\)'+'\n兑现时记录当前轮号；未变则保留余额\n所有尾块均按当前 L 更新 H；保留已兑现轮号',2380,350,size=25)
 left('debit','对 Q 收租：每个物理块一份，按余额分摊\n'+r'\(\delta=\min_{y\in Q}(H_y-L)\)'+'\n'+r'\(c_{a,y}\leftarrow c_{a,y}\left(1-\frac{b_y\delta}{\mathrm{Credit}_y}\right),\quad y\in Q\)'+'\n'+r'\(\mathrm{Credit}_y\leftarrow\sum_a c_{a,y},\quad L\leftarrow L+\delta\)'+'\n零余额跳过除法；全 Q 扣租后仅推进一次 L',2840,240,size=26)
 left('loss','选 Credit = 0 的尾块 y；按当前临时前缀计算删除损失\n'+r'\(G_y=\sum_{w\gets y}[\mathrm{WCT}_w(\mathbf T^{-y})-\mathrm{WCT}_w(\mathbf T)]\)'+'\n'+r'\(\mathbf T^{-y}\)：删除 y 后的恢复状态；同值按物理块 ID 选择',3190,180,size=26)
 left('trim','更新临时计划与 Q，再检查容量\n'+r'\(Y\leftarrow Y\cup\{y\},\quad D_Y\leftarrow D_Y+G_y,\quad f\leftarrow f+b_y\)'+'\n移除 y；新暴露尾块保留余额，重新检查价值版本',3480,180,size=26)
 left('bypass','不备份 x；丢弃临时计划\n不修改真实余额、已兑现轮号或已有备份',4080,140,size=27)
 layout(p,2930,770)
 p.box('gate-bypass','不备份 x\n丢弃临时计划',2910,2590,850,150,size=27)
 p.box('retry','丢弃临时计划\n重新读取输入后重试',2910,2810,850,150,size=27)
 p.box('copy-failure','分片未齐则等待；失败则清理本次分配\n旧分配的 ACK 忽略；已释放的备份不回滚\n重新规划，未成功发布不初始化 x 的 Credit',2910,3310,850,190,size=26)
 p.chain('candidate','prefix');p.edge('prefix','wait-prefix',out=(0,.5),into=(1,.5),label='否',label_at=(1300,1030,75,45));p.edge('prefix','recovery',label='是',label_at=(2125,1165,75,45));p.chain('recovery','benefits','init','fits')
 p.edge('fits','build-q',out=(0,.5),into=(1,.5),points=[(1410,2165),(1410,1960)],label='否',label_at=(1500,2110,75,45));p.chain('build-q','has-tail')
 p.edge('fits','admission-rule',label='是',label_at=(2125,2260,75,45));p.chain('admission-rule','accept');p.edge('accept','gate-bypass',out=(1,.5),into=(0,.5),label='否',label_at=(2680,2610,75,45));p.edge('accept','validate',label='是',label_at=(2125,2750,75,45))
 p.edge('validate','retry',out=(1,.5),into=(0,.5),label='否',label_at=(2680,2830,75,45));p.edge('validate','copy',label='是',label_at=(2125,2970,75,45));p.chain('copy','ack');p.edge('ack','copy-failure',out=(1,.5),into=(0,.5),label='否',label_at=(2680,3340,75,45));p.edge('ack','allocation',label='是',label_at=(2125,3480,75,45));p.chain('allocation','commit');p.edge('commit','done',label='成功',label_at=(2125,4160,100,45))
 p.edge('commit','allocation',out=(1,.5),into=(1,.5),points=[(2840,4022.5),(2840,3687.5)],label='输入变化：重算',label_at=(2870,3960,280,60))
 p.edge('commit','copy-failure',out=(1,.85),into=(1,.5),points=[(3790,4101.25),(3790,3405)],label='副本失效：清理',label_at=(3290,4140,390,55))
 p.edge('has-tail','bypass',out=(0,.5),into=(0,.5),points=[(25,2210),(25,4150)],label='否',label_at=(70,2235,75,45));p.edge('has-tail','refresh-credit',label='是',label_at=(690,2300,75,45));p.chain('refresh-credit','debit','loss','trim')
 p.edge('trim','fits',out=(1,.5),into=(.15,1),points=[(1340,3570),(1340,2290),(1802.5,2290)])
 p.box('footer','收益 G 决定是否值得替换；剩余 Credit 决定收租顺序。授信分账仅在初始化或刷新信用时计算。',65,4400,p.w-130,70,text=True,size=25,align='left')
 return p


def cache_hit():
 p=Flow('cache-hit','3 · Cache hit：按需评估与独立续租',3350,4100);legend(p,True)
 def main(k,t,y,h=150,**kw):return p.box(k,t,930,y,1300,h,**kw)
 main('request','新请求只更新该 Agent 的新轮号、Slack 与代价；不遍历 KV\n重复、旧轮号不覆盖当前输入；逐个处理命中的完整块 x',770,140,size=27)
 p.box('committed','本 Pool 已有可恢复副本？',1105,1010,950,130,decision=True,size=28)
 p.box('admit-missing','已有复制则合并事件；否则\n从首个未备份块执行第 2 页准入',60,1000,690,155,size=26)
 main('register','登记 Agent → x；读取期间固定该分配\n解除引用仍保留已兑现轮号，防止同轮重复授信',1230,110,size=27)
 p.box('eligible','x 无备份后继，且没有固定读取？',1105,1430,950,130,decision=True,size=27)
 p.box('defer','Lazy Refresh：保存余额，退出 Q\n成为可释放尾块时继续',60,1650,690,150,size=27)
 main('snapshot','读取引用、Agent 轮号、恢复输入及账本版本\n复制余额、已兑现轮号和当前 L 到临时账本',1650,120,size=27)
 p.box('changed','引用、轮号或价值输入版本变化？',1105,1870,950,130,decision=True,size=27)
 main('benefits',benefits(hit=True),2110,280,size=25)
 main('allocation',allocation(),2480,225,size=25)
 main('renew','在临时账本中按 Agent 更新剩余信用\n'+renewal('x')+'\n兑现时记录当前轮号；不补回其他 Agent 已付租金',2800,225,size=26)
 main('key','无论是否重算收益，均按当前 L 更新租值键\n'+r'\(\mathrm{Credit}_x=\sum_a c_{a,x},\quad H_x=L+\mathrm{Credit}_x/b_x\)'+'\n同轮同版本保留余额与已兑现轮号',3120,155,size=27)
 p.box('validate','原子核验并写入账本、Q 成功？\nx 可释放，输入、分配代次与账本版本有效',1105,3370,950,160,decision=True,size=26)
 main('done','余额、已兑现轮号与 Q 已更新，本次刷新结束\n本次不推进 L，不增加物理副本',3660,130,size=27)
 p.box('restart','丢弃临时结果\n重新读取当前引用与版本后重试',2420,3370,850,160,size=27)
 layout(p,2450,770,hit=True)
 p.chain('request','committed');p.edge('committed','admit-missing',out=(0,.5),into=(1,.5),label='否',label_at=(790,1020,75,45));p.edge('committed','register',label='是',label_at=(1610,1160,75,45));p.chain('register','eligible')
 p.edge('eligible','defer',out=(0,.5),into=(.5,0),points=[(405,1495)],label='否',label_at=(805,1450,75,45));p.edge('eligible','snapshot',label='是',label_at=(1610,1575,75,45));p.edge('defer','snapshot',out=(1,.5),into=(0,.5));p.chain('snapshot','changed')
 p.edge('changed','key',out=(1,.5),into=(1,.5),points=[(2330,1935),(2330,3197.5)],label='否：保留信用，更新 H',label_at=(2370,1880,530,60));p.edge('changed','benefits',label='是',label_at=(1610,2020,75,45));p.chain('benefits','allocation','renew','key','validate')
 p.edge('validate','restart',out=(1,.5),into=(0,.5),label='否',label_at=(2250,3390,75,45));p.edge('validate','done',label='是',label_at=(1610,3570,75,45))
 p.box('footer','G 是当前收益，W 是本轮授信额度，Credit 是剩余余额。命中不等于续租；重入 Q 不等于重新授信。',65,3970,p.w-130,80,text=True,size=25,align='left')
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
 old['manual_edits_incorporated']='Manual 06f9e9e4d5ea source archived; page 1 and the user recovery-time definition preserved. Total gain, grant allocation and remaining credit are now separate stages.'
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
