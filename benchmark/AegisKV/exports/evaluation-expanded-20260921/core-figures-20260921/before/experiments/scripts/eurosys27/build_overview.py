#!/usr/bin/env python3
"""Editable single-column DRAM/storage architecture. No Peer-HBM backup."""
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'exports/eurosys-complete-20260920'


def main():
    doc=ET.Element('mxfile',host='app.diagrams.net',version='31.1.5')
    page=ET.SubElement(doc,'diagram',name='DRAM and storage',id='dram-storage')
    model=ET.SubElement(page,'mxGraphModel',page='1',pageWidth='500',pageHeight='518',background='#ffffff')
    root=ET.SubElement(model,'root')
    ET.SubElement(root,'mxCell',id='0');ET.SubElement(root,'mxCell',id='1',parent='0',value='Architecture')

    def node(key,text,x,y,w,h,fill='#FFFFFF',font=23,bold=False,stroke='#536677'):
        n=ET.SubElement(root,'mxCell',id=key,value=text,vertex='1',parent='1',style=
          f'rounded=1;arcSize=6;whiteSpace=wrap;html=0;fontFamily=Helvetica;fontSize={font};'
          f'fontStyle={int(bold)};fontColor=#172E40;strokeColor={stroke};fillColor={fill};strokeWidth=1.5;spacing=3;')
        ET.SubElement(n,'mxGeometry',x=str(x),y=str(y),width=str(w),height=str(h),**{'as':'geometry'})

    def edge(key,src,dst,label='',style='',pts=()):
        n=ET.SubElement(root,'mxCell',id=key,source=src,target=dst,edge='1',parent='1',value=label,
          style='edgeStyle=orthogonalEdgeStyle;rounded=0;html=0;endArrow=block;endFill=1;'
          'fontFamily=Helvetica;fontSize=22;labelBackgroundColor=#FFFFFF;strokeWidth=1.8;strokeColor=#526775;'+style)
        g=ET.SubElement(n,'mxGeometry',relative='1',**{'as':'geometry'})
        if pts:
            a=ET.SubElement(g,'Array',**{'as':'points'})
            for x,y in pts:ET.SubElement(a,'mxPoint',x=str(x),y=str(y))

    node('canvas','',0,0,500,518,stroke='none')
    node('workflow','Workflow DAG + progress',15,6,470,43,'#EDF2F6',bold=True)
    node('tracker','Tracker\nTime / slack',15,77,218,70,'#E4EDF5')
    node('master','KV Master\nTier decisions',267,77,218,70,'#E1EDE8')
    edge('dagtracker','workflow','tracker',style='exitX=0.23;exitY=1;entryX=0.5;entryY=0;')
    edge('values','tracker','master',style='exitX=1;exitY=0.5;entryX=0;entryY=0.5;')
    node('router','Router + surviving directory / token log',15,174,470,52,'#F2F3F6',font=22)
    edge('publish','master','router',style='exitX=0.5;exitY=1;entryX=0.77;entryY=0;dashed=1;')
    node('dp0','DP0: live KV\nAdapter + I/O',15,253,218,70,'#E7EEF4')
    node('dp1','DP1: live KV\nAdapter + I/O',267,253,218,70,'#E7EEF4')
    edge('dispatch','router','dp0',style='exitX=0.23;exitY=1;entryX=0.5;entryY=0;')
    edge('retry','router','dp1',style='exitX=0.77;exitY=1;entryX=0.5;entryY=0;')
    node('dram','Shared DRAM pool\nFast reusable copies',15,366,470,62,'#DDECE5')
    edge('save','dp0','dram','save',style='exitX=0.5;exitY=1;entryX=0.23;entryY=0;')
    edge('load','dram','dp1','restore',style='exitX=0.77;exitY=0;entryX=0.5;entryY=1;')
    node('storage','SSD / shared storage\nCapacity tier',15,454,470,62,'#F4E7D7')
    edge('demote','dram','storage',style='exitX=0.25;exitY=1;entryX=0.25;entryY=0;')
    edge('fetch','storage','dram',style='exitX=0.75;exitY=0;entryX=0.75;entryY=1;')
    ET.indent(doc,space='  ');OUT.mkdir(parents=True,exist_ok=True)
    path=OUT/'storage-overview.drawio';ET.ElementTree(doc).write(path,encoding='utf-8',xml_declaration=True)
    print(path)


if __name__=='__main__':main()
