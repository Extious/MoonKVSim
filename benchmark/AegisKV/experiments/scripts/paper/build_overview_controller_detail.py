#!/usr/bin/env python3
"""Three ownership layers with the controller's models, ledgers and guards."""
from pathlib import Path
import build_storage_design as base
from build_storage_design import Diagram, LINE, BLUE, PALE, ORANGE, SAND, GREEN, MINT, WHITE
OUT=Path(__file__).resolve().parents[3]/'exports/design-evidence-review-20260921'
base.OUT=OUT


def main():
    d=Diagram('system-overview',600,654)
    def n(*args,**kw):
        kw.setdefault('font',26)
        return d.node(*args,**kw)
    e=d.edge
    def box(key,x,y,w,h,fill,stroke=LINE,parent='1'):
        return n(key,'',x,y,w,h,fill=fill,stroke=stroke,parent=parent,
                 extra='rounded=1;arcSize=8;container=1;collapsible=0;')
    box('application',8,8,584,78,'#F1F4F6')
    n('app-title','Application',20,13,180,32,bold=True,align='left',parent='application')
    n('workflow','Agent workflow',20,48,204,31,align='left',parent='application')
    for key,label,x,y in [('a','A',243,32),('b','B',365,13),('c','C',365,53),('d','D',507,32)]:
        n(key,label,x,y,48,29,fill=WHITE,stroke=LINE,parent='application',extra='rounded=1;arcSize=20;')
    for src,dst in [('a','b'),('a','c'),('b','d'),('c','d')]:
        e(src+dst,src,dst,start=(1,.5),end=(0,.5),color=LINE)

    box('controller',8,104,584,292,'#EAF1F6')
    n('controller-title','Controller',20,108,187,33,bold=True,align='left',parent='controller')
    box('tracker',20,147,360,68,MINT,GREEN,'controller')
    n('tracker-title','Workflow Tracker',29,147,342,31,bold=True,parent='tracker')
    n('gbdt','GBDT',37,179,110,31,parent='tracker')
    n('slack','CPM / Slack',202,179,166,31,parent='tracker')
    e('predict-slack','gbdt','slack',start=(1,.5),end=(0,.5),dashed=True)

    box('master',20,242,360,140,PALE,BLUE,'controller')
    n('master-title','KV Master',28,245,344,31,bold=True,parent='master')
    box('cost',31,282,151,58,WHITE,BLUE,'master')
    n('cost-title','WCT cost',34,282,145,29,parent='cost')
    n('cost-detail','Layer I/O',34,309,145,29,parent='cost')
    box('rental',214,282,154,58,WHITE,BLUE,'master')
    n('rent-title','Rent',218,282,145,29,parent='rental')
    n('dram-ledger','D',218,312,26,25,parent='rental')
    n('ssd-ledger','S',292,312,26,25,parent='rental')
    for prefix,x,color,fill in [('D',248,BLUE,PALE),('S',322,ORANGE,SAND)]:
        for j in range(2):
            n(f'credit-{prefix}-{j}','',x+19*j,316,15,16,fill=fill,stroke=color,parent='rental')
    n('joint-check','Joint DAG check / reserve',31,350,337,28,fill=WHITE,stroke=BLUE,parent='master')
    e('rank','cost','rental',start=(1,.5),end=(0,.5),dashed=True)
    e('rent-plan','rental','joint-check',start=(.5,1),end=(.772,0),dashed=True)
    e('slack-value','tracker','master',start=(.24,1),end=(.24,0),dashed=True)
    n('slack-label','Slack',134,214,92,27,parent='controller')

    box('router',408,147,172,132,'#DDE5EF',BLUE,'controller')
    n('router-title','Router',412,149,164,32,bold=True,parent='router')
    n('router-locality','Load / KV',412,184,164,31,parent='router')
    n('router-failure','Fence / retry',412,219,164,31,parent='router')
    for j,h in enumerate([8,17,12,7]):
        n(f'load-{j}','',442+j*22,268-h,13,h,fill='#7497B8',parent='router')
    n('directory-back','',411,293,169,88,fill='#D3DFE8',stroke=LINE,parent='controller')
    n('directory','',408,297,172,88,fill=WHITE,stroke=LINE,parent='controller')
    for key,label,y in [('directory-title','Directory',298),('manifests','Manifests',327),('log-leases','Log / leases',356)]:
        n(key,label,411,y,166,28,bold=key=='directory-title',parent='directory')
    e('versions','master','directory',start=(1,.64),end=(0,.39),dashed=True,both=True)
    e('lookup','directory','router',start=(.5,0),end=(.5,1),dashed=True)
    e('workflow-metadata','application','tracker',start=(.375,1),end=(.5,0),
      points=[(227,141),(200,141)],dashed=True)
    e('request','application','router',start=(.832,1),end=(.5,0))

    box('engine',8,414,584,232,'#F4F5F1')
    n('engine-title','Engine',20,416,117,31,bold=True,align='left',parent='engine')
    for i,x in enumerate([20,316]):
        key=f'worker{i}';box(key,x,453,264,88,WHITE,parent='engine')
        n(key+'-title',f'DP {i}',x+8,454,91,30,bold=True,align='left',parent=key)
        n(f'gpu{i}','GPU',x+17,496,77,33,fill='#D9E3E9',stroke=LINE,bold=True,parent=key,
          extra='rounded=1;arcSize=8;')
        for j in range(4):
            for side,yy in [('top',492),('bottom',529)]:
                n(f'pin-{i}-{side}-{j}','',x+24+j*17,yy,6,4,fill=LINE,parent=key)
        for j in range(3):
            for side,xx in [('left',x+13),('right',x+94)]:
                n(f'pin-{i}-{side}-{j}','',xx,501+j*10,4,4,fill=LINE,parent=key)
        n(f'hbm{i}','',x+128,482,124,53,fill=MINT,stroke=GREEN,parent=key)
        n(f'hbm-title{i}','HBM',x+133,482,114,29,bold=True,parent=key)
        for row in range(2):
            for col in range(4):
                hot=col==(i+row)%3
                n(f'kv-{i}-{row}-{col}','',x+138+27*col,513+11*row,20,7,
                  fill=SAND if col==3 else WHITE,stroke=BLUE if hot else '#92B5A8',parent=key,
                  extra='strokeWidth=2.3;' if hot else '')
        e(f'gpu-hbm-{i}',f'gpu{i}',f'hbm{i}',start=(1,.5),end=(0,.57),both=True,color=BLUE)
    e('dispatch','router','worker0',start=(0,.43),end=(.5,0),points=[(395,203.76),(395,441),(152,441)])
    e('retry','router','worker1',start=(1,.43),end=(.5,0),
      points=[(589,203.76),(589,446),(448,446)],dashed=True,color='#AC4251')
    n('run-label','Run',210,415,72,29,parent='engine')
    n('retry-label','Retry',453,415,82,29,parent='engine')
    e('accepted-plan','master','engine',start=(.70,1),end=(.455,0),dashed=True)
    e('feedback','worker0','tracker',start=(0,.45),end=(0,.5),points=[(3,492.6),(3,181)],dashed=True)
    n('fabric','',42,559,516,6,fill='#ABC5D6',stroke=BLUE,parent='engine')
    for i,xx in enumerate([210,506]):
        e(f'worker-io-{i}',f'hbm{i}','fabric',start=(.5,1),end=((xx-42)/516,0),both=True,color=BLUE)
    for j in range(3):
        n(f'dram-bank-{j}','',52+5*j,588+5*j,177,12,fill=PALE,stroke=BLUE,parent='engine')
        for k in range(6):
            n(f'dram-chip-{j}-{k}','',59+5*j+27*k,591+5*j,18,6,fill='#749DB6',parent='engine')
    n('dram-label','DRAM pool',31,614,217,29,bold=True,parent='engine')
    for j in range(3):
        n(f'ssd-{j}','',429-5*j,584+5*j,72,20,fill=SAND if j==2 else WHITE,
          stroke=ORANGE,parent='engine',extra='rounded=1;arcSize=15;')
    n('ssd-led','',426,606,8,4,fill=ORANGE,parent='engine')
    n('ssd-label','SSD / storage',346,614,236,29,bold=True,parent='engine')
    e('dram-io','fabric','dram-bank-0',start=((140.5-42)/516,1),end=(.5,0),both=True,color=BLUE)
    e('ssd-io','fabric','ssd-0',start=((465-42)/516,1),end=(.5,0),both=True,color=BLUE)
    e('tier-move','dram-bank-2','ssd-2',start=(1,.5),end=(0,.5),both=True,color=BLUE)
    print(d.save())


if __name__=='__main__':main()
