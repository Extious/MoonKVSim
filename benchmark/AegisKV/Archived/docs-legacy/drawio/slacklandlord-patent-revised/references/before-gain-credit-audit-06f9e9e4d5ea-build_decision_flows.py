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
BASE=OUT/'references/before-compact-reuse-88112af84cd5-algorithm-2-patent-revised.drawio'
BASE_HASH='88112af84cd5fdec50f2affcbbd1f2ac097ef6947bc05474423f57442d3ad099'
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
 p.box('subtitle','恢复方式：复用全部可用前缀，再重算剩余已生成 KV；收益只按 WCT 计价。',60,115,p.w-120,65,size=27,text=True,align='left')
 p.box('symbols-title','符号说明',60,210,p.w-120,65,size=31,text=True,bold=True,align='left')
 rows=[
 r'\(x\)：本次处理的物理块；\(y\)：待淘汰尾块；\(a\)：Agent；\(s_a\)：本轮 Slack；\(b_x,b_y\)：物理字节数',
 r'\(k\)：连续备份块数；\(k_a\)：待评估块之前的连续备份块数；\(t_a^{\rm reuse}(k)\)：复用前 k 块；\(t_a^{\rm recompute}(k)\)：重算其余已生成 KV',
 r'\(T_a(k_a),T_a(k_a+1)\)：不用 / 使用待评估块的恢复时间；\(W_{a,x}\)：Agent 的 WCT 收益份额；\(P_{a,x}=W_{a,x}/b_x\)',
 r'\(c_{a,x}\)：Agent 剩余信用；\(\mathrm{Credit}_x=\sum_a c_{a,x}\)；\(H_x\)：尾块租值键；\(L\)：累计租金；\(\delta\)：本次收租增量',
 r'\(Q\)：本次决策的可释放尾块优先队列；\(Y\)：计划淘汰的块；\(f\)：计划可用字节；\(G_x,D_Y\)：加入收益、累计回收损失',
 r'\(w\)：工作流；\(v,u\)：DAG 节点；\(d_v,t_v\)：正常耗时、完成时间；\(\mathbf T\)：各节点恢复耗时，未受影响节点为 0；\(\max\varnothing=0\)']
 if hit:
  rows[0]=r'\(x\)：本次命中的物理块；\(a\)：Agent；\(s_a\)：本轮 Slack；\(b_x\)：实际物理字节数'
  rows[3]=r'\(c_{a,x}\)：Agent 剩余信用；\(\mathrm{Credit}_x=\sum_a c_{a,x}\)；\(H_x\)：尾块租值键；\(L\)：累计租金'
  rows[4]=r'\(Q\)：可释放尾块优先队列；已兑现轮号：该 Agent 对本块最近一次完成授信或续租的请求轮号'
 for i,s in enumerate(rows):p.box('symbols-'+str(i),s,75,290+i*65,p.w-150,62,size=26,text=True,align='left')

def recovery(symbol='x',new=False):
 compare=(rf'备份 {symbol} 前：\(T_a(k_a)\)；备份后：\(T_a(k_a+1)\)' if new else rf'不保留 {symbol}：\(T_a(k_a)\)；保留 {symbol}：\(T_a(k_a+1)\)')
 return (r'\(T_a(k)=t_a^{\rm reuse}(k)+t_a^{\rm recompute}(k)\)'+'\n'+compare)


