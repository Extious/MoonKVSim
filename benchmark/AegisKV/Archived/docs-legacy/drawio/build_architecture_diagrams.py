#!/usr/bin/env python3
"""Build two editable architecture diagrams; export with official Draw.io CLI."""
from pathlib import Path
import xml.etree.ElementTree as ET

OUT = Path(__file__).resolve().parent
BLUE = '#2463A0'
PURPLE = '#7543B5'
ORANGE = '#C36816'
GREEN = '#14806B'
INK = '#22334A'
GRAY = '#62748B'
FONT = 'Noto Sans CJK SC'


class Diagram:
    def __init__(self, name, title, subtitle, aegis=False):
        self.name = name
        self.file = ET.Element('mxfile', host='app.diagrams.net', version='31.1.5')
        page = ET.SubElement(self.file, 'diagram', id=name, name=title)
        graph = ET.SubElement(page, 'mxGraphModel', grid='1', gridSize='10',
                              page='1', pageScale='1', pageWidth='1800', pageHeight='1760',
                              background='#FFFFFF', math='0')
        self.root = ET.SubElement(graph, 'root')
        ET.SubElement(self.root, 'mxCell', id='0')
        ET.SubElement(self.root, 'mxCell', id='1', parent='0')
        self.serial = 0
        self.node('title', title, 40, 25, 1720, 58, label=True, bold=True, size=36)
        self.node('subtitle', subtitle, 40, 88, 1720, 35, label=True, size=21, color=GRAY)
        labels = [(300, BLUE, '蓝色：已有基础能力'),
                  (700, PURPLE, '紫色：AegisKV 新增或扩展' if aegis else '原生对象缓存与共享 KV'),
                  (1120, ORANGE, '实线：KV 写入'),
                  (1450, GREEN, '绿色：读取 / 恢复')]
        for i, (x, color, text) in enumerate(labels):
            self.node('legend'+str(i), text, x, 323, 390 if i < 2 else 300, 38,
                      label=True, color=color if aegis or i != 1 else GRAY, size=20)

    def node(self, id, text, x, y, w, h, *, color=INK, fill='#FFFFFF',
             parent='1', container=False, label=False, bold=False, size=22,
             align='center', shape=None):
        if label:
            style = 'text;strokeColor=none;fillColor=none;'
        else:
            style = (f'rounded=1;arcSize=10;strokeWidth=2;strokeColor={color};'
                     f'fillColor={fill};')
        style += (f'fontFamily={FONT};fontSize={size};fontColor={color};'
                  f'whiteSpace=wrap;html=0;spacing=8;verticalAlign=middle;align={align};')
        if bold:
            style += 'fontStyle=1;'
        if container:
            style += 'container=1;pointerEvents=0;'
        if shape:
            style += f'shape={shape};'
        c = ET.SubElement(self.root, 'mxCell', id=id, value=text, style=style,
                          vertex='1', parent=parent)
        ET.SubElement(c, 'mxGeometry', x=str(x), y=str(y), width=str(w), height=str(h),
                      attrib={'as': 'geometry'})

    def group(self, id, title, x, y, w, h, *, color=BLUE, fill='#F7FAFE', parent='1', size=25):
        self.node(id, '', x, y, w, h, color=color, fill=fill, container=True, parent=parent)
        self.node(id+'-title', title, 16, 8, w-32, 45, label=True, bold=True, size=size,
                  align='left', color=color, parent=id)

    def edge(self, id, source, target, *, color=GRAY, dashed=False, points=(),
             exit=(1, .5), entry=(0, .5), both=False, width=3):
        style = (f'edgeStyle=orthogonalEdgeStyle;rounded=1;strokeWidth={width};'
                 f'strokeColor={color};endArrow=block;endFill=1;endSize=10;'
                 f'exitX={exit[0]};exitY={exit[1]};entryX={entry[0]};entryY={entry[1]};'
                 'exitPerimeter=1;entryPerimeter=1;html=0;jettySize=20;')
        if dashed:
            style += 'dashed=1;dashPattern=6 5;'
        if both:
            style += 'startArrow=block;startFill=1;startSize=10;'
        c = ET.SubElement(self.root, 'mxCell', id=id, edge='1', parent='1',
                          source=source, target=target, style=style)
        g = ET.SubElement(c, 'mxGeometry', relative='1', attrib={'as': 'geometry'})
        if points:
            a = ET.SubElement(g, 'Array', attrib={'as': 'points'})
            for x, y in points:
                ET.SubElement(a, 'mxPoint', x=str(x), y=str(y))

    def save(self):
        ET.indent(self.file)
        ET.ElementTree(self.file).write(OUT/(self.name+'.drawio'), encoding='utf-8',
                                        xml_declaration=True)


