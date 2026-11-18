#!/usr/bin/env python3
"""Lighten the three-band Overview without changing its resource topology."""
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / 'exports/design-observations-compact-20260921'
SOURCE = ROOT / 'exports/three-tier-rental-design-20260921/sources/system-overview.drawio'

def main():
    tree = ET.parse(SOURCE)
    labels = {
        'request': 'LLM calls',
        'run-peer': 'Run / Peer',
        'cost': 'Value + rent',
        'choice': 'Layers / blocks',
        'directory': 'Manifests · logs · leases',
        'dp0-name': 'DP0 · GPU/HBM', 'dp1-name': 'DP1 · GPU/HBM',
        'adapter0': 'Adapter (AIMD)', 'adapter1': 'Adapter (AIMD)',
        'dram-label': 'Shared DRAM',
    }
    bold = {'app-label', 'ctrl-label', 'engine-label',
            'tracker-label', 'router-label', 'master-label'}
    for c in tree.findall('.//mxCell'):
        ident = c.get('id')
        if ident in labels:
            c.set('value', labels[ident])
        style = dict(x.split('=', 1) for x in c.get('style', '').split(';') if '=' in x)
        if c.get('vertex'):
            style['fontFamily'] = 'Linux Libertine O'
            style['fontSize'] = '25.4'
            style['fontStyle'] = '1' if ident in bold or ident.endswith('-number') else '0'
            style['strokeWidth'] = '1.0'
            if ident.endswith('-number'):
                # Smaller black markers retain the same readable type size.
                g=c.find('mxGeometry')
                g.set('width','27'); g.set('height','27')
                g.set('x',str(float(g.get('x'))+1.5))
                g.set('y',str(float(g.get('y'))+1.5))
        elif c.get('edge'):
            style['strokeWidth'] = '1.4'
            style['endSize'] = '4'
        if style:
            # Keep standalone style tokens such as ellipse.
            atoms=[x for x in c.get('style','').split(';') if x and '=' not in x]
            c.set('style',';'.join(atoms+[f'{k}={v}' for k,v in style.items()])+';')
    dest=OUT/'sources/system-overview.drawio'
    dest.parent.mkdir(parents=True,exist_ok=True)
    ET.indent(tree)
    tree.write(dest,encoding='utf-8',xml_declaration=True)
    print(dest)

if __name__=='__main__':main()