def benefits(symbol='x',hit=False):
 return ('按固定 Agent ID 顺序计算 WCT 收益并分账\n'+rf'\(\mathbf T^{{(i)}}\)：前 i 个引用使用 {symbol}，其余引用不用；其他节点不变'+'\n'+rf'\(w\gets {symbol}\)：引用 {symbol} 的工作流；\(\mathbf T^{{(0)}}\)：所有引用均不用 {symbol}'+'\n'+r'\(t_v=d_v+T_v+\max_{u\to v}t_u,\quad\mathrm{WCT}_w=\max_{v\in w}t_v\)'+'\n'+rf'\(W_{{a_i,{symbol}}}=\sum_{{w\gets {symbol}}}[\mathrm{{WCT}}_w(\mathbf T^{{(i-1)}})-\mathrm{{WCT}}_w(\mathbf T^{{(i)}})]\)'+'\n'+rf'仅单 Agent 恢复：\(W_{{a,{symbol}}}=\min\{{T_a(k_a)-T_a(k_a+1),\max(T_a(k_a)-s_a,0)\}}\)'+'\n'+rf'\(P_{{a,{symbol}}}=W_{{a,{symbol}}}/b_{symbol}\)'+('' if hit else rf'，\(G_{symbol}=\sum_a W_{{a,{symbol}}}\)'))


