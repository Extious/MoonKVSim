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
BASE=OUT/'references/before-simplified-flow-90c962654783/algorithm-2-patent-revised.drawio'
BASE_HASH='90c9626547833f8267cfad1ed35916b3d06ad8a126e19548ab4191e9a9b65978'
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
 p=Flow('flow','2 · SlackLandlord：简化后的 KV 决策流程',3760,3410)
 p.box('title','SlackLandlord  ·  逐 Agent 续租与 KV 备份决策',60,25,3640,80,size=40,text=True,bold=True,align='left')
 p.box('subtitle','先确认事件与备份条件，再计算当前 Agent 的收益；已有副本续租结束，新副本才参与容量竞争。',60,115,3640,65,size=28,text=True,align='left')
 rows=[
 r'\(a\)：当前 Agent；\(x\)：完整 KV 块；\(s_a\)：本请求固定的 Slack；\(b_x\)：物理字节数',
 r'\(G_{a,x}\)：a 的独立恢复收益；\(c_{a,x}\)：a 的剩余信用；\(\mathrm{Credit}_x=\sum_a c_{a,x}\)',
 r'\(T_a(k)\)：使用前 k 块备份恢复已生成 KV 的时间；\(k_a\)：x 前面的块数；不计未知未来 KV',
 r'\(Q\)：已提交、无后继且可释放的尾块；排除读取、必要前缀、其他备份操作保护与释放中的块',
 r'\(Y\)：试算回收块；\(f\)：试算可用字节；\(\delta\)：每字节租金；每个 Agent、请求、副本代次只授信一次']
 for i,line in enumerate(rows):p.box('symbols-'+str(i),line,70,225+i*58,3620,58,size=26,text=True,align='left')
 def main(k,t,y,h,**kw):return p.box(k,t,1200,y,1300,h,**kw)
 def left(k,t,y,h,**kw):return p.box(k,t,70,y,960,h,**kw)
 def right(k,t,y,h,**kw):return p.box(k,t,2790,y,820,h,**kw)
 def diamond(k,t,y,h=160):return p.box(k,t,1430,y,840,h,decision=True,size=27)
 main('candidate','① 读取 Agent a 当前请求对 x 的生成 / 复用事件\n读取 x 状态、各 Agent 余额和 a 的续租请求号；无副本则空分账',590,130,size=28)
 diamond('event-state','本次事件状态？',830,170)
 left('skip','本次结束\n重复或过期事件不修改信用',840,150,size=27)
 left('defer','暂缓本事件，不授信、不复制\n操作完成或前缀 / 源就绪后，回到①重读',1050,170,size=27)
 diamond('unready','需要新副本，且前缀或源未就绪？',1110,170)
 main('gain','② 只计算当前 Agent a 的恢复收益\n'+r'\(G_{a,x}=\min\{T_a(k_a)-T_a(k_a+1),\max(T_a(k_a)-s_a,0)\}\)'+'\n比较前缀到 x 之前 / 到 x；其后已生成的 KV 重算',1380,190,size=27)
 main('credit','③ 更新 a 的份额，再汇总共享 Credit\n'+r'\(c_{a,x}\leftarrow G_{a,x},\qquad \mathrm{Credit}_x\leftarrow\sum_a c_{a,x}\)'+'\n其他 Agent 保留已扣租余额；本次改动暂存',1660,170,size=28)
 diamond('resident','x 已有已提交的备份？',1940)
 right('renew-done','保存 a 的份额与本请求已处理记录，结束\n内部块、读取中的块同样可续租；更新 Q',1940,160,size=27)
 main('plan','④ 新副本：保护必要前缀，初始化 Q 与回收试算\n'+r'\(Y\leftarrow\varnothing,\qquad f\leftarrow\text{Pool 空闲字节}\)'+'\n扣租和试删只修改临时记录',2210,150,size=27)
 diamond('fits',r'空间足够？\(f\ge b_x\)',2480,160)
 main('execute','⑤ 核验并执行备份计划\n先核验状态、请求、保护与容量；通过后提交扣租\n释放 Y 后分配并复制 x；只接受本代次结果',2760,210,size=27)
 right('copy-failed','执行失败：清理本次未完成分配，结束\n不发布 x；已执行扣租与释放不回滚',2910,150,size=26)
 main('done','⑥ 发布完整备份与竞争后的剩余信用\n记录 a 本请求已授信；更新 Q，结束\n不补满 Credit；等候事件随后各自处理',3100,150,size=27)
 # One rental loop; Q is initialized before it and rebuilt after each trial deletion.
 p.box('has-tail','有可释放尾块且 x 尚有信用？\n'+r'\(Q\ne\varnothing\ \land\ \mathrm{Credit}_x>0\)',145,2080,810,160,decision=True,size=26)
 left('rent','x 与 Q 中各块按物理字节收租\n'+r'\(\delta=\min\{\mathrm{Credit}_x/b_x,\min_{y\in Q}\mathrm{Credit}_y/b_y\}\)'+'\n'+r'\(c_{a,y}\leftarrow c_{a,y}(1-b_y\delta/\mathrm{Credit}_y),\quad y\in Q\cup\{x\}\)'+'\n所有 Agent 均扣租，分母取扣租前总余额\n零余额跳过除法，再汇总各块 Credit',2340,240,size=25)
 p.box('alive','收租后 x 仍有信用？\n'+r'\(\mathrm{Credit}_x>0\)',165,2680,770,160,decision=True,size=27)
 left('remove','试删一个 Credit = 0 的旧尾块 y\n'+r'\(Y\leftarrow Y\cup\{y\},\qquad f\leftarrow f+b_y\)'+'\n同值按块 ID 选择；更新 Q，新尾块下一轮再收租',2940,170,size=26)
 left('reject','不备份 x，丢弃整次试算\n已有备份与余额不变；同时归零也拒绝 x',3210,110,size=26)
 right('layout-title','共享块 x · 各 Agent 分别记账',830,60,text=True,bold=True,size=30)
 right('layout-card',r'Agent A：\(s_A,\ c_{A,x}\)，续租请求号'+'\n'+r'Agent B：\(s_B,\ c_{B,x}\)，续租请求号'+'\nA 新请求只续租 A；B 无新请求不续租\n'+r'大小 \(b_x\)：共享块只占一份空间',930,210,size=26)
 right('layout-pool-title','Peer HBM Pool',1260,60,text=True,bold=True,size=29)
 for i,name in enumerate(['共享 x','A2','A3','B2','C1','空闲']):
  p.box('layout-slot-'+str(i),name,2790+(i%3)*280,1360+(i//3)*105,255,80,size=27)
 right('layout-note','续租只改当前 Agent 的份额\n收租按每块的所有份额扣除',1640,100,text=True,size=27)
 p.chain('candidate','event-state')
 p.edge('event-state','skip',out=(0,.5),into=(1,.5),label='重复 / 过期',label_at=(1110,830,300,55))
 p.edge('event-state','defer',out=(.25,1),into=(1,.25),points=[(1120,1040),(1120,1092.5)],label='备份 / 释放进行中',label_at=(560,990,530,50))
 p.edge('defer','candidate',out=(0,.5),into=(0,.5),points=[(25,1135),(25,655)],label='条件就绪后重试',label_at=(360,595,530,55))
 p.edge('event-state','unready',label='可处理',label_at=(1890,1030,180,50))
 p.edge('unready','defer',out=(0,.5),into=(1,.8),points=[(1100,1195),(1100,1186)],label='是',label_at=(1250,1200,90,50))
 p.edge('unready','gain',label='否',label_at=(1890,1300,90,50))
 p.chain('gain','credit','resident')
 p.edge('resident','renew-done',out=(1,.5),into=(0,.5),label='是',label_at=(2490,1950,90,50))
 p.edge('resident','plan',label='否',label_at=(1890,2120,90,50))
 p.chain('plan','fits')
 p.edge('fits','has-tail',out=(0,.5),into=(1,.5),points=[(1120,2560),(1120,2160)],label='否',label_at=(1260,2490,90,50))
 p.edge('has-tail','rent',label='是',label_at=(590,2255,90,50))
 p.edge('has-tail','reject',out=(0,.5),into=(0,.5),points=[(25,2160),(25,3265)],label='否',label_at=(70,2250,90,50))
 p.chain('rent','alive')
 p.edge('alive','remove',label='是',label_at=(590,2860,90,50))
 p.edge('alive','reject',out=(0,.5),into=(0,.5),points=[(25,2760),(25,3265)],label='否 / 同时归零',label_at=(65,2850,380,55))
 p.edge('remove','fits',out=(1,.5),into=(.15,1),points=[(1080,3025),(1080,2670),(1556,2670)])
 p.edge('fits','execute',label='是：无需淘汰时允许零信用',label_at=(1890,2670,650,60))
 p.edge('execute','candidate',out=(1,.18),into=(1,.5),points=[(3690,2797.8),(3690,655)],label='冲突：丢弃未执行试算，重试',label_at=(2800,2680,840,60))
 p.edge('execute','copy-failed',out=(1,.75),into=(0,.5),points=[(2640,2917.5),(2640,2985)],label='执行失败',label_at=(2520,2835,260,55))
 p.edge('execute','done',label='全部成功',label_at=(1890,3005,260,55))
 p.box('footer','设计范围：每次只为实际访问的 Agent 估值和续租；Credit 为可累加租金信用，不等于多 Agent 联合 WCT 改善。',65,3340,3630,55,text=True,size=25,align='left')
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
  'decision_flow_revision':{'events':'one Agent/request/chunk event; three-way event filter and shared readiness wait','renewal':'check new-copy readiness before valuation; update actor share and aggregate in one ordered step; no historical-reference grants','rent':'unchanged candidate-and-tail rental; Q initialized in the plan and updated after deletion; reject candidate on ties','valuation':'independent per-Agent Slack-limited delay reduction; only Credit aggregates Agents','completion':'execution step has explicit pre-execution conflict, execution failure and successful publication results'},
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
