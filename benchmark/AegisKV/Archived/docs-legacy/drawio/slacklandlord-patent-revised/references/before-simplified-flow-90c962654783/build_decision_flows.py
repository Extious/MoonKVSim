#!/usr/bin/env python3
"""Unified request-driven rental flow; preserve native layout and archived revisions."""
from pathlib import Path
from copy import deepcopy
from html import escape
import argparse, hashlib, json
import xml.etree.ElementTree as E
import build_diagram as native

OUT=Path(__file__).resolve().parent
SOURCE=OUT/'algorithm-2-patent-revised.drawio'
BASE=OUT/'references/before-agent-event-flow-476918a9d2cd/algorithm-2-patent-revised.drawio'
BASE_HASH='476918a9d2cdae7197522a245d764705a399f3d3d7fb2c03e5715c32dc307a8d'
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


# Only labels change on the user's KV-layout page; all geometry is preserved.
OVERVIEW_LABELS = {
 'subtitle': 'Agent 提供本轮 Slack；Request 生产或复用 KV；Peer HBM Pool 按物理 chunk 分配与回收。',
 'agent-A': 'Agent A · 第 3 轮\n本轮 Slack = 8 ms\nKV 路径 + 请求号 + 版本',
 'agent-B': 'Agent B · 第 2 轮\n本轮 Slack = 3 ms\nKV 路径 + 请求号 + 版本',
 'agent-C': 'Agent C · 第 1 轮\n本轮 Slack = 12 ms\nKV 路径 + 请求号 + 版本',
 'scope': r'\(C\)：算法 3 给定的备份可用容量；\(a\)：Agent；\(s_a\)：该 Agent 最近请求的 Slack。'+'\n新请求复用 KV 时更新 Slack 与该块信用；生成新块时决定是否备份。',
 'state': '容量与物理分配记录\nCOMMITTED / COPYING / RETIRING\n读取保护与分配代次\n各 Agent 的剩余信用、最近续租请求号',
 'round': '新请求到来\n记录本轮 Slack 与请求号\n本轮生成过程中 Slack 不变',
 'produce': '复用已有 KV\n按新 Slack 重算该块收益\n刷新本 Agent 的 Credit',
 'ack': '生成新的完整 KV chunk\n按前缀顺序进行准入决策\n容量不足时收租并淘汰尾块',
 'footer': '第 2 页：每次只处理当前 Agent 的一个 KV 块；单独估值、单独续租，再用共享块的剩余 Credit 决策。',
}

def overview():
 d=deepcopy(E.parse(BASE).find("diagram[@id='agents']"))
 for key,label in OVERVIEW_LABELS.items():
  c=d.find(f".//mxCell[@id='sla-agents-{key}']")
  c.set('value','<div style="line-height:1.4">'+escape(label).replace('\n','<br>')+'</div>')
 return d


