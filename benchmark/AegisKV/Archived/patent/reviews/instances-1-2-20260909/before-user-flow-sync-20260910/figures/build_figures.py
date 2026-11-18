#!/usr/bin/env python3
"""Editable patent figures 2/3; native Draw.io exports are the delivery images."""
from pathlib import Path
from html import escape
import json
import xml.etree.ElementTree as E

OUT = Path(__file__).resolve().parent


class Figure:
    def __init__(self, stem, title, width, height):
        self.stem, self.width, self.height = stem, width, height
        self.book = E.Element('mxfile', host='app.diagrams.net', version='31.1.5')
        diagram = E.SubElement(self.book, 'diagram', id=stem, name=title)
        graph = E.SubElement(diagram, 'mxGraphModel', math='1', grid='1', gridSize='10',
                             page='1', pageWidth=str(width), pageHeight=str(height), background='#FFFFFF')
        self.root = E.SubElement(graph, 'root')
        E.SubElement(self.root, 'mxCell', id='0')
        E.SubElement(self.root, 'mxCell', id='1', parent='0')
        self.nodes, self.edges = {}, []
        self.box('canvas', '', 0, 0, width, height, text=True)

    def box(self, key, label, x, y, w, h, *, size=28, decision=False, text=False,
            bold=False, align='center', dashed=False, html=False):
        style = (f'fontFamily=Noto Sans CJK SC;fontSize={size};fontColor=#000000;'
                 f'whiteSpace=wrap;html=1;align={align};verticalAlign=middle;spacing=10;strokeWidth=2;')
        style += ('text;strokeColor=none;fillColor=none;' if text else
                  'strokeColor=#000000;fillColor=#FFFFFF;' + ('rhombus;' if decision else 'rounded=1;arcSize=6;'))
        if bold:
            style += 'fontStyle=1;'
        if dashed:
            style += 'dashed=1;dashPattern=5 4;'
        value = label if html else escape(label).replace('\n', '<br>')
        value = '<div style="line-height:1.35">' + value + '</div>'
        cell = E.SubElement(self.root, 'mxCell', id=key, value=value, style=style, vertex='1', parent='1')
        E.SubElement(cell, 'mxGeometry', x=str(x), y=str(y), width=str(w), height=str(h), attrib={'as': 'geometry'})
        self.nodes[key] = (x, y, w, h)
        return cell

    def edge(self, a, b, *, out=(.5, 1), into=(.5, 0), points=(), label='', label_at=None, size=30):
        key = f'edge-{len(self.edges)}'
        style = ('edgeStyle=orthogonalEdgeStyle;rounded=0;strokeColor=#000000;strokeWidth=2.5;'
                 'endArrow=block;endFill=1;endSize=10;jettySize=20;'
                 f'exitX={out[0]};exitY={out[1]};entryX={into[0]};entryY={into[1]};')
        cell = E.SubElement(self.root, 'mxCell', id=key, edge='1', parent='1', source=a, target=b, style=style)
        geo = E.SubElement(cell, 'mxGeometry', relative='1', attrib={'as': 'geometry'})
        if points:
            arr = E.SubElement(geo, 'Array', attrib={'as': 'points'})
            for x, y in points:
                E.SubElement(arr, 'mxPoint', x=str(x), y=str(y))
        self.edges.append((a, b))
        if label:
            assert label_at is not None
            cell = self.box(key+'-label', label, *label_at, size=size, text=True)
            cell.set('style', cell.get('style')+'fillColor=#FFFFFF;spacing=1;')

    def chain(self, *keys):
        for a, b in zip(keys, keys[1:]):
            self.edge(a, b)

    def save(self):
        ids = [c.get('id') for c in self.root]
        assert len(ids) == len(set(ids))
        for c in self.root:
            for attribute in ['source', 'target', 'parent']:
                assert not c.get(attribute) or c.get(attribute) in ids
            if c.get('edge'):
                assert c.find('mxGeometry') is not None
        for key, (x, y, w, h) in self.nodes.items():
            assert 0 <= x < x+w <= self.width and 0 <= y < y+h <= self.height, key
        E.indent(self.book)
        E.ElementTree(self.book).write(OUT/(self.stem+'.drawio'), encoding='utf-8', xml_declaration=True)
        return {'stem': self.stem, 'canvas': [self.width, self.height], 'edges': self.edges}


