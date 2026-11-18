#!/usr/bin/env python3
"""Submission-oriented architecture/state figures, with native editable objects."""
from pathlib import Path
import xml.etree.ElementTree as ET
import build_storage_design as base
from build_storage_design import Diagram,BLUE,PALE,ORANGE,SAND,GREEN,MINT,LINE,WHITE,GRAY
ROOT=Path(__file__).resolve().parents[3];OUT=ROOT/'exports/system-design-submit-review-20260921';base.OUT=OUT

def overview():
 d=Diagram('system-overview',600,552)
 ET.SubElement(d.root,'mxCell',id='annotations',value='Paper callouts',parent='0');d.origins['annotations']=(0,0)
 def n(*a,**k):k.setdefault('font',25.6);return d.node(*a,**k)
 e=d.edge
 def box(i,x,y,w,h,fill=WHITE,stroke=LINE,parent='1'):
  return n(i,'',x,y,w,h,fill=fill,stroke=stroke,parent=parent,extra='rounded=1;arcSize=6;container=1;collapsible=0;')
 def badge(i,num,x,y):n(i,str(num),x,y,30,30,fill='#151E24',stroke='#151E24',bold=True,parent='annotations',extra='ellipse;shape=ellipse;fontColor=#FFFFFF;')
 box('application',8,6,584,64,GRAY)
 n('app-label','Application',20,9,184,27,bold=True,align='left',parent='application')
 n('request','LLM request',20,39,184,26,align='left',parent='application')
 for key,label,x,y in [('a','A0',244,27),('b','A1',351,7),('c','A2',351,40),('d','A3',511,27)]:
  n(key,label,x,y,45,25,fill=WHITE,stroke=LINE,parent='application')
 for a,b in [('a','b'),('a','c'),('b','d'),('c','d')]:e(a+b,a,b,start=(1,.5),end=(0,.5),color=LINE)
 box('controller',8,85,584,192,'#EAF1F6')
 n('ctrl-label','Controller',20,87,184,27,bold=True,align='left',parent='controller')
 for key,x,w,fill,col,label,num in [('tracker',20,170,MINT,GREEN,'Tracker',1),('router',213,166,'#DDE5EF',BLUE,'Router',2),('master',402,178,PALE,BLUE,'KV Master',3)]:
  box(key,x,123,w,100,fill,col,'controller')
  n(key+'-label',label,x+22,125,w-25,27,bold=True,parent=key)
  badge(key+'-number',num,x-10,118)
 n('predict','GBDT',23,158,77,26,parent='tracker')
 n('cpm','CPM',122,158,65,26,parent='tracker')
 e('predict-cpm','predict','cpm',start=(1,.5),end=(0,.5),dashed=True)
 n('slack','Slack',24,190,75,25,parent='tracker')
 for j,w in enumerate([62,35]):
  n(f'slack-bg{j}','',107,193+12*j,69,7,fill=WHITE,stroke=LINE,parent='tracker')
  n(f'slack-bar{j}','',107,193+12*j,w,7,fill='#8A9D93',parent='tracker')
 n('run-peer','Run / Peer',219,157,153,26,parent='router')
 n('binding','DP0 → DP1',219,190,153,26,parent='router')
 n('cost','WCT / I/O',406,155,170,26,parent='master')
 n('choice','L,K · D,S',406,183,170,25,parent='master')
 for j in range(6):n(f'plan-{j}','',414+j*25,212,18,6,fill=BLUE if j in [0,1,4] else '#C5D6E1',parent='master')
 e('target','router','master',start=(1,.5),end=(0,.5),dashed=True)
 e('slack-value','tracker','master',start=(.85,1),end=(.18,1),points=[(164.5,234),(434.04,234)],dashed=True)
 n('directory','Directory · manifests / log / leases',20,244,560,27,fill=WHITE,stroke=LINE,parent='controller')
 e('progress','application','tracker',start=(.34,1),end=(.5,0),points=[(206.56,117),(105,117)],dashed=True)
 e('requests','application','router',start=(.49,1),end=(.5,0))
 box('engine',8,287,584,258,'#F4F5F1')
 n('engine-label','Engine',20,288,113,27,bold=True,align='left',parent='engine')
 n('normal','Run',179,288,64,26,parent='engine');n('retry-label','Retry',457,288,91,26,parent='engine')
 for i,x in enumerate([20,316]):
  key=f'dp{i}';box(key,x,325,264,141,parent='engine')
  n(key+'-name',f'DP{i} · GPU / HBM',x+5,326,254,26,bold=True,parent=key)
  n(f'adapter{i}','Adapter · budget',x+7,357,250,26,fill=GRAY,stroke=LINE,parent=key)
  for typ,xx,ww,label,fill,col in [('local',x+7,151,'Local KV',MINT,GREEN),('peer',x+170,87,'Peer',PALE,BLUE)]:
   box(f'{typ}{i}',xx,391,ww,40,fill,col,key)
   n(f'{typ}-label{i}',label,xx+2,391,ww-4,25,parent=f'{typ}{i}')
   for rr in range(2):
    for cc in range(5 if typ=='local' else 2):
     tail=typ=='local' and cc==4
     n(f'block-{i}-{typ}-{rr}-{cc}','',xx+8+26*cc,417+7*rr,18,4,fill=SAND if tail else WHITE,stroke=ORANGE if tail else col,parent=f'{typ}{i}')
  n(f'connector{i}','Connector',x+7,439,250,25,fill=WHITE,stroke=BLUE,parent=key)
  e(f'local-io{i}',f'local{i}',f'connector{i}',start=(.5,1),end=(.302,0),color=BLUE,both=True)
  e(f'peer-io{i}',f'connector{i}',f'peer{i}',start=(.826,0),end=(.5,1),color=BLUE,both=True)
 badge('adapter-number',4,12,354);badge('connector-number',5,12,436)
 e('dispatch','router','dp0',start=(0,.46),end=(.5,0),points=[(200,169),(200,239),(13,239),(13,316),(152,316)])
 e('retry','router','dp1',start=(1,.15),end=(.5,0),points=[(389,138),(389,238),(589,238),(589,317),(448,317)],dashed=True,color='#AC4251')
 e('budget','adapter0','master',start=(1,.5),end=(1,.76),points=[(295,370),(295,282),(597,282),(597,199)],dashed=True,both=True)
 e('peer-copy','connector0','connector1',start=(1,.5),end=(0,.5),color=BLUE,both=True)
 n('fabric','',42,482,516,5,fill='#ABC5D6',stroke=BLUE,parent='engine')
 for i,xx in enumerate([152,448]):e(f'backing{i}',f'connector{i}','fabric',start=(.5,1),end=((xx-42)/516,0),color=BLUE,both=True)
 for j in range(3):
  n(f'dram{j}','',54+4*j,500+4*j,195,8,fill=PALE,stroke=BLUE,parent='engine')
  for k in range(6):n(f'chip{j}-{k}','',62+4*j+29*k,502+4*j,20,4,fill='#749DB6',parent='engine')
 for j in range(3):n(f'storage{j}','',428-4*j,497+4*j,74,14,fill=SAND if j==2 else WHITE,stroke=ORANGE,parent='engine',extra='rounded=1;arcSize=15;')
 n('dram-label','Full DRAM',30,518,247,26,bold=True,parent='engine')
 n('storage-label','Shared storage',323,518,257,26,bold=True,parent='engine')
 e('dram-io','fabric','dram0',start=(.215,1),end=(.5,0),color=BLUE,both=True)
 e('storage-io','fabric','storage0',start=(.82,1),end=(.5,0),color=BLUE,both=True)
 e('demote','dram2','storage2',start=(1,.5),end=(0,.5),color=BLUE,both=True)
 return d.save()

