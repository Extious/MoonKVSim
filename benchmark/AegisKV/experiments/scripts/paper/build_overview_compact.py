#!/usr/bin/env python3
"""Compact, near-square native Draw.io overview; schematic values only."""
from pathlib import Path
import build_storage_design as base
from build_storage_design import Diagram, LINE, BLUE, PALE, ORANGE, SAND, GREEN, MINT, WHITE

OUT=Path(__file__).resolve().parents[3]/'exports/system-overview-compact-20260921'
base.OUT=OUT
RED='#AA3C4D'


def main():
    d=Diagram('system-overview',480,480);n,g,e=d.node,d.group,d.edge
    # A shallow application band retains actual fork/join topology.
    g('workflow',8,8,464,59,fill='#F2F6F8')
    n('request','Request\nIDs',18,14,106,46,fill=WHITE,stroke=LINE,parent='workflow')
    for key,label,x,y in [('a0','A0',156,26),('a1','A1',269,12),('a2','A2',269,40),('a3','A3',393,26)]:
        n(key,label,x,y,50,23,fill=WHITE,stroke=LINE,parent='workflow')
    for key,source,target in [('01','a0','a1'),('02','a0','a2'),('13','a1','a3'),('23','a2','a3')]:
        e(key,source,target,start=(1,.5),end=(0,.5),color=LINE)

    # Two aligned columns share space instead of forming a long module stack.
    g('control',8,88,464,174,fill='#F8F9FC')
    g('tracker',18,96,187,88,fill=MINT,stroke=GREEN,parent='control')
    n('tracker-title','1  Tracker',23,100,177,26,bold=True,parent='tracker')
    n('gbdt','GBDT → CPM',23,129,177,25,parent='tracker')
    n('slack-value','Slack: 8 / 0 s',23,156,177,23,parent='tracker')
    g('master',263,96,199,99,fill=PALE,stroke=BLUE,parent='control')
    n('master-title','3  KV Master',268,100,189,26,bold=True,parent='master')
    n('rule','Value → rent',268,129,189,25,parent='master')
    for tier,x,color,fill in [('D',275,BLUE,PALE),('S',371,ORANGE,SAND)]:
        n('tier-'+tier,tier,x,162,22,25,parent='master')
        for j in range(2):
            n(f'candidate-{tier}-{j}','',x+27+23*j,167,18,16,fill=fill,stroke=color,parent='master')
    g('router',18,209,187,48,fill='#E7EEF4',stroke=BLUE,parent='control')
    n('router-title','2  Router',23,210,177,22,bold=True,parent='router')
    n('router-rule','Locality + load',22,232,179,23,parent='router')
    g('directory',263,213,199,44,fill=WHITE,stroke=LINE,parent='control')
    n('directory-title','Directory + log',267,214,191,22,parent='directory')
    n('frontier','M = 128',267,236,191,20,parent='directory')
    e('progress','a2','tracker',start=(.5,1),end=(.5,0),points=[(294,78),(111.5,78)],dashed=True)
    e('request-route','request','router',start=(0,.5),end=(0,.5),points=[(2,37),(2,231)])
    e('slack-master','tracker','master',start=(1,.5),end=(0,.45),dashed=True)
    e('plan-directory','master','directory',dashed=True)
    e('directory-router','directory','router',start=(0,.5),end=(1,.5),dashed=True)

    # Symmetric engines retain their actual block layout without a second HBM title row.
    for i,x in enumerate([18,252]):
        dp=f'dp{i}';g(dp,x,289,210,77,fill='#F7FAFB',stroke=LINE)
        n(dp+'title',f'DP {i} · HBM',x+4,291,202,25,bold=True,parent=dp)
        for row in range(2):
            yy=325+20*row
            n(f'layer-{i}-{row}',f'L{row+1}',x+6,yy-4,32,23,parent=dp)
            for col in range(6):
                selected=col in ((row+i)%4,3)
                n(f'block-{i}-{row}-{col}','',x+43+25*col,yy,19,15,
                  fill=SAND if col==5 else MINT,
                  stroke=BLUE if selected else ('#BA985D' if col==5 else '#ABC4BA'),
                  parent=dp,extra='strokeWidth=2.2;' if selected else '')
    e('dispatch','router','dp0',start=(.5,1),end=(.5,0),points=[(111.5,278),(123,278)],color=BLUE)
    e('retry','router','dp1',start=(.83,1),end=(.5,0),points=[(173.2,276),(357,276)],dashed=True,color=RED)
    n('run','Run',38,264,55,23)
    n('retry-label','Retry',282,263,66,23,fill=WHITE)

    # One execution strip fans out to both shared tiers; storage is not another tall stack.
    g('transfer',18,391,444,27,fill='#EAF0F5',stroke=BLUE)
    n('transfer-title','Engine hooks + KV transfer',22,392,436,25,bold=True,parent='transfer')
    for i,x in enumerate([123,357]):
        e(f'kv-{i}',f'dp{i}','transfer',end=((x-18)/444,0),both=True,color=BLUE)
    e('execute','directory','transfer',start=(1,.5),end=(1,.5),points=[(477,235),(477,404.5)],dashed=True)
    for tier,label,x,color,fill in [('dram','Shared DRAM',18,BLUE,PALE),('ssd','SSD / storage',278,ORANGE,SAND)]:
        g(tier,x,438,184,36,fill=fill,stroke=color)
        n(tier+'-title',label,x+3,440,178,31,bold=True,parent=tier)
        e(tier+'-io','transfer',tier,start=((x+92-18)/444,1),end=(.5,0),both=True,color=color)
    e('demote-fetch','dram','ssd',start=(1,.5),end=(0,.5),both=True,color=ORANGE)
    print(d.save())


if __name__=='__main__':main()