def renewal(symbol):
 return rf'\(c_{{a,{symbol}}}\leftarrow\begin{{cases}}0,&\text{{Agent 结束或引用解除}};\\W_{{a,{symbol}}},&\text{{首次引用或新轮尚未兑现}};\\\min(c_{{a,{symbol}}},W_{{a,{symbol}}}),&\text{{本轮已兑现}}.\end{{cases}}\)'


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
 p=Flow('flow','2 · 新 chunk：准入与尾块收租',3820,4360);legend(p)
 def main(k,s,y,h=150,**kw):return p.box(k,s,1450,y,1300,h,**kw)
 def left(k,s,y,h=150,**kw):return p.box(k,s,80,y,1160,h,**kw)
 main('candidate','新的完整 KV chunk x 到来；按前缀顺序逐块决策',770,100,size=28)
 p.box('prefix','前缀均已准入？',1640,970,920,130,decision=True,size=28)
 left('wait-prefix','本轮不备份 x 及后续块',970,130,size=28)
 main('recovery','读取引用 Agent 的 Slack、轮号、代价与版本\n'+recovery(new=True),1200,170,size=27)
 main('benefits',benefits(),1470,350,size=26)
 main('init','建立临时账本，保护 x 的前缀；试算中将 x 视为可恢复\n'+r'\(Y\leftarrow\varnothing,\quad D_Y\leftarrow0,\quad f\leftarrow\text{Pool 可用字节}\)',1930,160,size=27)
 p.box('fits','容量足够？\n'+r'\(f\ge b_x\)',1675,2190,850,150,decision=True,size=28)
 main('admission-rule',r'\(\begin{cases}G_x\ge0,&Y=\varnothing\quad\text{无需淘汰};\\[2mm]G_x>D_Y,&Y\ne\varnothing\quad\text{需要淘汰}.\end{cases}\)',2450,170,size=29)
 p.box('accept','满足准入条件？',1675,2720,850,130,decision=True,size=28)
 p.box('validate','输入、容量、读取与账本版本仍有效？',1640,2950,920,130,decision=True,size=27)
 main('copy','提交临时账本；释放 Y 并等待释放 ACK\n分配空间，复制 x 的全部分片\nY 为空时直接分配',3180,170,size=27)
 p.box('ack','全部分片成功且提交条件有效？',1640,3450,920,140,decision=True,size=27)
 main('commit','按当前前缀重算 W，原子核验版本并发布 COMMITTED\n'+r'\(c_{a,x}=W_{a,x},\quad\mathrm{Credit}_x=\sum_a c_{a,x}\)'+'\n'+r'\(H_x=L+\mathrm{Credit}_x/b_x\)'+'\n记录已兑现轮号；仅可释放尾块加入 Q',3710,240,size=27)
 main('done','备份完成，处理下一个完整 chunk',4070,80,size=28)
 left('build-q','更新 Q：已提交、无后继、可释放的尾块\n排除 x、受保护前缀与读取中的块',1990,140,size=27)
 p.box('has-tail','有可释放尾块？\n'+r'\(Q\ne\varnothing\)',235,2240,850,140,decision=True,size=28)
 left('refresh-credit','Lazy Refresh：检查全部 Q，结果先写临时账本\n新暴露或版本变化：按上方收益式（x 换为 y）重算 W\n'+renewal('y')+'\n'+r'\(\mathrm{Credit}_y=\sum_a c_{a,y},\quad H_y=L+\mathrm{Credit}_y/b_y\)'+'\n版本未变则保留余额；已兑现轮号保留去重',2480,320,size=26)
 left('debit','对 Q 收租：每个物理块一份，按余额分摊\n'+r'\(\delta=\min_{y\in Q}(H_y-L)\)'+'\n'+r'\(c_{a,y}\leftarrow c_{a,y}\left(1-\frac{b_y\delta}{\mathrm{Credit}_y}\right),\quad y\in Q\)'+'\n'+r'\(\mathrm{Credit}_y\leftarrow\sum_a c_{a,y},\quad L\leftarrow L+\delta\)'+'\n零余额跳过除法；全 Q 扣租后仅推进一次 L',2910,240,size=26)
 left('loss','选择 Credit = 0 的尾块 y，计算当前删除损失\n'+r'\(G_y=\sum_{w\gets y}[\mathrm{WCT}_w(\mathbf T^{-y})-\mathrm{WCT}_w(\mathbf T)]\)'+'\n'+r'\(\mathbf T^{-y}\)：从当前临时前缀删除 y；同值按块 ID 选择',3260,190,size=26)
 left('trim','更新临时计划与 Q，再检查容量\n'+r'\(Y\leftarrow Y\cup\{y\},\quad D_Y\leftarrow D_Y+G_y,\quad f\leftarrow f+b_y\)'+'\n移除 y，加入新暴露尾块；新尾块保留剩余余额',3560,190,size=26)
 left('bypass','不备份 x；丢弃临时计划\n已有备份、真实余额与 L 不变',4020,130,size=27)
 layout(p,2930,770)
 p.box('gate-bypass','不备份 x\n丢弃临时计划',2910,2710,850,150,size=27)
 p.box('retry','丢弃临时计划\n重新读取输入后重试',2910,2940,850,150,size=27)
 p.box('copy-failure','分片未齐则等待；失败则清理本次分配\n已释放的旧备份不回滚，重新决策\n发布前版本变化则重新核验',2910,3445,850,170,size=26)
 p.chain('candidate','prefix');p.edge('prefix','wait-prefix',out=(0,.5),into=(1,.5),label='否',label_at=(1300,990,75,45));p.edge('prefix','recovery',label='是',label_at=(2125,1125,75,45));p.chain('recovery','benefits','init','fits')
 p.edge('fits','build-q',out=(0,.5),into=(1,.5),points=[(1410,2265),(1410,2060)],label='否',label_at=(1500,2210,75,45));p.chain('build-q','has-tail')
 p.edge('fits','admission-rule',label='是',label_at=(2125,2370,75,45));p.chain('admission-rule','accept');p.edge('accept','gate-bypass',out=(1,.5),into=(0,.5),label='否',label_at=(2680,2730,75,45));p.edge('accept','validate',label='是',label_at=(2125,2875,75,45))
 p.edge('validate','retry',out=(1,.5),into=(0,.5),label='否',label_at=(2680,2960,75,45));p.edge('validate','copy',label='是',label_at=(2125,3105,75,45));p.chain('copy','ack');p.edge('ack','copy-failure',out=(1,.5),into=(0,.5),label='否',label_at=(2680,3470,75,45));p.edge('ack','commit',label='是',label_at=(2125,3620,75,45));p.chain('commit','done')
 p.edge('has-tail','bypass',out=(0,.5),into=(0,.5),points=[(25,2310),(25,4085)],label='否',label_at=(70,2335,75,45));p.edge('has-tail','refresh-credit',label='是',label_at=(690,2405,75,45));p.chain('refresh-credit','debit','loss','trim')
 p.edge('trim','fits',out=(1,.5),into=(.15,1),points=[(1340,3655),(1340,2390),(1802.5,2390)])
 p.box('footer','本图采用复用完整备份前缀的恢复模型。临时计划通过核验后才提交；实现细节见同目录说明。',65,4250,p.w-130,60,text=True,size=25,align='left')
 return p