def application(d, aegis):
    color = PURPLE if aegis else BLUE
    d.group('application', 'APPLICATION  ·  应用层' + ('  /  新增 Algorithm 1' if aegis else ''),
            40, 140, 1720, 160, color=color, fill='#FAF7FE' if aegis else '#F7FAFE')
    if aegis:
        for i, text in enumerate(('观测 workflow 进度\nrequest / tool return',
                                  'GBDT 预测残余时间\n仅使用因果可见特征',
                                  '残余 DAG 上运行 CPM\n校准后发布 branch Slack',
                                  'LLM request + Slack\n缺图 / 缺预测时取零')):
            d.node('app'+str(i), text, 40+i*430, 65, 350, 75, parent='application',
                   color=color, size=21)
        for i in range(3):
            d.edge('app-edge'+str(i), 'app'+str(i), 'app'+str(i+1), color=color)
    else:
        d.node('app0', 'LLM 应用 / Workflow\n发送 prompt 与生成请求', 20, 65, 420, 75,
               parent='application', color=BLUE, size=22)
        d.node('application-note', '缓存 key 与布局由推理框架 / Connector 定义\nStore 与 Transfer Engine 不计算 workflow Slack',
               590, 65, 1090, 75, parent='application', label=True, align='left', size=23)


def control(d, aegis):
    color = PURPLE if aegis else BLUE
    d.group('router', 'AEGIS ROUTER' if aegis else 'ROUTER + CONDUCTOR',
            40, 390, 440, 350, color=color, fill='#FAF7FE' if aegis else '#F7FAFE')
    if aegis:
        d.node('routing', 'Rendezvous 路由\nprimary + 兼容 standby\nrequest salt 隔离不同请求',
               20, 65, 400, 115, parent='router', color=PURPLE, size=21)
        d.node('route-state', '执行权与输出状态\nroute version / fence\n恢复编排 / CompleteRequest',
               20, 220, 400, 105, parent='router', color=PURPLE, size=21)
    else:
        d.node('routing', 'Gateway / Request Router\n根据命中、负载与策略\n选择推理实例',
               20, 65, 400, 115, parent='router', color=BLUE, size=21)
        d.node('route-state', 'Conductor · 可选 KV 索引\n消费 Worker / Store KV events\n返回各实例连续 prefix 命中',
               20, 220, 400, 105, parent='router', color=BLUE, size=21)
        d.edge('router-query', 'routing', 'route-state', color=BLUE, dashed=True,
               exit=(.5, 1), entry=(.5, 0), both=True, width=2)
    d.group('master', 'MOONCAKE STORE MASTER  ·  元数据与资源控制，不承载 KV bytes',
            650, 390, 1110, 350, color=BLUE, size=25)
    if aegis:
        d.node('master-base', '保留原生 Master：对象目录 / 放置 / ReplicaInfo / 租约 / RPC',
               20, 60, 1070, 60, parent='master', color=BLUE, fill='#EAF2FC', size=22)
        d.group('aegis-controller', '新增 AegisController  ·  native C++ / 内部 mutex 串行元数据',
                20, 140, 1070, 190, color=PURPLE, fill='#F4EEFC', parent='master', size=22)
        texts = [('policy', 'Alg. 2 · SlackLandlord\n本层 harm / credit / rent\nsuffix victims + 独立准入'),
                 ('directory', '请求保护目录 / 恢复队列\nrequest · route · tier · ordinal\nPENDING / COMMITTED / ABORTED'),
                 ('aimd', 'Alg. 3 · HBMQuotaAIMD\n压力下降 / 稳定后增加 α\n只调节 Peer-HBM 配额')]
        for i, (key, text) in enumerate(texts):
            d.node(key, text, 20+i*350, 65, 330, 105, parent='aegis-controller',
                   color=PURPLE, size=20)
        d.edge('route-registration', 'routing', 'master', color=PURPLE, dashed=True,
               exit=(1, .5), entry=(0, .35), width=2)
        d.node('route-registration-label', '注册请求\nroute + Slack', 480, 430, 165, 64,
               label=True, color=PURPLE, size=20)
    else:
        data = [('placement', '① 放置与分配', 'PutStart：key / size\n按容量 / 副本数 / 策略\n选择 segment 与 offset'),
                ('directory', '② 对象元数据', 'key → replica descriptors\nsegment / offset / length\nPROCESSING → COMPLETE'),
                ('lifecycle', '③ 生命周期', '只读完整对象 / 读租约\n近似 LRU / soft & hard pin\n压力淘汰 / 删除 / 节点状态')]
        for i, (key, title, text) in enumerate(data):
            d.group(key, title, 20+i*370, 70, 330, 245, parent='master', size=23)
            d.node(key+'-body', text, 12, 80, 306, 130, parent=key, label=True, size=21)
        d.edge('store-events', 'master', 'route-state', color=BLUE, dashed=True,
               exit=(0, .79), entry=(1, .5), width=2)
        d.node('store-events-label', 'KV events\n可选发布', 485, 600, 155, 64,
               label=True, color=BLUE, size=20)
    # Routes occupy the clear band between Application and control groups.
    d.edge('application-request', 'application', 'router', color=color, dashed=True,
           exit=(.128, 1), entry=(.5, 0), points=((260, 345),), width=2)


