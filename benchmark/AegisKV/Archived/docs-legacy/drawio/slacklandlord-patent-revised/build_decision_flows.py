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
BASE=OUT/'references/before-hl-keys-f84db8ef173c/algorithm-2-patent-revised.drawio'
BASE_HASH='f84db8ef173ca51b4b47e080e9177bb54b3e3ccde3ad9448c4ffe77d83b4778e'
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
 'state': '容量与物理分配记录\nCOMMITTED / COPYING / RETIRING\n本池租金 L、尾块队列 Q 与租值键 H\n各 Agent 信用份额、最近续租请求号',
 'round': '新请求到来\n记录本轮 Slack 与请求号\n本轮生成过程中 Slack 不变',
 'produce': '复用已有 KV\n按新 Slack 重算该块收益\n刷新本 Agent 的 Credit',
 'ack': '生成新的完整 KV chunk\n按前缀顺序进行准入决策\n容量不足时收租并淘汰尾块',
 'footer': '第 2 页：Agent 的请求到来，决策其中一个完整 KV chunk x；逐 Agent 续租，以 H、L 管理尾块租金。',
}

def overview():
 d=deepcopy(E.parse(BASE).find("diagram[@id='agents']"))
 for key,label in OVERVIEW_LABELS.items():
  c=d.find(f".//mxCell[@id='sla-agents-{key}']")
  c.set('value','<div style="line-height:1.4">'+escape(label).replace('\n','<br>')+'</div>')
 return d