def sparse():
 d=Diagram('sparse-recovery',480,420);n,g,e=d.node,d.group,d.edge
 n('a','(a) Full DRAM checkpoint through M',8,4,464,27,bold=True,align='left')
 n('tokens','Historical token blocks',106,38,352,25)
 for l in range(3):
  n(f'l{l}',f'Layer {l+1}',12,78+35*l,89,26,align='left')
  for b in range(5):
   n(f'd-{l}-{b}','Tail' if b==4 else f'B{b}',109+71*b,75+35*l,61,28,fill=SAND if b==4 else PALE,stroke=ORANGE if b==4 else BLUE,extra='dashed=1;' if b==4 else '')
 n('b','(b) Peer on bound DP · L = 2',8,184,464,27,bold=True,align='left')
 for l,blocks in enumerate([[0,3],[0,1,3]]):
  n(f'pl{l}',f'Layer {l+1}',12,222+34*l,89,26,align='left')
  for j,b in enumerate(blocks):n(f'p{l}-{b}',f'B{b}',109+j*58,221+34*l,48,27,fill=MINT,stroke=GREEN)
  n(f'k{l}',f'K = {len(blocks)}',303,222+34*l,150,26)
 n('c','(c) Native layer-1 demand: B0, B2',8,296,464,27,bold=True,align='left')
 n('hit','B0: Peer hit',12,335,191,28,fill=MINT,stroke=GREEN)
 n('miss','B2: backing → H2D',219,335,249,28,fill=PALE,stroke=BLUE)
 # Explicit source identity for miss: data path routes outside the matrix.
 e('miss-fetch','d-0-2','miss',start=(.5,1),end=(1,.5),points=[(281.5,106.5),(476,106.5),(476,349)],dashed=True,color=BLUE)
 n('metadata','Manifest: all layers + selector state',8,384,464,28,fill=GRAY,stroke=LINE)
 return d.save()

if __name__=='__main__':
 for f in [overview,sparse]:print(f())