def data_plane(d, aegis):
    d.node('data-heading', 'DATA PLANE  ·  KV 数据面',
           500, 821, 450, 40, label=True, bold=True, size=23)
    d.group('source', 'SOURCE WORKER  ·  扩展 vLLM' if aegis else 'WORKER A  ·  vLLM 示例',
            40, 880, 440, 470, color=BLUE)
    d.node('source-kv', '真实推理引擎\nScheduler + 主 KV pages\nGPU HBM / K、V tensors',
           20, 70, 400, 130, parent='source', color=BLUE, fill='#EAF2FC', size=23)
    connector = ('AegisKVConnector + gate\n4096 prompt / 256 decode\n共享 ordinal；两层独立准入\nSource copy → 分层 ACK' if aegis else
                 'MooncakeStoreConnector\nblock hash / 保存与加载决定\nStore Client + TransferEngine')
    d.node('source-connector', connector, 20, 270, 400, 130, parent='source',
           color=PURPLE if aegis else BLUE, fill='#F4EEFC' if aegis else '#FFFFFF', size=21)
    d.node('source-caption', '完成 forward 后\n才可保护其 KV' if aegis else '主 KV 所有权\n属于推理框架',
           20, 407, 230, 60, parent='source', label=True, size=19, color=GRAY)
    d.edge('source-publish', 'source-kv', 'source-connector', color=ORANGE,
           exit=(.5, 1), entry=(.5, 0))

    d.group('peer', '备用 WORKER  ·  route-bound target' if aegis else 'WORKER B  ·  共享缓存的使用者',
            650, 880, 440, 470, color=PURPLE if aegis else BLUE,
            fill='#FAF7FE' if aegis else '#F7FAFE', size=23)
    d.node('peer-kv', '新增 Peer-HBM 保护副本\n位于绑定的备用 GPU\nCOMMITTED 才能恢复' if aegis else
           '真实推理引擎\nScheduler + 主 KV pages\n命中共享 prefix 可少做重算',
           20, 70, 400, 130, parent='peer', color=PURPLE if aegis else BLUE,
           fill='#F4EEFC' if aegis else '#EAF2FC', size=22)
    d.node('peer-primary', '恢复后独立的主 KV slots\n真实 HBM → HBM copy\n继续 vLLM forward / replay' if aegis else
           'MooncakeStoreConnector\n查询完整副本 + 持有读租约\nTE 加载到已分配 GPU buffers',
           20, 270, 400, 130, parent='peer', color=BLUE, size=21)
    d.node('peer-caption', '备份与主 KV 同时占容量；不是零拷贝改名' if aegis else '此处展示共享 Store 的读取路径',
           15, 413, 410, 44, parent='peer', label=True, size=19, color=GRAY)
    if aegis:
        d.edge('hbm-protect', 'source-kv', 'peer-kv', color=ORANGE, width=4)
        d.node('hbm-protect-label', '① 独立 HBM copy', 485, 948, 160, 67,
               label=True, color=ORANGE, size=21)
        d.edge('hbm-load', 'peer-kv', 'peer-primary', color=GREEN,
               exit=(.5, 1), entry=(.5, 0), width=4)
        d.node('hbm-load-label', '恢复加载', 885, 1090, 170, 45, label=True, size=20, color=GREEN)
    else:
        d.edge('read-into-primary', 'peer-primary', 'peer-kv', color=GREEN,
               exit=(.5, 0), entry=(.5, 1), width=4)

    d.group('store', 'MOONCAKE STORE  ·  共享 DRAM', 1260, 880, 500, 470, color=BLUE)
    d.node('store-te', 'Store-side Client + TransferEngine\n注册内存 / 收发实际 bytes',
           20, 70, 460, 90, parent='store', color=BLUE, size=22)
    for i, name in enumerate(('Store Node A', 'Store Node B')):
        d.node('segment'+str(i), name+'\nDRAM segment\nbase + offset',
               20+i*240, 205, 220, 140, parent='store', color=BLUE,
               fill='#EAF2FC', size=21, shape='cylinder3')
    d.node('store-caption', '承载请求私有的 DRAM 保护对象\n与 Peer-HBM 独立提交 / 独立释放' if aegis else
           '对象可跨请求、跨实例复用\nMaster 保存目录；这些节点保存 bytes',
           20, 370, 460, 80, parent='store', label=True, size=21, color=GRAY)
    for i in range(2):
        d.edge('store-segment'+str(i), 'store-te', 'segment'+str(i), color=BLUE,
               exit=(.24 if i == 0 else .76, 1), entry=(.5, 0), width=2)

    # Metadata and routing terminate on container borders, leaving labels clear.
    d.edge('route-to-source', 'router', 'source', color=PURPLE if aegis else BLUE,
           dashed=True, exit=(.30, 1), entry=(.30, 0), width=2)
    d.node('route-source-label', '请求路由', 55, 752, 170, 44, label=True,
           color=PURPLE if aegis else BLUE, size=20)
    d.edge('worker-master-rpc', 'source', 'master', color=PURPLE if aegis else BLUE,
           dashed=True, exit=(.85, 0), entry=(.16, 1),
           points=((414, 795), (828, 795)), both=True, width=2)
    d.node('worker-master-label', 'Admit / CompleteCopy' if aegis else 'PutStart / query / PutEnd',
           438, 753, 360, 40, label=True, color=PURPLE if aegis else BLUE, size=20)
    d.edge('register-store', 'store', 'master', color=BLUE, dashed=True,
           exit=(.70, 0), entry=(.865, 1), both=True, width=2)
    d.node('register-store-label', 'MountSegment\n放置 / 目录', 1425, 752, 215, 65,
           label=True, color=BLUE, size=20)
    if aegis:
        d.edge('aimd-quota', 'master', 'peer', color=PURPLE, dashed=True,
               exit=(.38, 1), entry=(.80, 0), points=((1072, 785), (1002, 785)), both=True, width=2)
        d.node('aimd-label', 'αM 配额\n压力反馈', 1110, 750, 250, 64,
               label=True, color=PURPLE, size=20)

    # The Source-to-DRAM path goes below the Peer, never through Peer-HBM.
    d.edge('direct-dram-write', 'source-connector', 'store-te', color=ORANGE,
           exit=(.75, 1), entry=(1, .5),
           points=((360, 1400), (1790, 1400), (1790, 995)), width=4)
    d.node('dram-write-label', '② 独立 DRAM PUT：来自 Source buffers，不经过 Peer-HBM' if aegis else
           '实际 WRITE：Source GPU buffers → Master 分配的 Store segment / offset',
           410, 1355, 1130, 43, label=True, color=ORANGE, size=21)
    d.edge('store-read', 'store-te', 'peer-primary', color=GREEN,
           exit=(0, .70), entry=(1, .5), points=((1240, 1013), (1240, 1215)), width=4)
    d.node('store-read-label', '③ DRAM\n加载缺失 keys' if aegis else 'GET / READ\n共享 prefix',
           1100, 1110, 130, 85, label=True, color=GREEN, size=20)


