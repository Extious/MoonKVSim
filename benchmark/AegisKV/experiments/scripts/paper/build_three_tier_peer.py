#!/usr/bin/env python3
"""Native diagrams for full checkpoints plus optional Peer-HBM hot replicas."""
from pathlib import Path
import xml.etree.ElementTree as ET
import build_storage_design as base
from build_storage_design import Diagram,BLUE,PALE,ORANGE,SAND,GREEN,MINT,LINE,WHITE,GRAY
ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'exports/three-tier-peer-restored-20260921'
base.OUT=OUT

def overview():
 d=Diagram('system-overview',600,694)
 def n(*a,**k):k.setdefault('font',26);return d.node(*a,**k)
 e=d.edge
 def box(i,x,y,w,h,fill,stroke=LINE,parent='1'):
  return n(i,'',x,y,w,h,fill=fill,stroke=stroke,parent=parent,extra='rounded=1;arcSize=6;container=1;collapsible=0;')
 box('application',8,8,584,72,GRAY)
 n('app-label','Application',20,10,190,30,bold=True,align='left',parent='application')
 n('app-detail','Agent workflow',20,43,214,30,align='left',parent='application')
 for key,label,x,y in [('a','A',252,29),('b','B',365,10),('c','C',365,47),('d','D',514,29)]:
  n(key,label,x,y,42,28,fill=WHITE,stroke=LINE,parent='application')
 for a,b in [('a','b'),('a','c'),('b','d'),('c','d')]:e(a+b,a,b,start=(1,.5),end=(0,.5),color=LINE)
 box('controller',8,98,584,256,'#EAF1F6')
 n('ctrl-label','Controller',20,100,200,31,bold=True,align='left',parent='controller')
 box('tracker',20,139,320,66,MINT,GREEN,'controller')
 n('tracker-name','Workflow Tracker',25,141,310,29,bold=True,parent='tracker')
 n('gbdt','GBDT',26,174,105,27,parent='tracker')
 n('slack','CPM / Slack',171,174,162,27,parent='tracker')
 e('prediction','gbdt','slack',start=(1,.5),end=(0,.5),dashed=True)
 box('master',20,230,320,110,PALE,BLUE,'controller')
 n('master-name','KV Master',25,231,310,30,bold=True,parent='master')
 n('wct','WCT / I/O',28,266,142,29,fill=WHITE,stroke=BLUE,parent='master')
 n('revalue','Revalue',184,266,147,29,fill=WHITE,stroke=BLUE,parent='master')
 n('master-plan','L, K · D/S · joint DAG',27,304,306,29,parent='master')
 e('slack-input','tracker','master',start=(.12,1),end=(.12,0),dashed=True)
 n('slack-label','Slack',97,205,95,25,parent='controller')
 box('router',366,139,214,98,'#DDE5EF',BLUE,'controller')
 n('router-name','Router',369,142,208,29,bold=True,parent='router')
 n('router-normal','Load / locality',369,174,208,29,parent='router')
 n('router-fail','Bind DP / retry',369,206,208,28,parent='router')
 box('directory',366,266,214,74,WHITE,LINE,'controller')
 n('directory-name','Directory',370,268,206,29,bold=True,parent='directory')
 n('directory-data','Log / manifests',370,303,206,29,parent='directory')
 e('target','router','master',start=(0,.81),end=(1,.4),points=[(354,218.38),(354,274)],dashed=True)
 e('metadata','master','directory',start=(1,.86),end=(0,.79),dashed=True,both=True)
 e('versions','directory','router',start=(.5,0),end=(.5,1),dashed=True)
 e('app-tracker','application','tracker',start=(.32,1),end=(.5,0),dashed=True,points=[(194.88,132),(180,132)])
 e('app-router','application','router',start=(.80,1),end=(.5,0))
 box('engine',8,371,584,315,'#F4F5F1')
 n('engine-name','Engine',20,374,120,31,bold=True,align='left',parent='engine')
 for i,x in enumerate([20,316]):
  w=f'dp{i}';box(w,x,416,264,158,WHITE,parent='engine')
  n(w+'-name',f'DP {i} · GPU / HBM',x+5,418,254,29,bold=True,parent=w)
  n(f'adapter{i}','Adapter · budget',x+6,451,252,28,fill=GRAY,stroke=LINE,parent=w)
  for k,xx,label,fill,color in [('local',x+6,'Local KV',MINT,GREEN),('peer',x+140,'Peer KV',PALE,BLUE)]:
   box(f'{k}{i}',xx,485,118,50,fill,color,w)
   n(f'{k}-label{i}',label,xx+1,485,116,28,parent=f'{k}{i}')
   for row in range(2):
    for col in range(4 if k=='local' else 2):
     n(f'{k}-{i}-{row}-{col}','',xx+9+25*col,516+8*row,18,5,fill=WHITE,stroke=color,parent=f'{k}{i}')
  n(f'connector{i}','Connector',x+6,542,252,27,fill=WHITE,stroke=BLUE,parent=w)
  e(f'peer-access{i}',f'connector{i}',f'peer{i}',start=(193/252,0),end=(.5,1),color=BLUE,both=True)
  e(f'local-copy{i}',f'local{i}',f'connector{i}',start=(.5,1),end=(59/252,0),color=BLUE,both=True)
 e('run','router','dp0',start=(0,.40),end=(.5,0),points=[(349,178.2),(349,408),(152,408)])
 e('retry','router','dp1',start=(1,.40),end=(.5,0),points=[(589,178.2),(589,409),(448,409)],dashed=True,color='#AC4251')
 n('run-label','Run',165,375,82,29,parent='engine')
 n('retry-label','Retry',456,375,90,29,parent='engine')
 e('plan','master','engine',start=(.76,1),end=(.436,0),dashed=True)
 e('budget-feedback','adapter0','master',start=(0,.5),end=(0,.5),points=[(3,465),(3,285)],dashed=True)
 e('peer-transfer','connector0','connector1',start=(1,.5),end=(0,.5),color=BLUE,both=True)
 n('fabric','',46,604,508,5,fill='#ABC5D6',stroke=BLUE,parent='engine')
 for i,x in enumerate([20,316]):e(f'backing{i}',f'connector{i}','fabric',start=(.5,1),end=((x+132-46)/508,0),color=BLUE,both=True)
 for j in range(3):
  n(f'dram{j}','',43+5*j,625+5*j,209,10,fill=PALE,stroke=BLUE,parent='engine')
  for k in range(7):n(f'chip{j}-{k}','',50+5*j+k*28,627+5*j,19,6,fill='#749DB6',parent='engine')
 n('dram-text','Full DRAM',27,652,242,29,bold=True,parent='engine')
 for j in range(3):n(f'storage{j}','',429-5*j,623+5*j,76,18,fill=SAND if j==2 else WHITE,stroke=ORANGE,parent='engine',extra='rounded=1;arcSize=10;')
 n('storage-text','Shared storage',323,652,257,29,bold=True,parent='engine')
 e('dram-io','fabric','dram0',start=(.20,1),end=(.5,0),color=BLUE,both=True)
 e('storage-io','fabric','storage0',start=(.83,1),end=(.5,0),color=BLUE,both=True)
 e('whole-demote','dram2','storage2',start=(1,.5),end=(0,.5),color=BLUE,both=True)
 return d.save()

