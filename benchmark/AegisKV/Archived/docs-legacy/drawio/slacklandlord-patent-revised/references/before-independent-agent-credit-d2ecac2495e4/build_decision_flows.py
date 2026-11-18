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
BASE=OUT/'references/before-unified-rental-8be19795d980/algorithm-2-patent-revised.drawio'
BASE_HASH='8be19795d9806a1327573a72dd760293ce199843e07282c217fd2d3fedf669fe'
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
 'scope': r'\(C\)：算法 3 给定的备份可用容量；\(a\)：Agent；\(s_a\)：该 Agent 最近请求的 Slack。'+'\n新请求复用 KV 时更新 Slack 与该块信用；生成新块时决定是否备份。',
 'state': '容量与物理分配记录\nCOMMITTED / COPYING / RETIRING\n读取保护与分配代次\n各 Agent 的剩余信用、最近续租请求号',
 'round': '新请求到来\n记录本轮 Slack 与请求号\n本轮生成过程中 Slack 不变',
 'produce': '复用已有 KV\n按新 Slack 重算该块收益\n刷新本 Agent 的 Credit',
 'ack': '生成新的完整 KV chunk\n按前缀顺序进行准入决策\n容量不足时收租并淘汰尾块',
 'footer': '第 2 页：复用续租与新块准入的统一流程。内部块可刷新信用；收租与淘汰只针对可释放尾块。',
}

def overview():
 d=deepcopy(E.parse(BASE).find("diagram[@id='agents']"))
 for key,label in OVERVIEW_LABELS.items():
  c=d.find(f".//mxCell[@id='sla-agents-{key}']")
  c.set('value','<div style="line-height:1.4">'+escape(label).replace('\n','<br>')+'</div>')
 return d


