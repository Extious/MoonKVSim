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
    f = Figure('figure-2-agent-credit', '附图2：Agent 恢复收益与租值键', 1100, 1320)
    f.box('title', '单 Agent 恢复收益与共享块租值键', 35, 10, 1030, 60, size=34, bold=True, text=True)
    f.box('symbols',
          r'\(a\)：本次 Agent；\(u,v\)：块的引用 Agent；\(x\)：第 \(k_a+1\) 个完整块；\(b_x\)：物理字节数'
          '\n'+r'\(s_a\)：本请求固定 Slack；\(c_{u,x}\)：Agent 份额；\(\mathrm{Credit}_x\)：块总余额'
          '\n'+r'\(L\)：本池累计每字节租金，初值 0；\(H_x\)：块租值键；\(Q\)：可释放尾块队列',
          30, 85, 1040, 110, size=24, text=True, align='left')
    f.box('input', '① 读取本请求与当前块\n'+r'\(a,\ s_a,\ x,\ b_x,\ k_a\)'+'；仅评估当前已生成的 KV',
          65, 215, 970, 85, size=27)
    f.box('time', '', 65, 345, 970, 270)
    f.box('time-title', '② 累计前缀复用时间与剩余重算时间', 85, 357, 930, 45, size=27, bold=True, text=True)
    f.box('before', r'\(T_a(k_a)\)', 95, 424, 180, 55, size=28, text=True)
    f.box('after', r'\(T_a(k_a+1)\)', 75, 497, 200, 55, size=28, text=True)
    for row, y in [('before', 422), ('after', 495)]:
        f.box(row+'-prefix', r'前 \(k_a\) 块：复用', 290, y, 280, 57, size=24)
        f.box(row+'-x', 'x：'+('重算' if row=='before' else '复用'), 590, y, 145, 57,
              size=24, dashed=row=='before')
        f.box(row+'-suffix', '已生成后缀：重算', 755, y, 250, 57, size=24, dashed=True)
    f.box('time-note', '刚生成 x 时，其后没有已生成后缀；续租内部块时，后缀仍计入重算。',
          90, 560, 920, 40, size=23, text=True)
    f.box('gain', '③ 只计算当前 Agent 的恢复收益与密度\n'
          +r'\(G_{a,x}=\min\{T_a(k_a)-T_a(k_a+1),\ \max[T_a(k_a)-s_a,0]\}\)'
          +'\n'+r'\(P_{a,x}=G_{a,x}/b_x\)', 65, 660, 970, 150, size=26)
    f.box('settle', '④ 先结算已有块的旧租金\n'
          +r'\(x\in Q:\quad \mathrm{Credit}_x\leftarrow b_x\max(H_x-L,0)\)'
          +'\n'+r'\(c_{u,x}\leftarrow c_{u,x}\,\frac{\mathrm{Credit}_x}{\sum_v c_{v,x}}\quad(\forall u)\)'
          +'\n分母统一取结算前总额；总额为 0 时跳过。'
          +'\n不在 Q 的块保留冻结份额；新副本从空分账开始。',
          65, 855, 970, 215, size=26)
    f.box('renew', '⑤ 只续租 a，暂存共享块的 Credit 与 H\n'
          +r'\(c_{a,x}\leftarrow G_{a,x},\quad \mathrm{Credit}_x\leftarrow\sum_u c_{u,x}\)'
          +'\n'+r'\(H_x\leftarrow L+\mathrm{Credit}_x/b_x\)'
          +'\n其他 Agent 保留租后余额；交由附图 3 保存或进行新副本准入。',
          65, 1115, 970, 165, size=26)
    f.chain('input', 'time', 'gain', 'settle', 'renew')
    return f.save()


