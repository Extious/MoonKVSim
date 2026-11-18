from pathlib import Path
import os,subprocess,fitz,json,shutil
ROOT=Path(__file__).resolve().parent
CLI='/home/comp/zhanzhao/.codex/skills/drawio/scripts/drawio-cli'
src=ROOT/'sources/serving_model.drawio';dest=ROOT/'native';dest.mkdir(exist_ok=True)
env=dict(os.environ,FONTCONFIG_FILE=str(ROOT/'fontconfig.conf'))
for fmt in ['pdf','svg','png']:
 target=dest/f'serving_model.drawio.{fmt}'
 args=[CLI,'-x','-f',fmt,'-e','-b','0','-o',str(target)]
 if fmt=='pdf':args.append('--crop')
 if fmt=='png':args.extend(['-s','2'])
 run=subprocess.run(args+[str(src)],env=env,capture_output=True,text=True,timeout=90)
 (dest/f'serving-model-{fmt}.log').write_text(run.stdout+run.stderr)
 assert run.returncode==0 and target.exists(),run.stderr
 print('native',fmt,flush=True)
with fitz.open(dest/'serving_model.drawio.pdf') as doc,fitz.open() as final:
 width=(505.89-24)/2*72/72.27
 p=final.new_page(width=width,height=doc[0].rect.height*width/doc[0].rect.width)
 p.show_pdf_page(p.rect,doc,0)
 final.save(ROOT/'figures/serving_model.pdf',deflate=True)
with fitz.open(ROOT/'figures/serving_model.pdf') as doc:
 page=doc[0]
 for color,cs in [('color',fitz.csRGB),('gray',fitz.csGRAY)]:
  page.get_pixmap(matrix=fitz.Matrix(3,3),colorspace=cs).save(ROOT/f'review/serving_model-{color}.png')
 spans=[s for b in page.get_text('dict')['blocks'] if 'lines' in b for l in b['lines'] for s in l['spans'] if s['text'].strip()]
 assert min(s['size'] for s in spans)>=10,min(s['size'] for s in spans)
 info={'width_mm':page.rect.width*25.4/72,'height_mm':page.rect.height*25.4/72,'min_font_pt':min(s['size'] for s in spans)}
 (ROOT/'review/serving-model-metrics.json').write_text(json.dumps(info,indent=2)+'\n')
 print(info)
shutil.copy2(ROOT/'figures/serving_model.pdf',ROOT.parents[1]/'paper/figures/serving_model.pdf')