def benefit():
    f = Figure('figure-2-agent-credit', '附图2：Slack 到 KV 备份收益', 1600, 960)
    f.box('title', 'Slack 如何映射到 KV 分块的备份收益', 40, 10, 1520, 65, size=40, text=True, bold=True)
    f.box('symbols', r'\(a\)：当前 Agent；\(x\)：第 \(k_a+1\) 个完整块；\(b_x\)：物理字节数'
          '\n'+r'\(T_a(k)\)：使用前 k 块备份，恢复当前已生成 KV 所需的总时间',
          60, 95, 1480, 100, size=31, text=True, align='left')
    f.box('slack', '工作流输入\n本请求内固定的 Slack\n'+r'\(s_a\)',
          90, 250, 420, 195, size=35)
    f.box('recovery', 'KV 恢复代价\n'
          +r'\(T_a(k_a)\)：复用 x 之前的前缀，其后重算'+'\n'
          +r'\(T_a(k_a+1)\)：复用到 x，其后重算',
          650, 250, 860, 195, size=32)
    f.box('gain', '① 计算当前 Agent 的 KV 恢复收益\n'
          +r'\(G_{a,x}=\min\{T_a(k_a)-T_a(k_a+1),\ \max[T_a(k_a)-s_a,0]\}\)',
          100, 560, 1400, 150, size=34)
    f.box('density', '② 输出备份收益与单位字节收益\n'
          +r'\(G_{a,x},\qquad P_{a,x}=G_{a,x}/b_x\)',
          390, 790, 820, 130, size=36)
    f.edge('slack', 'gain', out=(.5,1), into=(.25,0), points=((300,505),(450,505)))
    f.edge('recovery', 'gain', out=(.5,1), into=(.75,0), points=((1080,505),(1150,505)))
    f.edge('gain','density')
    return f.save()


