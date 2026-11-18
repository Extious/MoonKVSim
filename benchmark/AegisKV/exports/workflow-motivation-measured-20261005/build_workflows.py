"""Compact role cards with explicit Agent identity and exact dependencies."""
from pathlib import Path
import json
import hashlib
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parent
AEGIS=ROOT.parents[1]
PREVIOUS=AEGIS/'exports/background-motivation-style-20261005'
WIDTH,HEIGHT,W,H=1008,328,210,64
INK,EDGE,TEAL,MINT,BLUE,PALE_BLUE,AMBER,WARM='#243746','#70808A','#39756A','#E1EEE8','#23688D','#DDEBF3','#9B6428','#F3E5D1'


def vertex(root,ident,value,x,y,w,h,style,parent='1'):
    c=ET.SubElement(root,'mxCell',id=ident,value=value,vertex='1',parent=parent,style=style)
    ET.SubElement(c,'mxGeometry',x=str(x),y=str(y),width=str(w),height=str(h),**{'as':'geometry'})


def build():
    cfg=json.loads((PREVIOUS/'sources/figure-contract.json').read_text())
    depfile=AEGIS/'docs/workload-decision-20261004/WORKFLOW_DEPENDENCIES.json'
    dependencies=json.loads(depfile.read_text())['dependencies']
    positions={
      'research':{'C':(24,72),'A':(24,156),'B':(24,240),'E':(274,72),'D':(274,198),'F':(524,198),'G':(774,156)},
      'review':{'A':(24,72),'B':(24,156),'C':(24,240),'D':(274,72),'E':(274,240),'F':(524,72),'G':(524,156),'H':(774,156)}}
    routes={
      'research':{('C','E'):(.5,.5,None),('A','E'):(.35,.75,[254,254]),('A','D'):(.65,.25,[244,244]),
                  ('B','D'):(.35,.75,[264,264]),('B','F'):(.65,.75,[504,504]),('D','F'):(.5,.5,None),
                  ('E','G'):(.5,.25,[744,744]),('F','G'):(.5,.75,[754,754])},
      'review':{('A','D'):(.5,.5,None),('B','D'):(.35,.75,[254,254]),('B','E'):(.65,.25,[264,264]),
                ('C','E'):(.5,.5,None),('D','F'):(.5,.5,None),('D','G'):(.75,.25,[504,504]),
                ('C','G'):(.65,.75,[244,244,504,504]),('E','H'):(.5,.75,[744,744]),
                ('F','H'):(.5,.25,[754,754]),('G','H'):(.5,.5,None)}}
    mx=ET.Element('mxfile',host='app.diagrams.net',type='device')
    for panel in cfg['workflows']:
        app=panel['id']; pos=positions[app]
        d=ET.SubElement(mx,'diagram',id=app,name=panel['title'])
        model=ET.SubElement(d,'mxGraphModel',page='1',pageWidth=str(WIDTH),pageHeight=str(HEIGHT),background='#FFFFFF')
        root=ET.SubElement(model,'root');ET.SubElement(root,'mxCell',id='0');ET.SubElement(root,'mxCell',id='1',parent='0')
        vertex(root,'canvas','',0,0,WIDTH,HEIGHT,'fillColor=#FFFFFF;strokeColor=none;')
        vertex(root,'title',panel['title'],24,8,960,34,
          f'html=0;whiteSpace=wrap;fontFamily=Linux Libertine O;fontSize=23;fontStyle=1;fontColor={INK};align=left;fillColor=none;strokeColor=none;')
        vertex(root,'application-frame','',8,54,992,266,'rounded=1;arcSize=3;fillColor=#FAFBFB;strokeColor=#D8DEE1;strokeWidth=1;')
        last='G' if app=='research' else 'H'
        for letter,(x,y) in pos.items():
            fill,stroke=(MINT,TEAL) if letter in 'ABC' else (WARM,AMBER) if letter==last else (PALE_BLUE,BLUE)
            vertex(root,f'agent-{letter}','',x,y,W,H,
              f'rounded=1;arcSize=5;fillColor={fill};strokeColor={stroke};strokeWidth=1.3;')
            vertex(root,f'badge-{letter}',letter,9,19,28,28,
              f'ellipse;html=0;fontFamily=Linux Libertine O;fontSize=22;fontColor={INK};fillColor=#FFFFFF;strokeColor={stroke};strokeWidth=1;align=center;',f'agent-{letter}')
            vertex(root,f'role-{letter}',panel['roles'][letter],43,2,163,60,
              f'html=0;whiteSpace=wrap;fontFamily=Linux Libertine O;fontSize=22;fontColor={INK};align=center;verticalAlign=middle;fillColor=none;strokeColor=none;spacing=0;',f'agent-{letter}')
        required={(a,b) for b,parents in dependencies[app].items() for a in parents}
        assert set(routes[app])==required
        for (a,b),(sy,ty,xs) in routes[app].items():
            c=ET.SubElement(root,'mxCell',id=f'dependency-{a}-{b}',edge='1',parent='1',source=f'agent-{a}',target=f'agent-{b}',
              style=f'html=0;rounded=0;strokeColor={EDGE};strokeWidth=1.5;endArrow=block;endFill=1;endSize=5;jumpStyle=arc;jumpSize=8;exitX=1;exitY={sy};exitPerimeter=0;entryX=0;entryY={ty};entryPerimeter=0;')
            g=ET.SubElement(c,'mxGeometry',relative='1',**{'as':'geometry'})
            if xs:
                ys=[pos[a][1]+H*sy,pos[b][1]+H*ty] if len(xs)==2 else [pos[a][1]+H*sy,314,314,pos[b][1]+H*ty]
                arr=ET.SubElement(g,'Array',**{'as':'points'})
                for px,py in zip(xs,ys):ET.SubElement(arr,'mxPoint',x=str(px),y=str(py))
    ET.indent(mx)
    out=ROOT/'sources';out.mkdir(exist_ok=True)
    ET.ElementTree(mx).write(out/'application-workflows.drawio',encoding='utf-8',xml_declaration=True)
    cfg['dependencies_source_sha256']=hashlib.sha256(depfile.read_bytes()).hexdigest()
    cfg['style_changes']='Compact two-line role cards, Agent ID badges, subtle application frame, established Libertine/pale-green/blue/amber palette. Colors distinguish roles, not scheduling barriers.'
    (out/'figure-contract.json').write_text(json.dumps(cfg,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':build()