def unified():
 p=Flow('flow','2 · 一个 Agent 的一次请求：KV 决策全流程',3760,4530)
 p.box('title','SlackLandlord  ·  一个 Agent 的请求如何决定一个 KV 块',60,25,3640,80,size=40,text=True,bold=True,align='left')
 p.box('subtitle','逐块处理当前请求；收益与续租只属于当前 Agent；共享块用各份额的剩余信用参与容量竞争。',60,115,3640,65,size=28,text=True,align='left')
 rows=[
 r'\(a\)：当前 Agent；\(x\)：本次完整 KV 块；\(s_a\)：本请求的 Slack，本轮不变；\(b_x\)：物理字节数',
 r'\(G_{a,x}\)：a 备份 x 的独立收益；\(c_{a,x}\)：a 对 x 的剩余信用；\(\mathrm{Credit}_x=\sum_a c_{a,x}\)',
 r'\(T_a(k)\)：使用前 k 块备份恢复已生成 KV 的时间；\(k_a\)：x 前面的块数；不计未知未来 KV',
 r'\(Q\)：可释放尾块；\(Y\)：试算中选出的回收块；\(f\)：试算可用字节；\(\delta\)：每字节租金',
 '处理记录按“副本代次、Agent、请求号”去重；无新请求就不续租，容量竞争仍按余额扣租。']
 for i,line in enumerate(rows):p.box('symbols-'+str(i),line,70,225+i*58,3620,58,size=26,text=True,align='left')
 def main(k,t,y,h,**kw):return p.box(k,t,1200,y,1300,h,**kw)
 def left(k,t,y,h,**kw):return p.box(k,t,70,y,960,h,**kw)
 def right(k,t,y,h,**kw):return p.box(k,t,2790,y,820,h,**kw)
 def diamond(k,t,y,h=150):return p.box(k,t,1430,y,840,h,decision=True,size=27)
 main('candidate','① 取当前 Agent a 的一个 KV 事件\n当前有效请求新生成或实际复用完整块 x；使用本轮 Slack',590,130,size=29)
 main('state','② 读取 x 的状态、各 Agent 余额与 a 的已处理请求号\n无副本则建立空分账；本 Pool 的元数据操作串行执行',850,150,size=27)
 diamond('busy','x 有未完成的备份或释放操作？',1100)
 left('defer','暂存本事件，等待该操作结束\n随后重新读取 x；不并发复制、不提前续租',1100,150,size=27)
 diamond('duplicate','a 的本请求已处理或过期？',1370,160)
 left('duplicate-done','保留全部余额，本次结束\n重复或过期事件不再次授信',1370,160,size=27)
 main('gain','③ 只计算当前 Agent a 的恢复收益\n'+r'\(G_{a,x}=\min\{T_a(k_a)-T_a(k_a+1),\max(T_a(k_a)-s_a,0)\}\)'+'\n使用到 x 之前 / 到 x 的备份前缀，其后已生成的 KV 重算',1640,210,size=27)
 main('credit','④ 首次授信，或为 a 的新请求续租\n'+r'\(c_{a,x}\leftarrow G_{a,x}\)'+'\n只改 a 的份额；其他 Agent 保留已扣租的余额',1960,150,size=28)
 main('aggregate','⑤ 汇总共享物理块的剩余信用\n'+r'\(\mathrm{Credit}_x\leftarrow\sum_a c_{a,x}\)'+'；更新先保存在本次临时记录',2210,130,size=28)
 diamond('resident','x 已有已提交的物理备份？',2450)
 right('renew-done','保存 a 的份额与本请求已处理记录，结束\n内部块、读取中的块也立即续租；更新 Q',2450,150,size=27)
 diamond('prefix','x 的必要前缀已提交，且源完整可读？',2710)
 right('wait-prefix','暂不备份 x，丢弃本次临时分账\n先处理缺失前缀或等待源就绪',2710,150,size=27)
 main('plan','⑥ 新备份：保护必要前缀，建立回收试算\n'+r'\(Y\leftarrow\varnothing,\qquad f\leftarrow\text{Pool 空闲字节}\)'+'\n以下扣租和试删仍只改变临时记录',2970,150,size=27)
 diamond('fits',r'空间足够？\(f\ge b_x\)',3230)
 diamond('validate','状态、请求版本、读保护与容量仍有效？',3490,160)
 right('retry','丢弃未执行的试算\n重新读取状态和余额后再决策',3505,130,size=27)
 main('copy','⑦ 提交扣租与回收计划，登记 x 的备份操作\n释放 Y，确认空间后分配并复制 x\n等待操作结果；只接受匹配本代次的确认',3760,150,size=27)
 diamond('copy-result','本次释放、分配与复制均成功？',4020,160)
 right('copy-failed','清理本次未完成分配，本次未备份成功\n不发布 x；已执行的扣租与释放不回滚',4020,160,size=26)
 main('done','⑧ 发布完整备份与竞争后的剩余信用\n记录 a 本请求已授信；更新 Q，本次结束\n不补满 Credit；等候中的其他 Agent 事件随后逐个处理',4280,150,size=27)
 # Capacity competition is a connected side loop, with one return to space check.
 left('queue','⑥a 更新 Q：无备份后继、未被读取的已提交块\n排除 x、必要前缀、其他备份的操作保护块及释放中块',2970,150,size=26)
 p.box('has-tail','有可释放尾块且 x 尚有信用？\n'+r'\(Q\ne\varnothing\ \land\ \mathrm{Credit}_x>0\)',145,3230,810,160,decision=True,size=26)
 left('rent','⑥b x 与 Q 中各块按物理字节收租\n'+r'\(\delta=\min\{\mathrm{Credit}_x/b_x,\min_{y\in Q}\mathrm{Credit}_y/b_y\}\)'+'\n'+r'\(c_{a,y}\leftarrow c_{a,y}(1-b_y\delta/\mathrm{Credit}_y),\quad y\in Q\cup\{x\}\)'+'\n每块的所有 Agent 均扣租，分母取扣租前总余额\n零余额跳过除法，再汇总各块 Credit',3500,230,size=25)
 p.box('alive','收租后 x 仍有信用？\n'+r'\(\mathrm{Credit}_x>0\)',165,3830,770,160,decision=True,size=27)
 left('remove','⑥c 选一个 Credit = 0 的旧尾块 y，加入试删\n'+r'\(Y\leftarrow Y\cup\{y\},\qquad f\leftarrow f+b_y\)'+'\n同值按块 ID 选择；前驱成为尾块后再参与下一轮',4090,160,size=26)
 left('reject','不备份 x，丢弃整次试算\n已有备份与余额不变；新旧同时归零也拒绝 x',4340,110,size=26)
 # Only explanatory KV/Pool layout is detached from execution.
 right('layout-title','同一块 x，各 Agent 分别记账',1100,60,text=True,bold=True,size=30)
 right('layout-card',r'Agent A：\(s_A,\ c_{A,x}\)，上次续租请求号'+'\n'+r'Agent B：\(s_B,\ c_{B,x}\)，上次续租请求号'+'\nA 的新请求只更新 A；B 的份额继续保留\n'+r'物理大小 \(b_x\)：共享块只占一份空间',1200,220,size=26)
 right('layout-pool-title','Peer HBM Pool · 物理布局',1530,60,text=True,bold=True,size=29)
 for i,name in enumerate(['共享 x','A2','A3','B2','C1','空闲']):
  p.box('layout-slot-'+str(i),name,2790+(i%3)*280,1630+(i//3)*105,255,80,size=27)
 right('layout-note','有后继的内部块：可续租，不可淘汰\n成为可释放尾块后：参与 Q 的收租',1880,110,text=True,size=27)
 p.chain('candidate','state','busy')
 p.edge('busy','defer',out=(0,.5),into=(1,.5),label='是',label_at=(1180,1100,90,50))
 p.edge('defer','state',out=(.5,0),into=(0,.5),points=[(550,925)],label='操作结束后',label_at=(630,865,330,50))
 p.edge('busy','duplicate',label='否',label_at=(1890,1280,90,50))
 p.edge('duplicate','duplicate-done',out=(0,.5),into=(1,.5),label='是',label_at=(1180,1380,90,50))
 p.edge('duplicate','gain',label='否：本请求尚未处理',label_at=(1890,1550,500,50))
 p.chain('gain','credit','aggregate','resident')
 p.edge('resident','renew-done',out=(1,.5),into=(0,.5),label='是',label_at=(2480,2450,90,50))
 p.edge('resident','prefix',label='否：需要新副本',label_at=(1890,2630,390,50))
 p.edge('prefix','wait-prefix',out=(1,.5),into=(0,.5),label='否',label_at=(2480,2710,90,50))
 p.edge('prefix','plan',label='是',label_at=(1890,2880,90,50))
 p.chain('plan','fits')
 p.edge('fits','queue',out=(0,.5),into=(1,.5),points=[(1120,3305),(1120,3045)],label='否',label_at=(1250,3230,90,50))
 p.chain('queue','has-tail')
 p.edge('has-tail','rent',label='是',label_at=(590,3410,90,50))
 p.edge('has-tail','reject',out=(0,.5),into=(0,.5),points=[(25,3310),(25,4395)],label='否',label_at=(70,3410,90,50))
 p.chain('rent','alive')
 p.edge('alive','reject',out=(0,.5),into=(0,.5),points=[(25,3910),(25,4395)],label='否 / 同时归零',label_at=(65,4000,380,55))
 p.edge('alive','remove',label='是',label_at=(590,4010,90,50))
 p.edge('remove','fits',out=(1,.5),into=(.15,1),points=[(1080,4170),(1080,3400),(1556,3400)])
 p.edge('fits','validate',label='是：无需淘汰时允许零信用',label_at=(1890,3400,650,60))
 p.edge('validate','retry',out=(1,.5),into=(0,.5),label='否',label_at=(2480,3500,90,50))
 p.edge('retry','state',out=(1,.5),into=(1,.5),points=[(3690,3570),(3690,925)],label='重新读取',label_at=(3360,860,300,55))
 p.edge('validate','copy',label='是',label_at=(1890,3670,90,50))
 p.chain('copy','copy-result')
 p.edge('copy-result','copy-failed',out=(1,.5),into=(0,.5),label='否',label_at=(2480,4030,90,50))
 p.edge('copy-result','done',label='是',label_at=(1890,4210,90,50))
 p.box('footer','估值范围：各 Agent 独立使用 Slack，Credit 为可累加租金信用；不计算多 Agent 联合 WCT，也不对未来请求预付信用。',65,4460,3630,60,text=True,size=25,align='left')
 return p


def write():
 assert hashfile(BASE)==BASE_HASH
 old=json.loads((OUT/'MANIFEST.json').read_text())
 assert hashfile(SOURCE) in {BASE_HASH,old.get('output_sha256',{}).get(SOURCE.name)},'Manual edits detected; preserve and incorporate them first.'
 flow=unified();checks=flow.validate()
 book=E.Element('mxfile',host='app.diagrams.net',version='31.1.5');book.append(overview());book.append(flow.d)
 E.indent(book);E.ElementTree(book).write(SOURCE,encoding='utf-8',xml_declaration=True)
 standalone=E.Element('mxfile',host='app.diagrams.net',version='31.1.5');standalone.append(deepcopy(flow.d));E.indent(standalone)
 E.ElementTree(standalone).write(OUT/'algorithm-2-rental-management.drawio',encoding='utf-8',xml_declaration=True)
 record={
  'status':'UNIFIED_RENTAL_DESIGN_NOT_DEPLOYED','date':'2026-09-09','active_generator':'build_decision_flows.py',
  'previous_revision':{'archive':str(BASE.parent.relative_to(OUT)),'manual_source_sha256':BASE_HASH},
  'pages':{'agents':{'layout_preserved':True,'updated_labels':list(OVERVIEW_LABELS)},'flow':checks},
  'decision_flow_revision':{'events':'one current Agent/request/chunk event; busy-copy/release events wait and reread; no Agent end event','renewal':'explicit duplicate guard, actor-only value and credit update, then shared Credit aggregation; no bulk grants to historical references','rent':'candidate and eligible tails compete on remaining credit per physical byte; reject candidate on ties','valuation':'independent per-Agent Slack-limited delay reduction; only Credit aggregates Agents','completion':'resident credit save, deferred prefix, rejection, retry, successful copy publication and failed-copy cleanup are explicit paths'},
  'model_boundary':'additive independent-Agent credit, not exact joint workflow WCT; no global optimality or idle expiry guarantee',
  'production_algorithm_code_changed':False,'patent_docx_changed':False,
  'output_sha256':{SOURCE.name:hashfile(SOURCE)},'generator_components_sha256':{n:hashfile(OUT/n) for n in ['build_decision_flows.py','build_diagram.py']},
  'visual_review':'PENDING','export_checks':'PENDING'}
 (OUT/'MANIFEST.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
 print('Written overview and ONE unified rental flow.',flush=True)


def export_standalone():
 import subprocess,pymupdf
 from PIL import Image
 from urllib.parse import quote,unquote
 source=OUT/'algorithm-2-rental-management.drawio'
 for fmt in ['png','pdf']:
  cmd=[native.CLI,'-x','-f',fmt,'-e','-b','0','-o',str(source)+'.'+fmt,str(source)]
  if fmt=='pdf':cmd.insert(1,'--crop')
  subprocess.run(cmd,check=True)
 with pymupdf.open(str(source)+'.pdf') as doc:
  assert len(doc)==1
  assert not any(t in doc[0].get_text() for t in [r'\(',r'\begin',r'\mathrm'])
  meta={k:v for k,v in doc.metadata.items() if k not in ['format','encryption']};meta.update(subject=quote(source.read_text(),safe=''))
  doc.set_metadata(meta);doc.saveIncr()
  for b in doc[0].get_text('blocks'):assert doc[0].rect.contains(pymupdf.Rect(b[:4]))
 with Image.open(str(source)+'.png') as im:
  embedded=E.fromstring(unquote(im.info['mxGraphModel']))
  assert [c.attrib for c in embedded.iter('mxCell')]==[c.attrib for c in E.parse(source).iter('mxCell')]
 record=json.loads((OUT/'MANIFEST.json').read_text())
 for suffix in ['', '.png','.pdf']:
  path=Path(str(source)+suffix);record['output_sha256'][path.name]=hashfile(path)
 record['export_checks']['standalone_sources_embedded']='PASS'
 (OUT/'MANIFEST.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--xml-only',action='store_true');args=parser.parse_args()
 write()
 if not args.xml_only:native.export();export_standalone()
