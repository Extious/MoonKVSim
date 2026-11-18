#!/usr/bin/env python3
from pathlib import Path
import subprocess
import os
import fitz

ROOT=Path(__file__).resolve().parent
CLI='/home/comp/zhanzhao/.codex/skills/drawio/scripts/drawio-cli'
env=dict(os.environ,FONTCONFIG_FILE=str(ROOT/'fontconfig.conf'))
for fmt in ['pdf','png','svg']:
    dest=ROOT/'native'/f'evaluation-protocol.drawio.{fmt}'
    cmd=[CLI,'-x','-f',fmt,'-e','-b','0','-o',str(dest)]
    if fmt=='pdf':cmd+=['--crop']
    result=subprocess.run(cmd+[str(ROOT/'sources/evaluation-protocol.drawio')],env=env,capture_output=True,text=True,timeout=90)
    (ROOT/'native'/f'evaluation-protocol-{fmt}.log').write_text(result.stdout+result.stderr)
    assert result.returncode==0 and dest.exists(),fmt
    print('Exported protocol',fmt,flush=True)
with fitz.open(ROOT/'native/evaluation-protocol.drawio.pdf') as src:
    with fitz.open() as doc:
        w=168/25.4*72
        p=doc.new_page(width=w,height=src[0].rect.height*w/src[0].rect.width)
        p.show_pdf_page(p.rect,src,0)
        doc.save(ROOT/'evaluation-protocol.pdf')
        p.get_pixmap(matrix=fitz.Matrix(2,2),alpha=False).save(ROOT/'review/evaluation-protocol-color.png')
        p.get_pixmap(matrix=fitz.Matrix(2,2),colorspace=fitz.csGRAY,alpha=False).save(ROOT/'review/evaluation-protocol-gray.png')