def rental():
    f = Figure('figure-3-slacklandlord', '附图3：SlackLandlord 租值键决策', 1800, 2030)
    f.box('title', 'SlackLandlord：KV 分块的租值键决策', 40, 5, 1720, 65, size=42, text=True, bold=True)
    f.box('symbols',
          r'\(x\)：本次处理的完整块；\(Q\)：本池已提交备份中可安全释放的尾块队列'
          '\n'+r'\(L\)：本池累计租金；\(H_x\)：租值键；\(c_{u,x}\)：Agent u 的信用份额'
          '\n'+r'\(L^{\prime},Y,f\)：试算租金、待回收块、可用字节；y：Q 中 H 最小的尾块；z：新尾块'
          '\n所有占用本池的备份均收租；Q 仅控制能否淘汰。Peer-HBM 与 DRAM 各自执行。',
          60, 80, 1680, 160, size=31, text=True, align='left')
    f.box('input', '① 请求去重、块状态就绪后，读取本次输入\n'
          +r'\(a,\ x,\ b_x,\ G_{a,x}\)'+'（收益由附图 2 提供）',
          360, 270, 1080, 100, size=34)
    f.box('resident', '本池已有 x 的\n已提交备份？', 600, 430, 600, 130, size=34, decision=True)
    f.edge('input','resident')
    f.box('settle', '②a 已有副本：按本池 L 结算旧租金\n'
          +r'\(\mathrm{Credit}_x\leftarrow b_x\max(H_x-L,0)\)'+'\n'
          +r'\('
          +r'c_{u,x}\leftarrow c_{u,x}\cdot\frac{\mathrm{Credit}_x}{\sum_v c_{v,x}}\)'+'\n'
          +'所有备份均收租，无需判断 x 是否在 Q\n'
          +'分母取结算前总额，0 则跳过',
          60, 620, 900, 245, size=31)
    f.edge('resident','settle',out=(0,.5),into=(.5,0),points=((510,495),),
           label='是',label_at=(530,440,65,40),size=31)
    f.box('renew', '只续租当前 Agent a\n'
          +r'\(c_{a,x}\leftarrow G_{a,x},\quad \mathrm{Credit}_x\leftarrow\sum_u c_{u,x}\)'+'\n'
          +r'\(H_x\leftarrow L+\mathrm{Credit}_x/b_x\)'+'\n'
          +'保存本请求记录；在 Q 时同步更新堆项',
          60, 925, 900, 190, size=31)
    f.edge('settle','renew')
    f.box('initialize', '②b 无备份：初始化候选信用\n'
          +r'\(L^{\prime}\leftarrow L,\quad c_{a,x}\leftarrow G_{a,x}\)'+'\n'
          +r'\(H_x\leftarrow L^{\prime}+G_{a,x}/b_x\)'+'\n'
          +r'\(x\notin Q\)；其他 Agent 的份额为 0',
          1030, 620, 700, 195, size=31)
    f.edge('resident','initialize',out=(1,.5),into=(.5,0),points=((1380,495),),
           label='否',label_at=(1230,440,65,40),size=31)
    f.box('trial', '③ 保护必要前缀，建立临时账本\n'
          +r'\(Y\leftarrow\varnothing\)'+'\n'
          +r'\(f\leftarrow\text{Pool 可用字节}\)'+'\n'
          +'保护块退出临时 Q，H 与收租不变',
          1010, 910, 740, 205, size=31)
    f.edge('initialize','trial')
    f.box('capacity', '空间足够？\n'+r'\(f\ge b_x\)', 650, 1210, 500, 120, size=34, decision=True)
    f.edge('trial','capacity',points=((1380,1150),(900,1150)))
    f.box('choose', r'\(Q\ne\varnothing\)，且'+'\n'+r'\(\max(L^{\prime},H_y)<H_x\)？',
          150, 1370, 620, 195, size=33, decision=True)
    f.edge('capacity','choose',out=(0,.5),into=(.5,0),points=((460,1270),),label='否',label_at=(505,1215,65,40),size=31)
    f.box('reject', '拒绝本次准入\n丢弃临时账本\n实际状态不变', 870, 1395, 250, 140, size=31)
    f.edge('choose','reject',out=(1,.5),into=(0,.5),label='否',label_at=(795,1415,65,40),size=31)
    f.box('rent', '④ 试删 y，并从临时 Q 移除\n'
          +r'\(L^{\prime}\leftarrow\max(L^{\prime},H_y)\)'+'\n'
          +r'\(Y\leftarrow Y\cup\{y\},\quad f\leftarrow f+b_y\)'+'\n'
          +r'新尾块 z 以原 \(H_z\) 入 Q'+'\n'
          +r'所有 H 保持不变；按 \(L^{\prime}\) 试算扣租',
          50, 1610, 820, 240, size=31)
    f.edge('choose','rent',label='是',label_at=(505,1567,65,40),size=31)
    f.edge('rent','capacity',out=(0,.5),into=(.5,0),points=((25,1730),(25,1170),(900,1170)))
    f.box('commit', '⑤ 核验后提交并执行\n'
          +r'\(L\leftarrow L^{\prime}\)'+'\n'
          +r'\(c_{a,x}\leftarrow b_x\max(H_x-L^{\prime},0)\)'+'\n'
          +'等待实际释放\n分配空间 → 复制',
          1220, 1370, 525, 245, size=31)
    f.edge('capacity','commit',out=(1,.5),into=(.5,0),points=((1482.5,1270),),label='是',label_at=(1230,1215,65,40),size=31)
    f.box('publish', '⑥ 发布备份，记录处理结果\n'
          +r'\(c_{a,x}\leftarrow b_x\max(H_x-L,0)\)'+'\n'
          +r'复制期间继续收租，保留原 \(H_x\)'+'\n'
          +'解除保护，安全尾块入 Q',
          1215, 1690, 535, 185, size=31)
    f.edge('commit','publish')
    f.box('notes', '空闲容量允许零 Credit；核验冲突重读①。\n进行中或未就绪先等待；重复或过期不授信。',
          65, 1900, 850, 95, size=30, text=True)
    return f.save()


if __name__ == '__main__':
    result = [benefit(), rental()]
    (OUT/'STRUCTURE.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps([{k:v for k,v in x.items() if k!='edges'} for x in result],ensure_ascii=False))