def sparse():
 d=Diagram('sparse-recovery',480,407);n,g,e=d.node,d.group,d.edge
 n('title','Full checkpoint, selective Peer replica',6,4,468,29,bold=True)
 n('dram-name','DRAM: complete through M',10,39,460,28,bold=True)
 for l in range(3):
  n(f'l{l}',f'Layer {l+1}',14,78+l*40,93,28,align='left')
  for b in range(5):
   tail=b==4
   n(f'd-{l}-{b}','Tail' if tail else f'B{b}',114+70*b,76+l*40,59,31,fill=GRAY if tail else PALE,stroke=LINE if tail else BLUE,extra='dashed=1;' if tail else '')
 n('peer-name','Peer: L = 2, K = 2 per layer',10,201,460,28,bold=True)
 for l in range(2):
  n(f'pl{l}',f'Layer {l+1}',14,238+l*35,93,28,align='left')
  for j,b in enumerate([0,3]):n(f'p-{l}-{b}',f'B{b}',119+79*j,237+l*35,61,29,fill=MINT,stroke=GREEN)
 n('mismatch','Layer 1 needs B0/B2 → fetch B2',10,321,460,28)
 n('storage','Whole-checkpoint demotion → storage',10,364,460,29,fill=SAND,stroke=ORANGE)
 return d.save()

def lifecycle():
 d=Diagram('checkpoint-lifecycle',480,420);n,g,e=d.node,d.group,d.edge
 n('title','Commit coverage before release',8,3,464,30,bold=True)
 n('a','(a) Full checkpoint frontier',14,42,452,29,bold=True,align='left')
 n('frontier','M = 128 · tokens 129–192 pending',16,79,448,29,fill=PALE,stroke=BLUE)
 n('publish','All dependencies commit → M = 192',16,120,448,29)
 n('b','(b) Whole-checkpoint demotion',14,167,452,29,bold=True,align='left')
 n('copy','DRAM → copy / verify → storage',16,204,448,29,fill=SAND,stroke=ORANGE)
 n('drain','Commit → redirect → drain → free',16,242,448,29)
 n('c','(c) Release a Peer hot replica',14,289,452,29,bold=True,align='left')
 n('backing','Full DRAM/storage backing valid?',16,328,448,29,fill=MINT,stroke=GREEN)
 n('free','Yes → redirect reads → drain → free',16,368,448,29)
 return d.save()

def competition():
 tree=ET.parse(ROOT/'exports/direct-value-design-20260921/sources/placement-competition.drawio')
 labels={'incoming-name':'Peer x · size 1','safe-title':'Unpinned victims Q','y-name':'Release y','z-name':'Release z'}
 for cell in tree.findall('.//mxCell'):
  if cell.get('id') in labels:cell.set('value',labels[cell.get('id')])
 target=OUT/'sources/placement-competition.drawio';target.parent.mkdir(parents=True,exist_ok=True)
 tree.write(target,encoding='utf-8',xml_declaration=True)
 return target

if __name__=='__main__':
 for f in [overview,sparse,lifecycle,competition]:print(f())
