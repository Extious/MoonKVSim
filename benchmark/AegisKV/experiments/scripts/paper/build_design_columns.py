#!/usr/bin/env python3
"""Detailed single-column AegisKV mechanism diagrams, native Draw.io sources."""
from pathlib import Path
import build_storage_design as base
from build_storage_design import Diagram, INK, LINE, BLUE, PALE, ORANGE, SAND, GREEN, MINT, GRAY, WHITE
OUT=Path(__file__).resolve().parents[3]/'exports/design-figure-revision-20260920'
base.OUT=OUT
RED='#AA3C4D'


def overview():
 d=Diagram('system-overview',480,835);n,g,e=d.node,d.group,d.edge
 # Application objects and explicit parallel dependence, rather than just a title.
 g('app',8,8,464,106,fill='#F2F6F8')
 n('app-title','Agent workflow',20,13,440,26,bold=True,align='left')
 n('request','Request\nIDs',20,51,114,52,fill=WHITE,stroke=LINE,parent='app')
 for key,lab,x,y in [('a0','A0',164,65),('a1','A1',270,46),('a2','A2',270,82),('a3','A3',390,65)]:
  n(key,lab,x,y,54,27,fill=WHITE,stroke=LINE,parent='app')
 for i,a,b in [('01','a0','a1'),('02','a0','a2'),('13','a1','a3'),('23','a2','a3')]:
  e(i,a,b,start=(1,.5),end=(0,.5),color=LINE)
 # Controller modules, with their actual intermediate state.
 g('control',8,143,464,235,fill='#F8F9FC')
 g('tracker',25,156,194,108,fill=MINT,stroke=GREEN,parent='control')
 n('tracker-title','1  Tracker',32,164,180,26,bold=True,parent='tracker')
 n('gbdt','GBDT → CPM',30,197,184,26,parent='tracker')
 n('slack','Slack: 8 / 0 s',30,230,184,24,parent='tracker')
 g('master',260,156,194,133,fill=PALE,stroke=BLUE,parent='control')
 n('master-title','3  KV Master',266,164,182,27,bold=True,parent='master')
 n('master-rule','Value → rent',266,198,182,25,parent='master')
 for row,label,yy in [('d','D',236),('s','S',262)]:
  n(row+'tag',label,268,yy,23,22,parent='master')
  for i in range(5):
   n(f'cand-{row}-{i}','',302+i*27,yy+2,21,17,fill=(PALE if row=='d' else SAND) if i%3 else WHITE,
     stroke=BLUE if row=='d' else ORANGE,parent='master')
 g('router',25,300,194,65,fill='#E7EEF4',stroke=BLUE,parent='control')
 n('router-title','2  Router',32,305,180,26,bold=True,parent='router')
 n('router-rule','Locality + load',31,335,182,23,parent='router')
 g('directory',260,316,194,50,fill=WHITE,stroke=LINE,parent='control')
 n('dir-name','Directory + log',264,317,186,24,parent='directory')
 n('frontier','M = 128',265,341,184,22,parent='directory')
 e('app-progress','a2','tracker',start=(.5,1),end=(.5,0),points=[(297,130),(122,130)],dashed=True)
 e('request-dispatch','request','router',start=(0,.5),end=(0,.5),points=[(2,77),(2,332.5)])
 e('slack-master','tracker','master',start=(1,.62),end=(0,.50),dashed=True)
 e('master-directory','master','directory',dashed=True)
 e('directory-router','directory','router',start=(0,.5),end=(1,.6),dashed=True)
 # Symmetric data planes with actual layer/block working state, no Peer region.
 for i,x in enumerate([20,258]):
  dp=f'dp{i}';g(dp,x,418,202,155,fill='#F7FAFB',stroke=LINE)
  n(dp+'name',f'DP {i}',x+4,425,194,27,bold=True,parent=dp)
  n(dp+'hbm','Execution HBM',x+5,458,192,25,parent=dp)
  for r,lab in enumerate(['L1','L2','…']):
   yy=493+r*21
   n(f'layer{i}{r}',lab,x+8,yy-2,33,23,align='left',parent=dp)
   for c in range(6):
    n(f'kv{i}{r}{c}','',x+48+c*24,yy,19,15,fill=SAND if c==5 else MINT,
      stroke=BLUE if c in ((r+i)%4,3) else ('#BA985D' if c==5 else '#ABC4BA'),parent=dp,
      extra='strokeWidth=2.2;' if c in ((r+i)%4,3) else '')
 e('run','router','dp0',points=[(122,400),(121,400)],color=BLUE)
 e('retry','router','dp1',start=(.8,1),end=(.5,0),
   points=[(180.2,397),(359,397)],dashed=True,color=RED)
 n('run-label','Run',35,387,66,25,fill=WHITE)
 n('retry-label','Retry',275,380,75,25,fill=WHITE)
 g('transfer',36,604,408,34,fill='#EAF0F5',stroke=BLUE)
 n('transfer-name','Engine hooks + KV transfer',40,607,400,27,bold=True,parent='transfer')
 for i,x in enumerate([121,359]):
  e(f'bytes{i}',f'dp{i}','transfer',start=(.5,1),end=((x-36)/408,0),both=True,color=BLUE)
 e('execute','directory','transfer',start=(1,.5),end=(1,.5),
   points=[(477,341),(477,621)],dashed=True)
 for tier,label,yy,color,fill in [('dram','Shared DRAM',669,BLUE,PALE),('ssd','SSD / shared storage',756,ORANGE,SAND)]:
  g(tier,36,yy,408,63,fill=fill,stroke=color)
  n(tier+'-name',label,43,yy+3,394,25,bold=True,parent=tier)
  for j,lab in enumerate(['x','y','z','…']):
   n(f'{tier}{j}',lab,72+86*j,yy+33,64,26,fill=WHITE,stroke=color,parent=tier)
 e('backup','transfer','dram',both=True,color=BLUE)
 e('tier-move','dram','ssd',both=True,color=ORANGE)
 # Short labels sit off the data path; caption explains line semantics.
 n('backup-label','Backup / restore',43,641,175,25)
 n('tier-label','Demote / fetch',43,733,173,23)
 return d.save()