def unified():
 p=Flow('flow','2 · SlackLandlord：一次请求中一个 KV chunk 的决策',3760,3620)
 p.box('title','SlackLandlord  ·  Agent 的请求到来，决策其中一个 KV chunk x',60,25,3640,80,size=40,text=True,bold=True,align='left')
 p.box('subtitle','请求中的完整 KV 按前缀顺序逐块处理；先按当前 Agent 估值和续租，再用 H、L 决定新副本准入。',60,115,3640,65,size=28,text=True,align='left')
 rows=[
 r'\(a\)：当前 Agent；\(x\)：本请求的完整 KV 块；\(s_a\)：本请求固定 Slack；\(b_x\)：块的物理字节数',
 r'\(G_{a,x}\)：a 的恢复收益；\(T_a(k)\)：用前 k 块备份恢复已生成 KV 的时间；\(k_a\)：x 前面的块数',
 r'\(c_{u,x}\)：最近结算时 Agent u 的信用份额；\(u,v\)：遍历该块的 Agent；\(\mathrm{Credit}_x\)：结算后的总余额',
 r'\(L\)：本池累计每字节租金，初值 0；\(L^{\prime}\)：本次试算租金；\(H_x\)：租值键；H、L 单位均为时间/字节',
 r'\(Q\)：按 H 排序的可释放尾块；排除读取、必要前缀、其他备份操作保护与释放中的块',
 r'\(Y\)：试算回收块；\(f\)：试算可用字节；\(y,z\)：旧尾块及新暴露尾块；每个请求、Agent、副本代次只授信一次']
 for i,line in enumerate(rows):p.box('symbols-'+str(i),line,70,220+i*57,3620,57,size=26,text=True,align='left')
 def main(k,t,y,h,**kw):return p.box(k,t,1200,y,1300,h,**kw)
 def left(k,t,y,h,**kw):return p.box(k,t,70,y,960,h,**kw)
 def right(k,t,y,h,**kw):return p.box(k,t,2790,y,820,h,**kw)
 def diamond(k,t,y,h=150):return p.box(k,t,1430,y,840,h,decision=True,size=27)
 main('candidate','① Agent a 的请求到来，取其中一个完整 KV chunk x\n读取本请求 Slack、请求号与 x 状态；无副本则空分账\n新生成块在封闭后进入本流程',620,155,size=28)
 diamond('event-state','本请求对 x 的处理状态？',830)
 left('skip','本次结束\n重复或过期请求不重新授信',835,140,size=27)
 left('defer','暂缓处理 x，不授信、不复制\n操作完成或前缀 / 源就绪后，回到①重读',1050,150,size=27)
 diamond('unready','需要新副本，且前缀或源未就绪？',1080)
 main('gain','② 只计算当前 Agent a 的恢复收益\n'+r'\(G_{a,x}=\min\{T_a(k_a)-T_a(k_a+1),\max(T_a(k_a)-s_a,0)\}\)'+'\n比较前缀到 x 之前 / 到 x；其后已生成的 KV 重算',1300,150,size=27)
 main('settle','③ 先结算 x 已支付的租金\n'+r'\(\mathrm{Credit}_x\leftarrow b_x\max(H_x-L,0)\)'+'\n'+r'\(c_{u,x}\leftarrow c_{u,x}\,\frac{\mathrm{Credit}_x}{\sum_v c_{v,x}}\quad(\forall u)\)'+'\n仅已有 x ∈ Q 时执行；其余块保留份额\n分母取结算前总额；总额为 0 时跳过',1530,240,size=27)
 main('credit','④ 只续租当前 Agent a，并设置租值键\n'+r'\(c_{a,x}\leftarrow G_{a,x},\quad \mathrm{Credit}_x\leftarrow\sum_u c_{u,x}\)'+'\n'+r'\(H_x\leftarrow L+\mathrm{Credit}_x/b_x\)'+'\n其他 Agent 保留租后余额；本次改动暂存',1820,185,size=28)
 diamond('resident','x 已有已提交的备份？',2090)
 right('renew-done','保存分账与 a 本请求已处理记录\n'+r'\(x\in Q\)：更新堆中 \(H_x\)；否则冻结份额'+'\n内部块、读取中的块同样可续租，结束',2075,180,size=27)
 main('plan','⑤ 新副本：建立 L、Q 与账本的临时副本\n'+r'\(L^{\prime}\leftarrow L,\quad Y\leftarrow\varnothing,\quad f\leftarrow\text{Pool 可用字节}\)'+'\n本次退出 Q 的块按③结算并冻结；保护 x 的必要前缀\n新入 Q 者按左侧回收框建键；持续在 Q 中的 H 不变',2330,220,size=27)
 diamond('fits',r'空间足够？\(f\ge b_x\)',2640)
 main('execute','⑥ 核验并执行备份计划\n先核验请求、L / Q 版本、保护与容量；通过后提交临时状态\n'+r'\(L\leftarrow L^{\prime},\qquad c_{a,x}\leftarrow b_x\max(H_x-L^{\prime},0)\)'+'\n冻结 x 的租后份额；撤销 Y 恢复资格后释放、分配并复制 x\n只接受本副本代次的操作结果',2890,245,size=26)
 right('copy-failed','执行失败：清理本次未完成分配\n不发布 x；已执行的租金推进与释放不回滚\n按实际状态恢复 Q，结束',3200,165,size=26)
 main('done','⑦ 复制完成：按当前 L 发布完整备份\n'+r'\(\mathrm{Credit}_x\leftarrow\sum_u c_{u,x},\quad H_x\leftarrow L+\mathrm{Credit}_x/b_x\)'+'\n记录 a 本请求已授信；按保护状态入 Q 或冻结\n复制期间不收租；不重算收益、不补满 Credit',3270,220,size=27)
 # H_x remains fixed within the trial; only newly exposed tails get a new key.
 p.box('has-tail','有可释放尾块？\n'+r'\(Q\ne\varnothing\)',145,2130,810,150,decision=True,size=27)
 left('rent','读取 Q 中租值键最小的尾块 y\n'+r'\((y,H_y)\leftarrow\min Q\)'+'\nH 相同则按物理块 ID 选择',2370,145,size=28)
 p.box('alive','旧尾块会先耗尽信用？\n'+r'\(H_y<H_x\)',165,2620,770,150,decision=True,size=28)
 left('remove','推进试算租金，试删 y\n'+r'\(L^{\prime}\leftarrow H_y,\quad Y\leftarrow Y\cup\{y\},\quad f\leftarrow f+b_y\)'+'\n移除 y；新暴露且可释放的尾块 z 入 Q：\n'+r'\(H_z\leftarrow L^{\prime}+\frac{\sum_u c_{u,z}}{b_z}\)'+'\n原有其他 H 不变；'+r'候选 \(H_x\) 不重建',2870,245,size=26)
 left('reject','不备份 x，丢弃试算 L、Q 与账本\n实际 L、已有副本及余额不变\n候选与旧尾块同值也拒绝',3230,145,size=26)
 right('layout-title','共享块 x · 分账与租值键',835,60,text=True,bold=True,size=30)
 right('layout-card',r'Agent A：\(s_A,\ c_{A,x}\)，续租请求号'+'\n'+r'Agent B：\(s_B,\ c_{B,x}\)，续租请求号'+'\n'+r'块大小 \(b_x\)、租值键 \(H_x\)'+'\n副本状态、读取保护、是否在 Q 中',950,205,size=27)
 right('layout-pool-title','Peer HBM Pool',1290,60,text=True,bold=True,size=29)
 for i,name in enumerate(['共享 x','A2','A3','B2','C1','空闲']):
  p.box('layout-slot-'+str(i),name,2790+(i%3)*280,1390+(i//3)*105,255,80,size=27)
 right('layout-note','Pool 元数据：累计租金 L、尾块最小堆 Q\n块元数据：租值键 H、各 Agent 分账与状态',1660,100,text=True,size=26)
 p.chain('candidate','event-state')
 p.edge('event-state','skip',out=(0,.5),into=(1,.5),label='已处理 / 过期',label_at=(1090,835,320,55))
 p.edge('event-state','defer',out=(.25,1),into=(1,.25),points=[(1120,1020),(1120,1087.5)],label='备份 / 释放进行中',label_at=(560,995,530,50))
 p.edge('defer','candidate',out=(0,.5),into=(0,.5),points=[(25,1125),(25,697.5)],label='条件就绪后重试',label_at=(360,620,530,55))
 p.edge('event-state','unready',label='可处理',label_at=(1890,1000,180,50))
 p.edge('unready','defer',out=(0,.5),into=(1,.8),points=[(1100,1155),(1100,1170)],label='是',label_at=(1250,1160,90,50))
 p.edge('unready','gain',label='否',label_at=(1890,1235,90,50))
 p.chain('gain','settle','credit','resident')
 p.edge('resident','renew-done',out=(1,.5),into=(0,.5),label='是',label_at=(2490,2100,90,50))
 p.edge('resident','plan',label='否',label_at=(1890,2250,90,50))
 p.chain('plan','fits')
 p.edge('fits','has-tail',out=(0,.5),into=(1,.5),points=[(1120,2715),(1120,2205)],label='否',label_at=(1260,2645,90,50))
 p.edge('has-tail','rent',label='是',label_at=(590,2300,90,50))
 p.edge('has-tail','reject',out=(0,.5),into=(0,.5),points=[(25,2205),(25,3302.5)],label='否',label_at=(70,2300,90,50))
 p.chain('rent','alive')
 p.edge('alive','remove',label='是',label_at=(590,2790,90,50))
 p.edge('alive','reject',out=(0,.5),into=(0,.5),points=[(25,2695),(25,3302.5)],label='否 / 同值',label_at=(65,2800,380,55))
 p.edge('remove','fits',out=(1,.5),into=(.15,1),points=[(1080,2992.5),(1080,2820),(1556,2820)])
 p.edge('fits','execute',label='是：无需淘汰时允许零信用',label_at=(1890,2805,650,60))
 p.edge('execute','candidate',out=(1,.18),into=(1,.5),points=[(3690,2934.1),(3690,697.5)],label='冲突：丢弃未执行试算，重试',label_at=(2800,2810,840,60))
 p.edge('execute','copy-failed',out=(1,.78),into=(0,.5),points=[(2640,3081.1),(2640,3282.5)],label='执行失败',label_at=(2520,3100,260,55))
 p.edge('execute','done',label='全部成功',label_at=(1890,3170,260,55))
 p.box('footer','一份请求、一个完整块、一次决策。H、L 用于按需结算租金；Credit 累加各 Agent 份额，不等于多 Agent 联合 WCT 改善。',65,3550,3630,55,text=True,size=25,align='left')
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
  'decision_flow_revision':{'events':'one Agent request arrives; decide one complete chunk x from this request','renewal':'settle deferred rent proportionally, renew only requesting Agent, and rekey H; no historical-reference grants','rent':'Q is ordered by H; compare old-tail H_y with fixed candidate H_x, advance trial L only; settle on Q exit and rebase only new entries','valuation':'independent per-Agent Slack-limited delay reduction; only Credit aggregates Agents','completion':'freeze candidate post-rent balance before copying; on publication rebase H with current L without refill; reject stale L/Q snapshots'},
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