def lifecycle(d, aegis):
    d.node('lifecycle-heading', '故障恢复  ·  只有 COMMITTED、连续且版本兼容的 prefix 可用' if aegis else
           '一次 KV 写入，以及后续请求如何复用它',
           40, 1460, 1720, 45, label=True, bold=True, size=25)
    if aegis:
        cards = ['故障 fencing\n冻结旧 route 输出', '激活绑定 target\n按剩余 Slack 排序',
                 '预留独立主 KV\n先 HBM，再 DRAM', '重算缺失 suffix\nsilent replay 输出位置',
                 '恢复输出 / 请求结束\ndrain 后清理保护']
    else:
        cards = ['引擎决定缓存\nblock key + KV buffers', 'PutStart 分配空间\n返回 replica descriptors',
                 'TE 写入 bytes\n不经过 Store Master', 'PutEnd 发布可读\n副本成为 COMPLETE',
                 '后续 Get / exists\n租约保护下读取复用']
    for i, text in enumerate(cards):
        d.node('step'+str(i), text, 40+i*350, 1525, 320, 100,
               color=GREEN if aegis else BLUE, fill='#EFF9F5' if aegis else '#F0F6FD', size=21)
    for i in range(4):
        d.edge('step-edge'+str(i), 'step'+str(i), 'step'+str(i+1),
               color=GREEN if aegis else BLUE, width=2)
    foot = ('实现图：AegisKV on Mooncake / vLLM。两层分别 ACK；PENDING 不可恢复。\n'
            '4090 pilot 的跨 GPU 保护经 host-staged TCP；图中逻辑 copy 不代表已验证直接 NVLink / RDMA。' if aegis else
            '以标准 vLLM + Mooncake Store 路径为例。TE 也支持其他后端；图中未展开可选 SSD offload / HA。\n'
            'SGLang 的本地 HostCache 与远端 Store DRAM 是不同层；底层能力不自动包含 workflow-Slack 保护。')
    d.node('footnote', foot, 40, 1658, 1720, 70, label=True, color=GRAY, size=20)


def main():
    for aegis, name, title, subtitle in [
        (False, 'mooncake-kv-management', '01  Mooncake 如何管理与共享 KV',
         '原生架构：引擎拥有主 KV，Master 管理对象目录，Transfer Engine 搬运 bytes'),
        (True, 'mooncake-aegiskv-implementation', '02  增加 AegisKV 后的 Mooncake 架构',
         '实现增量：Application Slack + Router 版本与备用绑定 + native Controller + Worker 保护 / 恢复')]:
        d = Diagram(name, title, subtitle, aegis=aegis)
        application(d, aegis)
        control(d, aegis)
        data_plane(d, aegis)
        lifecycle(d, aegis)
        d.save()


if __name__ == '__main__':
    main()