def sparse():
 d=Diagram('sparse-recovery',480,423);n,g,e=d.node,d.group,d.edge
 n('a','(a) Complete history, mixed tiers',10,4,460,29,bold=True)
 n('history','History M',110,36,260,27);n('tail','Tail N',391,36,74,27)
 for c in range(5):n(f'col{c}',f'B{c}',111+c*54,69,44,25)
 dram={(0,0),(0,3),(1,0),(1,2),(2,0)}
 for r in range(3):
  yy=100+r*35;n(f'layer{r}',f'Layer {r+1}',13,yy,96,28,align='left')
  for c in range(5):
   here=(r,c) in dram;n(f'kv{r}{c}','D' if here else 'S',111+c*54,yy,42,27,
      fill=PALE if here else SAND,stroke=BLUE if here else ORANGE)
  n(f'tail{r}','',409,yy,37,27,stroke=LINE,extra='dashed=1;')
 n('key','D: DRAM | S: SSD',31,210,420,26)
 n('b','(b) Layer 1: prediction vs. demand',10,251,460,28,bold=True)
 for row,label,yy,selected in [('p','Predict',293,{0,3}),('q','Actual',336,{0,2})]:
  n(row+'title',label,14,yy,90,28,align='left')
  for c in range(5):
   miss=row=='q' and c==2
   n(f'{row}{c}',f'B{c}',117+c*63,yy,50,29,bold=c in selected,
      fill=SAND if miss else (PALE if c in selected else WHITE),stroke=ORANGE if miss else LINE,
      extra='strokeWidth=2.2;' if c in selected else '')
 n('fetch','B2: fetch from SSD before use',30,387,420,28,fill=SAND,stroke=ORANGE)
 e('miss','fetch','q2',start=(.55,0),end=(.5,1),color=ORANGE)
 return d.save()


