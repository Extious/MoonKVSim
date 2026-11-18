"""Editable, native Draw.io schematics; all masks are constructed examples."""
from pathlib import Path
import json
import xml.etree.ElementTree as ET

OUT = Path(__file__).resolve().parent
C = dict(ink='#17324D', muted='#53677B', line='#C6D1DD', blue='#377BB5',
         light='#EAF3FC', green='#2D8C77', mint='#E6F4EF', orange='#BA7127',
         cream='#FFF3E3', grey='#E8ECF1', white='#FFFFFF', purple='#7666A7')


class Diagram:
    def __init__(self, name, height):
        self.name, self.height, self.i = name, height, 1
        self.doc = ET.Element('mxfile', host='app.diagrams.net', version='31.1.5')
        page = ET.SubElement(self.doc, 'diagram', name=name, id=name)
        model = ET.SubElement(page, 'mxGraphModel', dx='1200', dy=str(height),
                              grid='1', gridSize='10', page='1', pageScale='1',
                              pageWidth='1200', pageHeight=str(height), background='#FFFFFF')
        self.root = ET.SubElement(model, 'root')
        ET.SubElement(self.root, 'mxCell', id='0')
        ET.SubElement(self.root, 'mxCell', id='1', parent='0')
        self.box('', 0, 0, 1200, height, fill='white', stroke='none')

    def box(self, label, x, y, w, h, fill='white', stroke='line', size=23,
            color='ink', bold=False, align='center', rounded=False, extra=''):
        self.i += 1
        style = (f'rounded={int(rounded)};whiteSpace=wrap;html=0;'
                 f'fillColor={C.get(fill,fill)};strokeColor={C.get(stroke,stroke)};'
                 f'fontColor={C.get(color,color)};fontFamily=Noto Sans CJK SC;'
                 f'fontSize={size};fontStyle={int(bold)};align={align};'
                 f'verticalAlign=middle;spacing=4;strokeWidth=1.4;{extra}')
        cell = ET.SubElement(self.root, 'mxCell', id=str(self.i), value=label,
                             style=style, vertex='1', parent='1')
        ET.SubElement(cell, 'mxGeometry', x=str(x), y=str(y), width=str(w),
                      height=str(h), attrib={'as': 'geometry'})
        return str(self.i)

    def text(self, label, x, y, w, h, size=23, color='ink', bold=False, align='left'):
        return self.box(label, x,y,w,h, fill='none', stroke='none', size=size,
                        color=color, bold=bold, align=align)

    def edge(self, points, dashed=False, color='muted', width=2, end=True):
        self.i += 1
        cell = ET.SubElement(self.root, 'mxCell', id=str(self.i), value='',
                             style=(f'endArrow={"block" if end else "none"};endFill=1;'
                                    f'strokeColor={C.get(color,color)};strokeWidth={width};'
                                    f'dashed={int(dashed)};rounded=0;'), edge='1', parent='1')
        geo = ET.SubElement(cell, 'mxGeometry', relative='1', attrib={'as':'geometry'})
        for point, role in [(points[0],'sourcePoint'), (points[-1],'targetPoint')]:
            ET.SubElement(geo, 'mxPoint', x=str(point[0]), y=str(point[1]), attrib={'as':role})
        if len(points)>2:
            arr=ET.SubElement(geo, 'Array', attrib={'as':'points'})
            for x,y in points[1:-1]: ET.SubElement(arr, 'mxPoint', x=str(x), y=str(y))

    def title(self, n, title, subtitle):
        self.box(str(n), 30,25,44,44, fill='ink', stroke='ink', color='white', bold=True, size=27)
        self.text(title,85,23,1080,49,size=30,bold=True)
        self.text(subtitle,30,79,1140,40,size=21,color='muted')

    def save(self):
        ET.indent(self.doc)
        p=OUT/(self.name+'.drawio')
        ET.ElementTree(self.doc).write(p, encoding='utf-8', xml_declaration=True)
        return p