def cache_hit():
 p=Flow('cache-hit','3 · Cache hit：续租与 Lazy Refresh',3350,3820);legend(p,True)
 def main(k,s,y,h=150,**kw):return p.box(k,s,930,y,1300,h,**kw)
 main('request','新请求更新 Agent 的 Slack、轮号与代价；不遍历 KV\n逐个处理命中的完整块 x',770,140,size=28)
 p.box('committed','本 Pool 已有可恢复副本？',1105,1010,950,130,decision=True,size=28)
 p.box('admit-missing','从首个未备份块开始\n执行第 2 页准入',60,1000,690,150,size=27)
 main('register','登记 Agent → x；读取期间固定该分配\n保留已兑现轮号，防止同轮重复授信',1240,110,size=27)
 p.box('eligible','x 无备份后继，且没有固定读取？',1105,1440,950,140,decision=True,size=27)
 p.box('defer','Lazy Refresh：保留余额\n等待成为可释放尾块后继续',60,1665,690,170,size=27)
 p.box('changed','首次加入 Q，或输入版本已变化？',1105,1680,950,140,decision=True,size=27)
 p.box('unchanged','保留 Credit，本次结束\n同轮重复命中不补信用',2420,1680,850,150,size=27)
 main('recovery','读取全部引用的当前版本，建立临时账本\n'+recovery(),1920,145,size=26)
 main('benefits',benefits(hit=True),2165,350,size=26)
 main('renew','在临时账本中按 Agent 续租\n'+renewal('x')+'\n同轮已兑现只保留或下调；解除引用仍保留去重记录',2625,220,size=27)
 p.box('validate','x 仍可释放，且输入与账本版本未变？',1105,2945,950,140,decision=True,size=27)
 main('commit','原子写入余额、已兑现轮号，更新 Q\n'+r'\(\mathrm{Credit}_x=\sum_a c_{a,x},\quad H_x=L+\mathrm{Credit}_x/b_x\)'+'\n本次不推进 L，不复制额外备份',3185,185,size=27)
 main('done','本次刷新完成；其他块继续按需刷新',3470,80,size=28)
 p.box('restart','丢弃临时结果\n重新核对引用与版本后重试',2420,2940,850,150,size=27)
 layout(p,2450,770,hit=True)
 p.chain('request','committed');p.edge('committed','admit-missing',out=(0,.5),into=(1,.5),label='否',label_at=(790,1020,75,45));p.edge('committed','register',label='是',label_at=(1610,1160,75,45));p.chain('register','eligible')
 p.edge('eligible','defer',out=(0,.5),into=(.5,0),points=[(405,1510)],label='否',label_at=(805,1460,75,45));p.edge('eligible','changed',label='是',label_at=(1610,1605,75,45));p.edge('defer','changed',out=(1,.5),into=(0,.5))
 p.edge('changed','unchanged',out=(1,.5),into=(0,.5),label='否',label_at=(2250,1700,75,45));p.edge('changed','recovery',label='是',label_at=(1610,1840,75,45));p.chain('recovery','benefits','renew','validate')
 p.edge('validate','restart',out=(1,.5),into=(0,.5),label='否',label_at=(2250,2960,75,45));p.edge('validate','commit',label='是',label_at=(1610,3110,75,45));p.chain('commit','done')
 p.box('footer','只计恢复 WCT 收益。新请求仅登记续租资格；安全尾块按需兑现；其他 Agent 已付租金不返还。',65,3680,p.w-130,80,text=True,size=25,align='left')
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
 old['manual_edits_incorporated']='Manual 88112af84cd5 source archived; page 1 preserved; simplified prefix wording retained; recovery uses the full backup prefix and decision steps are compacted.'
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