def rental():
 d=Diagram('rental-competition',480,366);n,g,e=d.node,d.group,d.edge
 n('title','One byte-unit of DRAM required',10,4,460,28,bold=True)
 g('incoming',19,45,442,58,fill=PALE,stroke=BLUE)
 n('incoming-name','Incoming x · size 1',24,48,432,25,bold=True,parent='incoming')
 n('incoming-credit','Trial credit: 6 → 4',24,76,432,24,parent='incoming')
 n('price','Trial rent +2 per byte-unit',20,113,440,26)
 g('q',15,146,298,143,fill='#F7F9FA',stroke=BLUE)
 n('qtitle','Safe victims Q',22,150,284,26,bold=True,parent='q')
 for key,x,label,start,end in [('y',23,'Resident y',2,0),('z',167,'Resident z',5,3),('reader',327,'Read lease',1,0)]:
  parent='q' if key!='reader' else '1'; yy=188 if key!='reader' else 188
  n(key+'t',label,x,yy,133,26,bold=True,parent=parent)
  n(key+'credit',f'{start} → {end}',x+3,yy+35,127,29,fill=SAND if key=='y' else GRAY,stroke=ORANGE if key=='y' else LINE,parent=parent)
  n(key+'end','Propose' if key=='y' else ('Keep' if key=='z' else 'Not in Q'),x,yy+71,133,25,parent=parent)
 n('size','All groups have size 1',28,301,424,23)
 n('commit','Check value → reserve → demote y',16,335,448,28,fill=WHITE,stroke=LINE)
 return d.save()


def lifecycle():
 d=Diagram('checkpoint-lifecycle',480,472);n,g,e=d.node,d.group,d.edge
 n('a','(a) Frontier requires all dependencies',8,3,464,29,bold=True)
 n('old','M = 128',13,40,126,29,fill=PALE,stroke=BLUE)
 n('pending','129–192 pending',168,40,288,29,fill=SAND,stroke=ORANGE)
 for r,(lab,ready) in enumerate([('L1',True),('L2',False),('L3',True)]):
  yy=80+r*27;n(f'layer{r}',lab,23,yy,50,24,align='left')
  n(f'old{r}','',80,yy,148,22,fill=PALE,stroke=BLUE)
  n(f'new{r}','Ready' if ready else 'Pending',239,yy,205,22,fill=MINT if ready else SAND,stroke=GREEN if ready else ORANGE)
 n('frontier','Frontier stays at M = 128',26,166,428,26,bold=True)
 n('b','(b) Same object x; location changes',9,211,462,27,bold=True)
 for col,(lab,x) in enumerate([('Copy',124),('Commit',241),('Release',358)]):n(f'stage{col}',lab,x,244,107,25,bold=True)
 for row,(lab,yy) in enumerate([('DRAM x',278),('SSD x',312)]):
  n(f'tier{row}',lab,10,yy,106,27,align='left')
  for col in range(3):
   value= ('Live' if col<2 else 'Freed') if row==0 else ('Pending' if col==0 else 'Valid')
   n(f'copy{row}{col}',value,124+117*col,yy,105,27,fill=PALE if row==0 and col<2 else (SAND if row==1 else GRAY),stroke=LINE)
 n('readers','Release only after old readers drain',15,350,450,26)
 n('c','(c) Last copy: publish a fallback first',8,394,464,28,bold=True)
 for i,(lab,x) in enumerate([('Fallback',16),('Drain',183),('Delete x',350)]):
  n(f'f{i}',lab,x,434,114,30,fill=WHITE,stroke=LINE)
  if i:e(f'fe{i}',f'f{i-1}',f'f{i}',start=(1,.5),end=(0,.5))
 return d.save()

if __name__=='__main__':
 for fn in [overview,sparse,rental,lifecycle]:print(fn())