def unified():
 p=Flow('flow','2 · 请求复用与新块准入：统一租金流程',3760,3720)
 p.box('title','SlackLandlord  ·  请求复用与新块准入',60,25,3640,80,size=40,text=True,bold=True,align='left')
 p.box('subtitle','复用时按新 Slack 续租；容量不足时按剩余信用收租；只淘汰可释放尾块。',60,115,3640,65,size=28,text=True,align='left')
 rows=[
 r'\(x\)：本次 KV 块；\(y\)：候选尾块；\(a\)：引用 Agent；\(s_a\)：最近请求的 Slack；\(b_x\)：块的物理字节数',
 r'\(G_x\)：前缀增加 x 的总 WCT 收益；\(W_{a,x}\)：分给 Agent 的授信额度；\(c_{a,x}\)：该 Agent 的剩余信用',
 r'\(\mathrm{Credit}_x=\sum_a c_{a,x}\)；\(\delta\)：每字节收取的租金；同一 Agent、同一请求、同一块只授信或续租一次',
 r'\(Q\)：可释放尾块；\(Y\)：计划淘汰的块；\(D_Y\)：累计删除损失；\(f\)：计划可用字节',
 r'\(T_a(k)\)：恢复已生成 KV 的时间，使用前 k 块备份；\(k_a\)：x 之前的块数；\(w\gets x\)：引用 x 的工作流',
 r'\(\mathbf T,\mathbf T^x\)：相关引用的备份前缀分别到 x 之前、到 x；其他节点不变；WCT 按 DAG 最长完成路径计算']
 for i,line in enumerate(rows):p.box('symbols-'+str(i),line,70,225+i*58,3620,58,size=26,text=True,align='left')
 def main(k,t,y,h,**kw):return p.box(k,t,1200,y,1300,h,**kw)
 def left(k,t,y,h,**kw):return p.box(k,t,70,y,960,h,**kw)
 def diamond(k,t,y,h=140):return p.box(k,t,1430,y,840,h,decision=True,size=27)
 main('candidate','新请求复用 x，或生成完整 x\n登记引用与本轮 Slack；已有复制则合并事件',670,120,size=29)
 diamond('resident','本 Pool 已有 x 的备份？',890)
 diamond('prefix','必要前缀已提交，且源完整可读？',1120)
 left('wait-prefix','从缺失前缀开始处理\n前缀或源未就绪时，暂不备份后续块',1100,150,size=27)
 main('gain','计算前缀增加 x 带来的恢复收益\n'+r'不使用 x：\(T_a(k_a)\)；使用 x：\(T_a(k_a+1)\)'+'\n'+r'\(G_x=\sum_{w\gets x}[\mathrm{WCT}_w(\mathbf T)-\mathrm{WCT}_w(\mathbf T^x)]\)'+'\n'+r'单工作流、单 Agent 恢复：\(G_x=\min\{T_a(k_a)-T_a(k_a+1),\max(T_a(k_a)-s_a,0)\}\)',1350,235,size=27)
 main('plan','建立回收试算；保护 x 的必要前缀\n'+r'\(Y\leftarrow\varnothing,\quad D_Y\leftarrow0,\quad f\leftarrow\text{Pool 空闲字节}\)'+'\n试算中把 x 视为已备份，实际尚未分配',1680,155,size=27)
 diamond('fits',r'空间足够？\(f\ge b_x\)',1920)
 diamond('accept','满足准入条件？\n'+r'\(\begin{cases}G_x\ge0,&Y=\varnothing;\\G_x>D_Y,&Y\ne\varnothing.\end{cases}\)',2160,220)
 main('copy','核验并执行计划：释放 Y，确认后分配并复制 x\n复制成功才进入授信；冲突则重试，失败则清理本次分配',2480,160,size=27)
 main('allocation','Credit 分账：按当前输入重算 G，再分配额度\n固定 Agent ID 顺序；'+r'\(\mathbf T^{(i)}\)：前 i 个 Agent 使用 x，其余不用'+'\n'+r'\(W_{a_i,x}=\sum_{w\gets x}[\mathrm{WCT}_w(\mathbf T^{(i-1)})-\mathrm{WCT}_w(\mathbf T^{(i)})]\)'+'\n'+r'\(\sum_a W_{a,x}=G_x\)；使用上方收益式，内部块也按到 x 的前缀评估',2740,260,size=26)
 main('credit','新备份授信，或为本轮实际复用的 Agent 续租\n'+r'\(c_{a,x}\leftarrow\begin{cases}W_{a,x},&\text{新备份，或 a 复用且本轮未授信};\\\min(c_{a,x},W_{a,x}),&\text{其他已有份额}.\end{cases}\)'+'\n其他 Agent 已花掉的信用不补回；记录本轮续租已处理',3100,230,size=27)
 main('done',r'原子保存 \(\mathrm{Credit}_x=\sum_a c_{a,x}\) 与处理记录；更新 Q'+'\n内部块、读取中的块保留余额；不参与本次收租',3430,120,size=28)
 left('queue','更新 Q：无备份后继、未被读取的已提交尾块\n排除 x、必要前缀及释放中的块',1760,145,size=26)
 p.box('has-tail','还有可释放尾块？\n'+r'\(Q\ne\varnothing\)',165,2020,770,140,decision=True,size=27)
 left('revalue','按当前试算前缀重算各尾块 y 的额度\n使用 Credit 分账式（x 换为 y）\n'+r'\(c_{a,y}\leftarrow\min(c_{a,y},W_{a,y}),\quad\mathrm{Credit}_y=\sum_a c_{a,y}\)'+'\n这里只下调余额；没有实际复用就不续租',2260,225,size=26)
 left('rent','按物理字节收租，Agent 按剩余余额分摊\n'+r'\(\delta=\min_{y\in Q}\frac{\mathrm{Credit}_y}{b_y}\)'+'\n'+r'\(c_{a,y}\leftarrow c_{a,y}\left(1-\frac{b_y\delta}{\mathrm{Credit}_y}\right),\quad y\in Q\)'+'\n更新各块 Credit；零余额跳过除法',2590,225,size=26)
 left('remove','试删一个 Credit = 0 的尾块 y\n'+r'\(D_Y\leftarrow D_Y+\sum_{w\gets y}[\mathrm{WCT}_w(\mathbf T^{-y})-\mathrm{WCT}_w(\mathbf T)]\)'+'\n'+r'\(Y\leftarrow Y\cup\{y\},\quad f\leftarrow f+b_y\)'+'\n'+r'\(\mathbf T^{-y}\)：删除 y 后的恢复耗时；更新前缀与 Q',2910,245,size=25)
 left('no-space','本次不备份 x，丢弃回收试算\n已有备份与信用不受失败试算影响',3310,135,size=27)
 p.box('reject','本次不备份 x\n丢弃回收试算',2790,2170,820,140,size=28)
 p.box('copy-failed','等待复制，或清理后重试\n旧 ACK 不授信，已释放备份不回滚',2790,2470,820,160,size=27)
 # The only detached panel is the KV layout, not hidden algorithm steps.
 p.box('layout-title','一个共享 KV 块',2830,660,790,60,text=True,bold=True,size=30)
 p.box('layout-card',r'块 x · 大小 \(b_x\)'+'\nAgent A：最新 Slack、剩余信用\nAgent B：最新 Slack、剩余信用\n共享备份只占一份空间',2830,745,790,205,size=27)
 p.box('layout-pool-label','Peer HBM Pool',2830,1045,790,60,text=True,bold=True,size=29)
 for i,name in enumerate(['共享 x','A2','A3','B2','C1','空闲']):
  p.box('layout-slot-'+str(i),name,2830+(i%3)*265,1130+(i//3)*105,245,80,size=27)
 p.box('layout-note','内部块有后继：可续租，不可淘汰\n无后继且未被读取：进入 Q',2830,1395,790,110,text=True,size=27)
 p.chain('candidate','resident')
 p.edge('resident','allocation',out=(1,.5),into=(1,.5),points=[(2680,960),(2680,2870)],label='是：复用已有备份，直接续租',label_at=(2750,1650,890,65))
 p.edge('resident','prefix',label='否：新备份准入',label_at=(1900,1040,300,50))
 p.edge('prefix','wait-prefix',out=(0,.5),into=(1,.5),label='否',label_at=(1090,1155,80,50))
 p.edge('prefix','gain',label='是',label_at=(1890,1270,80,50));p.chain('gain','plan','fits')
 p.edge('fits','queue',out=(0,.5),into=(1,.5),points=[(1120,1990),(1120,1832.5)],label='否',label_at=(1260,1930,80,50));p.chain('queue','has-tail')
 p.edge('has-tail','revalue',label='是',label_at=(590,2180,80,50))
 p.edge('has-tail','no-space',out=(0,.5),into=(0,.5),points=[(25,2090),(25,3377.5)],label='否',label_at=(75,2160,80,50))
 p.chain('revalue','rent','remove')
 p.edge('remove','fits',out=(1,.5),into=(.15,1),points=[(1090,3032.5),(1090,2095),(1556,2095)])
 p.edge('fits','accept',label='是',label_at=(1890,2075,80,50))
 p.edge('accept','reject',out=(1,.5),into=(0,.5),label='否',label_at=(2420,2180,80,50))
 p.edge('accept','copy',label='是',label_at=(1890,2400,80,50))
 p.edge('copy','copy-failed',out=(1,.5),into=(0,.5),label='未成功',label_at=(2550,2460,140,50))
 p.edge('copy','allocation',label='成功',label_at=(1890,2670,110,50));p.chain('allocation','credit','done')
 p.box('footer','执行约束：同一 Pool 串行提交；复制按分配代次核验；新请求复用立即续租；无复用不续租，靠容量竞争收租回收。',65,3620,3630,65,text=True,size=25,align='left')
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
  'decision_flow_revision':{'events':'new chunk and request reuse; no Agent end event','renewal':'immediate, including internal blocks; only actually reusing Agent renews once per request','rent':'explicit remaining balances; no H or L state','ordering':'gain separate from fixed-ID grant attribution'},
  'model_boundary':'observed-prefix WCT cost model; idle records do not imply live requests or future value guarantees',
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