def rental():
    f = Figure('figure-3-slacklandlord', '附图3：SlackLandlord 完整决策与提交', 1800, 2400)
    f.box('title', 'SlackLandlord：一次 Agent 请求中一个 KV chunk 的决策',
          30, 5, 1740, 70, size=42, text=True, bold=True)
    f.box('symbols',
          r'\(L\)：本池租金；\(L^{\prime}\)：试算租金；\(H\)：租值键；\(b_x\)：x 的物理字节数'
          '\n'+r'\(Q\)：按 H 排序的可释放物理尾块；排除必要前缀、读取及其他操作保护块'
          '\n'+r'\(Y\)：试算回收块；\(f\)：试算可用字节；\(y,z\)：旧尾块、新暴露尾块'
          '\n共享块检查全部备份后继；每个 Pool 独立维护 L、Q、分账和副本状态。',
          50, 80, 1700, 180, size=32, text=True, align='left')
    f.box('pools', 'Peer-HBM 与 DRAM 各自执行下列流程，均由源 Worker 直接复制\n'
          '两池分别确认；组合为 HBM_ONLY / DRAM_ONLY / HBM_AND_DRAM / BYPASS',
          80, 280, 1640, 95, size=32)
    f.box('check', '① 读取 a 本请求中的完整块 x\n去重键：副本代次、Agent、请求号\n新副本须源完整、必要前缀已提交',
          120, 430, 900, 155, size=34)
    f.box('skip', '重复或过期\n本次结束，不授信', 1260, 420, 440, 95, size=34)
    f.box('wait', '备份 / 释放中，或未就绪\n等待后回①重读', 1190, 550, 510, 95, size=34)
    f.edge('check', 'skip', out=(1,.25), into=(0,.5), points=((1130,468.75),(1130,467.5)))
    f.edge('check', 'wait', out=(1,.8), into=(0,.5), points=((1100,554),(1100,597.5)))
    f.box('renew', '② 按附图 2 估值、结算旧租金、只续租 a\n'+r'暂存各 Agent 份额、\(\mathrm{Credit}_x\) 与 \(H_x\)',
          120, 675, 900, 110, size=34)
    f.edge('check','renew',label='可处理',label_at=(600,610,145,45),size=32)
    f.box('resident', '已有 COMMITTED\n副本？', 310, 850, 520, 145, size=34, decision=True)
    f.box('save', '保存分账与已处理记录\n按状态更新 Q 或冻结份额\n本层续租结束', 1190, 835, 510, 165, size=34)
    f.edge('renew','resident')
    f.edge('resident','save',out=(1,.5),into=(0,.5),label='是',label_at=(980,890,70,45),size=32)
    f.box('trial', '③ 建立 L、Q 和账本的临时副本\n'
          +r'\(L^{\prime}\leftarrow L,\quad Y\leftarrow\varnothing,\quad f\leftarrow\text{可用字节}\)'
          +'\n保护 x 的必要前缀：退出 Q 前结算，再冻结', 120, 1070, 900, 170, size=34)
    f.edge('resident','trial',label='否：新副本',label_at=(610,1010,230,45),size=32)
    f.box('capacity', '空间足够？\n'+r'\(f\ge b_x\)', 310, 1310, 520, 140, size=34, decision=True)
    f.edge('trial','capacity')
    f.box('choose', r'\(Q\ne\varnothing\) 且最小键满足'+'\n'+r'\(H_y<H_x\)？',
          265, 1560, 610, 165, size=34, decision=True)
    f.edge('capacity','choose',label='否',label_at=(600,1485,70,45),size=32)
    f.box('reject', '拒绝提案\n丢弃试算\n实账不变', 960, 1575, 220, 135, size=32)
    f.edge('choose','reject',out=(1,.5),into=(0,.5),label='否',label_at=(889,1590,65,40),size=32)
    f.box('rent', '④ 试删尾块 y，并从临时 Q 移除\n'
          +r'\(L^{\prime}\leftarrow H_y,\quad Y\leftarrow Y\cup\{y\},\quad f\leftarrow f+b_y\)'
          +'\n'+r'新尾块 z：\(H_z\leftarrow L^{\prime}+\sum_u c_{u,z}/b_z\)，入 Q'
          +'\n'+r'候选 \(H_x\) 与持续在 Q 中的 H 保持不变',
          120, 1810, 900, 220, size=34)
    f.edge('choose','rent',label='是',label_at=(600,1750,70,45),size=32)
    f.edge('rent','capacity',out=(0,.5),into=(0,.5),points=((65,1920),(65,1380)))
    f.box('empty', '空闲容量允许零 Credit；试算拒绝不改实账和请求标记。',
          100, 2070, 950, 55, size=31, text=True)

    f.box('validate','⑤ 提交前状态\n核验通过？',1220,1265,440,170,size=34,decision=True)
    f.edge('capacity','validate',out=(1,.5),into=(0,.5),points=((1080,1380),(1080,1350)),label='是',
           label_at=(900,1310,70,45),size=32)
    f.box('retry','冲突：丢弃试算，回①重读\n核验请求、L/Q、代次、保护与容量',
          1175,1090,555,110,size=32)
    f.edge('validate','retry',out=(.5,0),into=(.5,1),label='否',label_at=(1465,1205,65,45),size=32)
    f.box('commit','⑥ 提交试算，冻结候选余额\n'
          +r'\(L\leftarrow L^{\prime}\)'+'\n'+r'\(c_{a,x}\leftarrow b_x\max(H_x-L^{\prime},0)\)'
          +'\n撤销 Y 的恢复资格，等待实际释放\n释放完成后，分配 x 的空间',
          1220,1510,500,225,size=32)
    f.edge('validate','commit',label='是',label_at=(1490,1450,65,45),size=32)
    f.box('copy','PENDING → 本层直接复制\nPeer-HBM：D2D / P2P\nDRAM：D2H\n复制期间 x 不在 Q，份额冻结',
          1220,1800,500,180,size=32)
    f.edge('commit','copy')
    f.box('success','执行与校验\n全部成功？',1260,2035,420,130,size=34,decision=True)
    f.edge('copy','success')
    f.box('abort','ABORTED：不发布 x，按实清理\n已释放块与 L 不回滚\n未释放占用仍计入容量\n本层失败不取消另一层',
          1170,2200,600,185,size=32)
    f.edge('success','abort',label='否',label_at=(1495,2160,65,40),size=30)
    f.edge('commit','abort',out=(1,.5),into=(1,.5),points=((1785,1622.5),(1785,2292.5)),
           label='失败',label_at=(1720,1740,75,45),size=32)
    f.box('publish','⑦ 发布 COMMITTED 并记录授信\n'
          +r'\(H_x\leftarrow L+\sum_u c_{u,x}/b_x\)'+'（此时的 L）'
          +'\n释放本次保护；安全尾块按当前 L 入 Q'
          +'\n保留租后余额，不补满信用',
          120,2170,900,195,size=34)
    f.edge('success','publish',out=(0,.5),into=(1,.5),points=((1100,2100),(1100,2267.5)),
           label='是',label_at=(1080,2130,65,45),size=30)
    return f.save()


if __name__ == '__main__':
    result = [benefit(), rental()]
    (OUT/'STRUCTURE.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps([{k:v for k,v in x.items() if k!='edges'} for x in result],ensure_ascii=False))
