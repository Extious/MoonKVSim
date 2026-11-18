"""Native shapes for the Agent sublease revision; no rasterized formulas."""


def draw_rental_flow(Page):
    p = Page('flow', '2 · SlackLandlord：单块准入、续租与收租', 4330, width=2600)
    p.title('算法二  ·  SlackLandlord：Agent 续租与单块备份',
            '新请求登记续租资格；一次只准入一个完整 chunk x；已有共享副本只更新引用。')
    sy = p.panel('symbols', '符号说明', 60, 205, 2480, 485)
    left = [
        ('objects', r'\(x/y\)：候选块 / 可释放尾块；\(a,s_a\)：Agent 及其本轮 Slack'),
        ('bytes', r'\(b_x,b_y\)：物理 bytes；\(f\)：可用 bytes；\(Q\)：可释放尾块'),
        ('gain', r'\(W_{a,x},P_{a,x}\)：Agent a 的 WCT 收益份额、单位字节收益'),
        ('shares', r'\(G_x\)：块的联合 WCT 收益；\(c_{a,x}\)：Agent a 的剩余信用'),
        ('credit', r'\(\mathrm{Credit}_x\)：块的总剩余信用；\(L,H_x\)：累计租金、租值键'),
        ('loss', r'\(\delta\)：本次单位字节租金；\(Y,D_Y\)：试删块及累计 WCT 损失'),
    ]
    right = [
        ('prefix', r'\(k,k_a,n_a\)：连续备份长度、Agent 前缀长度、已生成块数'),
        ('costs', r'\(t_a^{\rm reuse}(j),t_a^{\rm recompute}(j,n_a)\)：加载前 j 块、重算其余块'),
        ('time', r'\(T_a(k),\Delta T_{a,x}\)：恢复全部已生成 KV 的耗时、x 节省的耗时'),
        ('dag', r'\(w,u\to v,d_v,t_v\)：工作流、前驱、节点正常耗时、完成时间'),
        ('vector', r'\(T_v,\mathbf T\)：节点恢复耗时、全部节点的恢复耗时向量'),
        ('order', r'\(a_i,\mathbf T^{(i)}\)：第 i 个引用 Agent、前 i 个 Agent 使用 x 的向量'),
    ]
    for col, x in ((left,85),(right,1335)):
        for row,(key,value) in enumerate(col):
            p.box('symbols-'+key,value,x,295+61*row,1170,55,text=True,parent=sy,size=23,align='left')

    p.box('candidate','① 取首个尚未备份的完整 KV chunk x',610,770,1040,100,size=29)
    p.box('prefix','x 的连续前缀\n已提交？',795,940,670,145,decision=True,size=29)
    p.box('wait-prefix','前缀未备份，后续也不再备份\n（遵循 Prefix Cache）',80,950,430,125,size=26)
    p.box('references','读取 Agent 引用、当前轮号、Slack 与恢复代价',610,1160,1040,90,size=27)
    p.box('gain','Agent 在备份 k 个 KV chunk 时的恢复时间\n'+
          r'\(T_a(k)=\min_{0\le j\le k}\{t_a^{\rm reuse}(j)+t_a^{\rm recompute}(j,n_a)\}\)',
          610,1320,1040,145,size=28)
    p.box('gain-single','备份第 k+1 个 KV chunk 对 WCT 带来的收益\n'+
          r'\(\Delta T_{a,x}=T_a(k)-T_a(k+1)\)'+'\n'+
          r'\(W_{a,x}=\min\{\Delta T_{a,x},\max(T_a(k)-s_a,0)\}\)'+'\n同一工作流内多 Agent 引用时，改用左侧分账公式',
          610,1530,1040,195,size=26)
    p.box('gain-density','计算 Agent a 对 chunk x 的收益密度\n'+r'\(P_{a,x}=W_{a,x}/b_x\)',
          610,1777,1040,105,size=28)
    p.box('init','④ 试算备份 x，保护必要前缀（尚未分配）\n'+
          r'\(Y\leftarrow\varnothing,\quad D_Y\leftarrow0,\quad f\leftarrow\text{Pool 可用字节}\)',
          610,2130,1040,125,size=27)
    p.box('fits','可用空间足够？\n'+r'\(f\ge b_x\)',795,2360,670,160,decision=True,size=29)
    p.box('accept','⑤ 当前净收益为正？\n'+r'\(G_x>D_Y\)',795,2660,670,155,decision=True,size=29)
    p.box('validate','⑥ 重验输入版本、容量、固定读取与分配代次',610,2920,1040,105,size=27)
    p.box('release','⑦ 确认回收计划与扣租；释放 Y\n等待对应的物理释放 ACK',610,3100,1040,120,size=28)
    p.box('copy','⑧ 为 x 分配空间并复制',610,3300,1040,100,size=29)
    p.box('ack','全部分片\n确认成功？',810,3490,640,145,decision=True,size=28)
    p.box('copy-failure','失败：清理本次分配并重规划\n未齐：等待其余分片',1830,4070,710,110,size=25)
    p.box('commit','⑨ 发布 COMMITTED，按当前前缀授信\n'+
          r'\(c_{a,x}\leftarrow b_xP_{a,x}=W_{a,x}\)'+'\n'+r'\(\mathrm{Credit}_x=\sum_a c_{a,x}\)'+'；记录各 Agent 的已兑现轮号',
          610,3770,1040,165,size=28)

    # A side loop supports the single-column admission path.
    p.box('eligible-note','Q：无后继、未固定的可释放尾块\n内部前缀保存余额，不参加本轮收租',65,2230,465,100,text=True,size=23)
    p.box('has-tail','有可释放尾块？\n'+r'\(Q\ne\varnothing\)',100,2380,390,155,decision=True,size=27)
    p.box('refresh-tail','检查 Q 中每个块的版本\n按右侧公式兑现续租 / 限额\n'+r'\(H_y=L+\mathrm{Credit}_y/b_y\)',
          65,2630,465,160,size=25)
    p.box('collect','推进累计租金\n'+r'\(\delta=\min_{y\in Q}(H_y-L)\)'+'\n'+r'\(L\leftarrow L+\delta\)',
          65,2880,465,145,size=27)
    p.box('debit','对 Q 中每块收一份物理租金\n'+
          r'\(\mathrm{Credit}_y\leftarrow\mathrm{Credit}_y-b_y\delta\)'+'\n各 Agent 按右侧比例分摊',
          65,3115,465,145,size=25)
    p.box('select-tail','选择一个信用归零的尾块 y\n'+r'\(\mathrm{Credit}_y=0\)',65,3330,465,110,size=27)
    p.box('trim','仅试删 y，并累加本次条件恢复损失\n'+
          r'\(Y\leftarrow Y\cup\{y\},\quad D_Y\leftarrow D_Y+G_y\)'+'\n'+r'\(f\leftarrow f+b_y\)',
          65,3510,465,155,size=23)
    p.box('bypass','BYPASS：丢弃临时计划\n保留真实备份、余额与 L',65,3885,465,115,size=26)

    p.edge('candidate','prefix')
    p.edge('prefix','wait-prefix',out=(0,.5),into=(1,.5),text='否',at=(565,966,75,45))
    p.edge('prefix','references',text='是',at=(1145,1100,75,45))
    for a,b in [('references','gain'),('gain','gain-single'),('gain-single','gain-density'),
                ('gain-density','init'),('init','fits')]:p.edge(a,b)
    p.edge('fits','has-tail',out=(0,.5),into=(1,.5),text='否',at=(595,2410,75,45))
    p.edge('has-tail','refresh-tail',text='是',at=(315,2565,70,45))
    for a,b in [('refresh-tail','collect'),('collect','debit'),('debit','select-tail'),('select-tail','trim')]:p.edge(a,b)
    p.edge('trim','fits',out=(1,.5),into=(.3,1),points=((570,3587),(570,2570),(996,2570)))
    p.edge('has-tail','bypass',out=(0,.5),into=(0,.5),points=((30,2457),(30,3942)),text='否',at=(30,3720,55,45))
    p.edge('fits','accept',out=(1,.5),into=(1,.5),points=((1730,2440),(1730,2737)),text='是',at=(1655,2560,75,45))
    p.edge('accept','bypass',out=(0,.5),into=(1,.5),points=((550,2737),(550,3942)),text='否',at=(640,2700,75,45))
    p.edge('accept','validate',text='是',at=(1145,2845,75,45))
    p.edge('validate','bypass',out=(0,.5),into=(1,.5),points=((550,2972),(550,3942)),text='失效',at=(540,3030,85,45),dashed=True)
    for a,b in [('validate','release'),('release','copy'),('copy','ack')]:p.edge(a,b)
    p.edge('ack','commit',text='是',at=(1145,3680,75,45))
    p.edge('ack','copy-failure',out=(1,.5),into=(0,.5),points=((1745,3562),(1745,4125)),
           text='失败 / 未齐',at=(1525,3575,195,50))

    # Equations are editable shapes, with the decomposition next to the DAG.
    calc=p.panel('dag-formulas','共享收益的分账公式',60,1160,485,1030)
    p.box('dag-recovery','受影响 Agent 节点\n'+r'\(T_v=T_a(k_a)\)'+'\n其余节点 '+r'\(T_v=0\)',
          80,1245,445,140,parent=calc,size=24)
    p.box('dag-finish','按拓扑顺序计算\n'+r'\(t_v=d_v+T_v+\max_{u\to v}t_u\)',
          80,1445,445,115,parent=calc,size=24)
    p.box('dag-wct',r'\(\mathrm{WCT}_w(\mathbf T)=\max_{v\in w}t_v\)',
          80,1620,445,90,parent=calc,size=24)
    p.box('dag-order','同一工作流：按固定 Agent ID 分账\n'+r'\(W_{a_i,x}=\sum_{w\gets x}\big[\)'+'\n'+
          r'\(\mathrm{WCT}_w(\mathbf T^{(i-1)})-\mathrm{WCT}_w(\mathbf T^{(i)})\big]\)',
          80,1770,445,185,parent=calc,size=22)
    p.box('dag-total','只汇总一次，供准入比较\n'+r'\(G_x=\sum_a W_{a,x}=b_x\sum_aP_{a,x}\)'+'\n'+r'\(w\gets x\)：工作流引用 x；\(\max\varnothing=0\)',
          80,2015,445,145,parent=calc,size=22)
    for a,b in [('dag-recovery','dag-finish'),('dag-finish','dag-wct'),('dag-wct','dag-order'),('dag-order','dag-total')]:p.edge(a,b)

    ref=p.panel('chunk-record','一个 chunk 的引用信息',1830,770,710,425)
    p.box('user-chunk-card','KV chunk P2  ·  候选 x\nAgent1: Slack1 = 8 ms\nAgent2: Slack2 = 3 ms\nSize: 4096 tokens\nHBM/DRAM: '+r'\(b_x\)'+' bytes',
          1880,860,610,245,parent=ref,size=27)
    p.box('references-note','Slack 从 Agent 表读取；每个引用另存剩余信用。',1850,1120,670,55,text=True,parent=ref,size=23)

    pool=p.panel('pool','Peer HBM Pool · 共享存储与收租边界',1830,1260,710,780)
    p.box('pool-prefixes','连续前缀：P1 → P2(x)\n另一条链：C1 → C2 → C3(y)',1855,1340,660,95,text=True,parent=pool,size=25)
    slots=[('P1','Agent1: 8 ms\nAgent2: 3 ms',1870,1470),
           ('C1','Agent3: 12 ms\n内部块：暂停收租',2200,1470),
           ('C2','Agent3: 12 ms\n内部块：暂停收租',1870,1695),
           ('C3','Agent3: 12 ms\n尾块 y：参与收租',2200,1695)]
    for key,refs,x,y in slots:
        p.box('pool-'+key,key+'\n'+refs+'\nSize: 4096 tokens',x,y,300,190,parent=pool,size=23)
    p.box('pool-note','P1 只占一槽；候选 x 的必要前缀不被试删。\nC3 删除后，C2 带剩余信用进入下一轮竞争。',
          1850,1900,670,85,parent=pool,text=True,size=23)
    p.box('pool-result','若接纳 x：P1 | C1 | C2 | x',1850,1980,670,50,parent=pool,text=True,size=22)

    ledger=p.panel('ledger','子租约：谁续租，谁获得新信用',1830,2110,710,1010)
    p.box('credit-total',r'\(\mathrm{Credit}_x=\sum_a c_{a,x}\)',1870,2200,630,90,parent=ledger,size=29)
    p.box('renew-agent','仅 Agent a 有未兑现的新请求\n'+r'\(c_{a,x}\leftarrow b_xP_{a,x}=W_{a,x}\)'+'\n兑现后记录该轮号',
          1870,2350,630,150,parent=ledger,size=26)
    p.box('cap-others','其余 Agent / 普通刷新：只保留或减额\n'+r'\(c_{b,x}\leftarrow\min(c_{b,x},b_xP_{b,x})\)',
          1870,2560,630,115,parent=ledger,size=26)
    p.box('lease-key','用剩余信用更新键\n'+r'\(H_x=L+\mathrm{Credit}_x/b_x\)',1870,2735,630,115,parent=ledger,size=28)
    for a,b in [('credit-total','renew-agent'),('renew-agent','cap-others'),('cap-others','lease-key')]:p.edge(a,b)
    p.box('rent-split','一份物理租金，按扣租前余额比例分摊\n'+
          r'\(c_{a,y}\leftarrow c_{a,y}\left(1-\frac{b_y\delta}{\mathrm{Credit}_y}\right)\)',
          1870,2895,630,130,parent=ledger,size=25)
    p.box('ledger-note','零信用不做除法；Agent 结束则撤销其份额。\n新请求不能补回其他 Agent 已支付的租金。',
          1850,3035,670,70,parent=ledger,text=True,size=22)

    lazy=p.panel('lazy','Lazy Refresh：登记 → 按需兑现',1830,3200,710,780)
    p.box('round-update','x 已备份，Agent1 发起下一轮请求\nSlack: 8 → 4 ms；版本: 7 → 8',
          1870,3290,630,100,parent=lazy,size=25)
    p.box('mark','只写 Agent1 表；Agent2 仍为 3 ms\nx 的余额、H 与已兑现版本暂不改',
          1870,3445,630,105,parent=lazy,size=25)
    p.box('lazy-when','x 成为可释放尾块，下一次收租前\n已兑现版本 7 ≠ Agent1 当前版本 8',
          1870,3605,630,105,parent=lazy,size=25)
    p.box('lazy-write','按当前恢复前缀重算 '+r'\(W_{1,x},P_{1,x}\)'+'\n仅兑现 Agent1，记录版本 8；再更新 H',
          1870,3765,630,100,parent=lazy,size=25)
    for a,b in [('round-update','mark'),('mark','lazy-when'),('lazy-when','lazy-write')]:p.edge(a,b)
    p.box('lazy-note','每次推进 L 前检查全部参与尾块，不能只看旧堆顶。\n内部块暂停收租，兑现前不会漏付尾块租金。',
          1850,3890,670,75,parent=lazy,text=True,size=22)
    p.box('quota','容量缩小：暂停准入，按尾块规则强制回收。\n固定读取未解除时等待；复制/释放中分配仍计入容量。',
          610,4070,1040,110,size=25)
    p.footer('设计边界：只考虑恢复 WCT；时间单位 ms，容量用 bytes。固定顺序分账不保证对称公平；严格单块准入可能错过组合收益；未声称经典 Landlord 竞争比。',height=80)
