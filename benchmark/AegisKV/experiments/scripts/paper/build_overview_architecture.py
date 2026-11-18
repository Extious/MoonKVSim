#!/usr/bin/env python3
"""Resource-oriented AegisKV overview, informed by LiveUpdate/RACER figures.

Independent native Draw.io drawing, not a tracing of the reference artwork.
"""
from pathlib import Path
import build_storage_design as base
from build_storage_design import Diagram, INK, LINE, BLUE, PALE, ORANGE, SAND, GREEN, MINT, WHITE

OUT=Path(__file__).resolve().parents[3]/'exports/system-overview-architecture-20260921'
base.OUT=OUT
RED='#AC4251'


def main():
    d=Diagram('system-overview',500,485)
    def n(*args,**kwargs):
        kwargs.setdefault('font',22)
        return d.node(*args,**kwargs)
    e=d.edge
    def region(key,x,y,w,h,fill,stroke=LINE,parent="1"):
        return n(key,'',x,y,w,h,fill=fill,stroke=stroke,parent=parent,
                 extra='rounded=1;arcSize=10;container=1;collapsible=0;')
    # The workload is an application object. The diagram's main area is deployment.
    region('workflow',8,8,474,56,'#F1F6F8')
    n('workflow-label','Workflows',16,19,181,31,bold=True,parent='workflow')
    for key,x,y in [('a',213,25),('b',304,13),('c',304,40),('d',425,25)]:
        n(key,'',x,y,35,19,fill=WHITE,stroke=LINE,parent='workflow',extra='rounded=1;arcSize=15;')
    for key,s,t in [('ab','a','b'),('ac','a','c'),('bd','b','d'),('cd','c','d')]:
        e(key,s,t,start=(1,.5),end=(0,.5),color=LINE)

    # A separate service boundary is deliberately outside the worker failure domains.
    region('services',8,90,161,281,'#EDF2F6')
    n('services-title','Control',13,96,151,30,bold=True,parent='services')
    region('tracker',20,136,137,57,MINT,GREEN,parent='services')
    n('tracker-title','Tracker',23,139,131,25,bold=True,parent='tracker')
    n('tracker-rule','GBDT/CPM',23,164,131,26,parent='tracker')
    region('master',20,229,137,56,PALE,BLUE,parent='services')
    n('master-title','KV Master',22,230,133,26,bold=True,parent='master')
    n('master-rule','Value / rent',22,256,133,26,parent='master')
    for j in range(2):
        n(f'metadata-back-{j}','',25-3*j,304+3*j,134,53,fill='#DEE5EA',stroke=LINE,parent='services')
    n('directory','',20,310,137,53,fill=WHITE,stroke=LINE,parent='services')
    n('directory-title','Directory',22,313,133,24,parent='services')
    n('log-title','Token log',22,337,133,24,parent='services')
    e('progress','workflow','tracker',start=(0,.5),end=(0,.5),points=[(2,36),(2,164.5)],dashed=True)
    e('slack','tracker','master',dashed=True)
    n('slack-label','Slack',97,199,63,25,fill='#EDF2F6',parent='services')
    e('coverage','master','directory',dashed=True)

    # Global dispatch, visibly distinct from the node-local GPU/HBM resources.
    region('router',207,88,275,58,'#E7EFF6',BLUE)
    n('router-title','Router',211,91,267,26,bold=True,parent='router')
    n('router-states','KV map',212,118,95,24,parent='router')
    for i in range(3):n(f'cache-map-{i}','',303+i*15,124,10,13,fill=PALE,stroke=BLUE,parent='router')
    n('load-label','Load',350,118,58,24,parent='router')
    for i,height in enumerate([9,19,14]):
        n(f'load-{i}','',414+i*18,139-height,12,height,fill='#7497B8',stroke='none',parent='router')
    e('request','workflow','router',start=(.71,1),end=(.5,0))

    # Two equally capable compute replicas: chip, nested HBM, and real KV slots.
    for i,x in enumerate([205,354]):
        key=f'worker{i}';region(key,x,190,128,144,'#F2F3F0')
        n(key+'-title',f'DP {i}',x+9,194,110,26,bold=True,parent=key)
        chip=f'gpu{i}'
        n(chip,'GPU',x+33,229,63,34,fill='#D9E3E9',stroke=LINE,bold=True,parent=key,
          extra='rounded=1;arcSize=8;')
        for j in range(4):
            for side in ['top','bottom']:
                n(f'pin-{i}-{side}-{j}','',x+39+j*13,225 if side=='top' else 263,5,4,fill=LINE,parent=key)
        for j in range(3):
            for side in ['left','right']:
                n(f'pin-{i}-{side}-{j}','',x+29 if side=='left' else x+96,234+j*10,4,4,fill=LINE,parent=key)
        n(f'hbm{i}','',x+10,276,108,50,fill=MINT,stroke=GREEN,parent=key)
        n(f'hbm-title{i}','HBM',x+16,277,96,23,bold=True,parent=key)
        for row in range(2):
            for col in range(4):
                hot=col==(i+row)%3
                n(f'kv-{i}-{row}-{col}','',x+17+23*col,303+12*row,17,8,
                  fill=SAND if col==3 else WHITE,stroke=BLUE if hot else '#92B5A8',parent=key,
                  extra='strokeWidth=2.3;' if hot else '')
    # Example dispatch/retry paths, rather than permanent primary/standby roles.
    e('dispatch','router','worker0',start=(.22,1),end=(.5,0),points=[(267.5,170),(269,170)])
    e('retry','router','worker1',start=(.77,1),end=(.5,0),dashed=True,color=RED)
    n('run-label','Run',207,157,55,24)
    n('retry-label','Retry',421,156,66,25)

    # The fabric has actual resource endpoints; metadata uses a separate dashed lane.
    n('fabric','',189,355,293,7,fill='#ABC5D6',stroke=BLUE)
    n('fabric-label','KV fabric',289,367,126,25,fill=WHITE)
    for i,x in enumerate([269,418]):
        e(f'worker-io-{i}',f'hbm{i}','fabric',start=(.5,1),end=((x-189)/293,0),both=True,color=BLUE)
    # Directory replies and placement control run outside the worker boards.
    e('directory-router','directory','router',start=(1,.35),end=(0,.5),
      points=[(184,327.55),(184,117)],dashed=True)
    e('place','master','fabric',start=(1,.45),end=(0,.5),
      points=[(176,254.2),(176,358.5)],dashed=True,both=True)
    e('worker-state','worker1','router',start=(1,.55),end=(1,.55),
      points=[(491,269.2),(491,119.9)],dashed=True)

    # Separate backing resources survive the protected compute-worker failure.
    region('store',8,400,474,78,'#F7F8F5')
    n('store-title','Shared KV store',143,402,205,25,bold=True,parent='store')
    for j in range(3):
        n(f'dram-bank-{j}','',24+6*j,428+6*j,155,12,fill=PALE,stroke=BLUE,parent='store')
        for k in range(6):
            n(f'dram-cell-{j}-{k}','',30+6*j+24*k,431+6*j,16,6,fill='#749DB6',parent='store')
    n('dram-label','DRAM pool',21,454,181,23,bold=True,parent='store')
    for j in range(3):
        n(f'ssd-{j}','',337-5*j,426+5*j,62,24,fill=SAND if j==2 else WHITE,stroke=ORANGE,parent='store',
          extra='rounded=1;arcSize=15;')
    n('ssd-led','',333,451,7,4,fill=ORANGE,parent='store')
    n('ssd-label','SSD / storage',284,454,187,23,bold=True,parent='store')
    e('dram-io','fabric','dram-bank-0',start=(.14,1),end=(.5,0),
      points=[(230.02,389),(101.5,389)],both=True,color=BLUE)
    e('ssd-io','fabric','ssd-0',start=(.87,1),end=(.5,0),
      points=[(443.91,395),(368,395)],both=True,color=BLUE)
    e('tier-move','dram-bank-2','ssd-2',start=(1,.5),end=(0,.5),both=True,color=BLUE)
    print(d.save())


if __name__=='__main__':main()
