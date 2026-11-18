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
BASE=OUT/'references/before-independent-agent-credit-d2ecac2495e4/algorithm-2-patent-revised.drawio'
BASE_HASH='d2ecac2495e47ede41d36611673f449ff6cfdbfd22e2af191613d0508ff96a0d'
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
 'footer': '第 2 页：各 Agent 独立计算收益，共享块合并 Credit；新块与可释放尾块竞争信用，只淘汰可释放尾块。',
}

def overview():
 d=deepcopy(E.parse(BASE).find("diagram[@id='agents']"))
 for key,label in OVERVIEW_LABELS.items():
  c=d.find(f".//mxCell[@id='sla-agents-{key}']")
  c.set('value','<div style="line-height:1.4">'+escape(label).replace('\n','<br>')+'</div>')
 return d


def unified():
 p=Flow('flow','2 · 独立 Agent 收益与共享 Credit：统一租金流程',3760,3520)
 p.box('title','SlackLandlord  ·  独立 Agent 收益，共享块合并 Credit',60,25,3640,80,size=40,text=True,bold=True,align='left')
 p.box('subtitle','新请求实际复用时续租；空间不足时，新块与可释放尾块按信用竞争。',60,115,3640,65,size=28,text=True,align='left')
 rows=[
 r'\(x\)：本次 KV 块；\(a\)：引用 Agent；\(s_a\)：该 Agent 最近请求的 Slack；\(b_x\)：物理字节数',
 r'\(G_{a,x}\)：单独考虑 Agent a 时，备份 x 减少的 Slack 外恢复延迟；\(c_{a,x}\)：该 Agent 的剩余信用',
 r'\(\mathrm{Credit}_x=\sum_a c_{a,x}\)；\(\delta\)：每字节收取的租金；共享块只占一份物理空间',
 r'\(Q\)：可释放尾块；\(Y\)：计划淘汰的块；\(f\)：计划可用字节；\(y\)：参与收租的块',
 r'\(T_a(k)\)：使用前 k 块备份恢复已生成 KV 的时间；\(k_a\)：x 之前的块数；不计未知未来 KV']
 for i,line in enumerate(rows):p.box('symbols-'+str(i),line,70,225+i*58,3620,58,size=26,text=True,align='left')
 def main(k,t,y,h,**kw):return p.box(k,t,1200,y,1300,h,**kw)
 def left(k,t,y,h,**kw):return p.box(k,t,70,y,960,h,**kw)
 def diamond(k,t,y,h=140):return p.box(k,t,1430,y,840,h,decision=True,size=27)
 main('candidate','新请求复用 x，或生成完整 x\n登记引用、请求号与 Slack；本轮 Slack 不变',570,110,size=29)
 diamond('resident','本 Pool 已有 x 的备份？',790)
 diamond('prefix','必要前缀已提交，且源完整可读？',1020)
 # Retain the user's manually moved missing-prefix box.
 p.box('wait-prefix','从缺失前缀开始处理\n前缀或源未就绪时，暂不备份后续块',53,1115,960,150,size=27)
 main('gain','逐个计算各引用 Agent 的恢复收益\n'+r'\(G_{a,x}=\min\{T_a(k_a)-T_a(k_a+1),\max(T_a(k_a)-s_a,0)\}\)'+'\n使用全部可用前缀；其后已生成的 KV 重算\n内部块按“前缀到 x 之前 / 到 x”为止估值',1270,235,size=27)
 main('initial','为新块建立临时信用\n'+r'\(c_{a,x}\leftarrow G_{a,x},\qquad \mathrm{Credit}_x\leftarrow\sum_a c_{a,x}\)'+'\n每个 Agent 单独授信；此时尚未分配备份',1620,150,size=27)
 main('plan','建立回收计划，保护 x 的必要前缀\n'+r'\(Y\leftarrow\varnothing,\qquad f\leftarrow\text{Pool 空闲字节}\)'+'\n以下收租与试删只修改临时记录',1880,140,size=27)
 diamond('fits',r'空间足够？\(f\ge b_x\)',2170,150)
 main('copy','核验代次与余额版本，提交收租和回收计划\n释放 Y 后分配并复制 x；冲突则重新决策',2480,160,size=27)
 main('done','复制成功后发布 x，保留竞争后的信用余额\n记录各 Agent 本请求已授信；更新 Q\n不重新授信，不补回已支付的租金',2800,145,size=27)
 left('queue','更新 Q：无备份后继、未被读取的已提交块\n排除 x、必要前缀及释放中的块',1830,125,size=26)
 p.box('has-tail','还有尾块且 x 尚有信用？\n'+r'\(Q\ne\varnothing\ \land\ \mathrm{Credit}_x>0\)',145,2090,810,140,decision=True,size=26)
 left('rent','x 与 Q 中各块一起收租\n'+r'\(\delta=\min\{\mathrm{Credit}_x/b_x,\min_{y\in Q}\mathrm{Credit}_y/b_y\}\)'+'\n'+r'\(c_{a,y}\leftarrow c_{a,y}(1-b_y\delta/\mathrm{Credit}_y),\quad y\in Q\cup\{x\}\)'+'\n各块 Credit 取剩余份额之和；零余额跳过除法',2320,240,size=25)
 p.box('alive','收租后 x 仍有信用？\n'+r'\(\mathrm{Credit}_x>0\)',165,2700,770,160,decision=True,size=27)
 left('remove','选一个 Credit = 0 的旧尾块 y，加入回收计划\n'+r'\(Y\leftarrow Y\cup\{y\},\qquad f\leftarrow f+b_y\)'+'\n同值按块 ID 选择；前驱成为尾块后再参与收租',2960,160,size=26)
 left('no-space','不备份 x，丢弃本次临时记录\n已有备份与余额不变；信用同时归零也拒绝 x',3230,110,size=26)
 p.box('renew','按左侧收益式，用 a 的新 Slack 重算 '+r'\(G_{a,x}\)'+'\n仅该 Agent 的新请求首次复用时续租\n'+r'\(c_{a,x}\leftarrow G_{a,x},\quad \mathrm{Credit}_x\leftarrow\sum_a c_{a,x}\)'+'\n其他 Agent 余额不变；重复事件保留原余额',2790,1650,820,260,size=26)
 p.box('renew-done','立即保存余额与本请求已处理记录\n内部块、读取中的块也可续租；更新 Q',2790,2090,820,130,size=27)
 p.box('copy-failed','复制未完成则等待；失败则清理本次分配\n旧 ACK 不发布；已释放的备份不回滚',2790,2480,820,160,size=26)
 # Detached panels only illustrate physical KV layout.
 p.box('layout-title','一个共享 KV 块',2830,580,790,60,text=True,bold=True,size=30)
 p.box('layout-card',r'块 x · 大小 \(b_x\)'+'\nAgent A：Slack、剩余信用、续租请求号\nAgent B：Slack、剩余信用、续租请求号\n共享备份只占一份空间',2830,665,790,205,size=26)
 p.box('layout-pool-label','Peer HBM Pool',2830,965,790,60,text=True,bold=True,size=29)
 for i,name in enumerate(['共享 x','A2','A3','B2','C1','空闲']):
  p.box('layout-slot-'+str(i),name,2830+(i%3)*265,1050+(i//3)*105,245,80,size=27)
 p.box('layout-note','内部块有后继：可续租，不可淘汰\n无后继且未被读取：可进入 Q',2830,1315,790,110,text=True,size=27)
 p.chain('candidate','resident')
 p.edge('resident','renew',out=(1,.5),into=(0,.5),points=[(2670,860),(2670,1780)],label='是：实际复用立即续租',label_at=(2680,1490,940,65))
 p.edge('resident','prefix',label='否：新备份准入',label_at=(1900,940,300,50))
 p.edge('prefix','wait-prefix',out=(0,.5),into=(1,.5),points=[(1110,1090),(1110,1190)],label='否',label_at=(1200,1025,80,50))
 p.edge('prefix','gain',label='是',label_at=(1890,1180,80,50))
 p.chain('gain','initial','plan','fits')
 p.edge('fits','queue',out=(0,.5),into=(1,.5),points=[(1120,2245),(1120,1892.5)],label='否',label_at=(1260,2185,80,50))
 p.chain('queue','has-tail')
 p.edge('has-tail','rent',label='是',label_at=(590,2240,80,50))
 p.edge('has-tail','no-space',out=(0,.5),into=(0,.5),points=[(25,2160),(25,3285)],label='否',label_at=(60,2240,80,50))
 p.chain('rent','alive')
 p.edge('alive','no-space',out=(0,.5),into=(0,.5),points=[(25,2780),(25,3285)],label='否 / 同时归零',label_at=(65,2850,360,55))
 p.edge('alive','remove',label='是',label_at=(590,2880,80,50))
 p.edge('remove','fits',out=(1,.5),into=(.15,1),points=[(1090,3040),(1090,2350),(1556,2350)])
 p.edge('fits','copy',label='是：无需淘汰时允许零信用',label_at=(1890,2370,630,65))
 p.edge('copy','copy-failed',out=(1,.5),into=(0,.5),label='未成功',label_at=(2550,2460,140,50))
 p.edge('copy','done',label='成功',label_at=(1890,2700,110,50))
 p.chain('renew','renew-done')
 p.box('footer','估值范围：各 Agent 独立使用自己的 Slack；Credit 是可累加的租金信用，不等同于多个 Agent 同时恢复时的精确 WCT 改善。',65,3400,3630,65,text=True,size=25,align='left')
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
  'decision_flow_revision':{'events':'new chunk and request reuse; no Agent end event','renewal':'immediate actor-only reset once per request, including internal blocks; others unchanged','rent':'candidate and eligible tails compete on remaining credit per physical byte; reject candidate on ties','valuation':'independent per-Agent Slack-limited delay reduction; only Credit aggregates Agents'},
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