def prefill_overview():
    d=Diagram('01-prefill-overview',1030)
    d.title(1,'Sparse prefill：每个输入都计算，每个 query 只连接部分历史',
            '单层逻辑示意 · 冷启动输入 12 个已知 token · 多个 query 可并行分块执行')
    d.text('本层输入',30,134,115,50,bold=True)
    for j in range(12):
        d.box(f'x{j+1}',160+j*82,140,70,43,fill='light',stroke='blue',size=22)
    d.text('第一层使用 token embedding；后续层使用上一层的全部位置表示。',155,192,1000,36,size=21,color='muted')
    d.edge([(650,231),(650,256)])
    d.box('所有新输入位置生成本层 Q、K、V / 对应压缩表示',180,260,930,55,fill='light',stroke='blue',bold=True)
    d.edge([(650,315),(650,343)])
    d.box('较轻的摘要 / indexer 打分 → 因果约束下选位置或选块 → 主 attention',95,347,1030,57,fill='mint',stroke='green',size=24,bold=True)
    d.text('以下矩阵只表示主 attention 的连接；选择器本身也有计算和状态开销。',95,416,1030,35,size=21,color='muted')

    masks={}
    for kind,base in [('dense',30),('sparse',620)]:
        title='Dense causal attention' if kind=='dense' else 'Block-sparse causal attention'
        d.text(title,base+30,455,520,36,size=25,bold=True,align='center')
        x,y,s=base+136,555,26
        d.text('Key 的位置 j',x,496,312,25,size=21,align='center')
        d.text('Query\n位置 i',base+10,y+111,87,75,size=20,align='center')
        matrix=[]
        for i in range(12):
            # Illustration only: a completed historical block plus the latest 3 tokens.
            earlier=i//3
            chosen=((i*2+1)%earlier) if earlier else None
            selected=set(range(max(0,i-2),i+1))
            if chosen is not None: selected.update(range(chosen*3,chosen*3+3))
            row=[]
            d.text(str(i+1),x-35,y+i*s,30,s,size=16,align='center')
            d.text(str(i+1),x+i*s,y-30,s,25,size=16,align='center')
            for j in range(12):
                v=0 if j>i else (1 if kind=='dense' or j in selected else 2)
                row.append(v)
                d.box('',x+j*s,y+i*s,s,s,fill={0:'grey',1:'blue',2:'white'}[v],
                      stroke='white' if v!=2 else 'line',extra='strokeWidth=1;')
            matrix.append(row)
        masks[kind]=matrix
        if kind=='sparse':
            for b in range(1,4):
                d.edge([(x+b*3*s,y),(x+b*3*s,y+12*s)],color='muted',width=1,end=False)
    legend=[('blue','实际计算的连接'),('white','允许访问但未选中'),('grey','未来位置：禁止访问')]
    for k,(color,label) in enumerate(legend):
        lx=78+k*385
        d.box('',lx,883,22,22,fill=color,stroke='line')
        d.text(label,lx+33,876,335,34,size=21)
    d.text('示意选法：每个 query 选择一个完整历史块＋最近 3 个位置；不是任何模型的实测掩码。',35,924,1130,36,size=20,color='muted')
    d.box('所有位置的 attention 输出 → 残差 / FFN → 下一层；直到最后一层',70,972,1060,41,fill='light',stroke='none',size=23,bold=True)
    d.save()
    return masks


def nsa_branches():
    d=Diagram('02-nsa-branches',1020)
    d.title(2,'NSA：一个 query 的三条注意力路径',
            '单层、单个 query 位置 i 的数据依赖图 · prefill 会对全部新输入位置执行这套计算')
    d.box('当前 query  qᵢ',425,135,350,50,fill='light',stroke='blue',bold=True)
    d.text('共享 query；三个分支使用各自的 K、V',290,194,620,35,size=22,color='muted',align='center')
    for x in [210,600,990]:
        d.edge([(600,232),(600,245),(x,245),(x,270)],color='blue')
    cols=[(30,'① 压缩分支','mint','green'),(420,'② 选择分支','light','blue'),(810,'③ 局部窗口','cream','orange')]
    for x,label,fill,stroke in cols:
        d.box('',x,274,360,503,fill=fill,stroke='none',rounded=True)
        d.text(label,x+15,285,330,44,size=27,bold=True,align='center')
    d.box('历史 KV 块\nB1    B2    B3    …',50,347,320,75,fill='white',stroke='green',size=23)
    d.edge([(210,422),(210,447)],color='green')
    d.box('学习式压缩（MLP）\n每个块 → 更短的 K / V 表示',50,451,320,85,fill='white',stroke='green',size=21)
    d.edge([(210,536),(210,569)],color='green')
    d.box('qᵢ 对因果可见的摘要\n计算 compressed attention',50,573,320,79,fill='white',stroke='green',size=21)
    d.edge([(210,652),(210,692)],color='green')
    d.box('压缩输出  Ocmp',60,698,300,50,fill='green',stroke='green',color='white',bold=True)

    d.box('本分支的原始精度 KV\nB1    B2    B3    …',440,347,320,75,fill='white',stroke='blue',size=23)
    d.text('按块分数取 Top-k',448,470,305,34,size=22,bold=True,align='center')
    d.box('只读取选中的 KV 块\n例如：B1、B3',440,518,320,68,fill='white',stroke='blue',size=23)
    # Rank scores leave compression attention, reach selector without crossing raw KV flow.
    d.edge([(370,613),(402,613),(402,489),(438,489)],dashed=True,color='green')
    d.edge([(600,422),(600,449)],color='blue')
    d.edge([(600,505),(600,516)],dashed=True,color='green')
    d.edge([(600,586),(600,610)],color='blue')
    d.box('qᵢ 对选中块做 attention',440,614,320,43,fill='white',stroke='blue',size=21)
    d.edge([(600,657),(600,692)],color='blue')
    d.box('选择输出  Osel',450,698,300,50,fill='blue',stroke='blue',color='white',bold=True)

    d.box('本分支的最近 w 个位置\n…   i−2   i−1   i',830,347,320,75,fill='white',stroke='orange',size=22)
    d.edge([(990,422),(990,569)],color='orange')
    d.box('qᵢ 对局部窗口\n计算 window attention',830,573,320,79,fill='white',stroke='orange',size=22)
    d.edge([(990,652),(990,692)],color='orange')
    d.box('窗口输出  Owin',840,698,300,50,fill='orange',stroke='orange',color='white',bold=True)
    for x in [210,600,990]:
        d.edge([(x,751),(x,806),(600,806),(600,832)])
    d.box('学习式门控合并：Oᵢ = gc · Ocmp + gs · Osel + gw · Owin',110,837,980,58,
          fill='light',stroke='blue',size=24,bold=True)
    d.text('实线：数据依赖       虚线：选择依据 / 索引       门控权重由当前隐藏状态产生',60,913,1080,34,size=21,color='muted',align='center')
    d.text('因果约束也适用于压缩摘要：query 不能借摘要看到未来 token。',40,955,1120,33,size=21,color='muted',align='center')
    d.text('结构依据：NSA §3.3；图内 B1 / B3 仅为选择示意，无时延或收益测量。',40,986,1120,26,size=18,color='muted',align='center')
    d.save()


def working_set():
    d=Diagram('03-prefill-working-set',885)
    d.title(3,'增量 prefill：每个 query 很稀疏，整批需要的 KV 却可能很多',
            '恢复场景示意 · 已有前缀 8 个等大 KV 块＋同一 Agent 下一轮的 4 个新输入 token')
    d.text('已有前缀 KV',30,145,210,45,size=24,bold=True)
    x,y,w,h=270,140,102,58
    for j in range(8):
        fill,stroke=('mint','green') if j<2 else ('cream','orange')
        d.box(f'B{j+1}',x+j*w,y,w-6,h,fill=fill,stroke=stroke,size=25,bold=True)
    d.text('Peer HBM',x,207,w*2-6,36,size=22,color='green',bold=True,align='center')
    d.text('DRAM',x+2*w,207,w*6-6,36,size=22,color='orange',bold=True,align='center')
    d.text('新增输入',30,272,210,42,size=24,bold=True)
    for i in range(4):
        d.box(f'u{i+1}',270+i*112,268,95,50,fill='light',stroke='blue',size=24)
    d.text('只为新增输入生成新的 Q / K / V',750,270,420,48,size=22,color='muted')
    d.text('每个 query 选择的历史块（构造示例）',30,345,1130,42,size=25,bold=True)
    selected=[]
    for i in range(4):
        ry=402+i*69
        d.text(f'q(u{i+1})',38,ry,130,52,size=25,bold=True)
        d.text('选 2 / 8',168,ry,94,52,size=20,color='muted')
        blocks=[2*i+1,2*i+2]
        selected.append(blocks)
        for j in range(8):
            hit=j+1 in blocks
            fill,stroke=('mint','green') if j<2 else ('cream','orange')
            d.box(f'B{j+1}' if hit else '·',x+j*w,ry,w-6,52,
                  fill=fill if hit else 'white',stroke=stroke if hit else 'line',
                  size=25,color='ink' if hit else 'muted',bold=hit)
    d.box('单个 query：2 / 8 = 25%\n4 个 query 的并集：8 / 8 = 100%',70,699,510,97,fill='light',stroke='blue',size=25,bold=True)
    d.box('只有 B1、B2 在 Peer HBM\n后面三个 query 仍需 DRAM 中的块',610,699,520,97,fill='cream',stroke='orange',size=23,bold=True)
    d.text('仅画一个层 / KV 组的动态历史选择；局部窗口、新 KV、摘要或 indexer 状态须另计。',35,811,1130,29,size=20,color='muted')
    d.text('并集表示这段计算期间用到的块，不要求它们同时驻留 HBM；传输与计算能否重叠取决于调度。',35,846,1130,29,size=20,color='muted')
    d.save()
    return selected


if __name__=='__main__':
    masks=prefill_overview()
    nsa_branches()
    selected=working_set()
    evidence=dict(evidence_type='constructed schematic, not measured',
                  overview=dict(tokens=12,block_size=3,local_positions=3,
                                encoding={'0':'future-forbidden','1':'attended','2':'eligible-not-selected'},masks=masks),
                  incremental=dict(equal_size_historical_blocks=8,new_queries=4,
                                   selected_blocks=selected,peer_blocks=[1,2],dram_blocks=[3,4,5,6,7,8],
                                   per_query_fraction=0.25,union_fraction=1.0))
    (OUT/'EXAMPLES.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n')
    print('Created three editable diagrams and EXAMPLES.json')
