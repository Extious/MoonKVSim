from pathlib import Path
import hashlib, json
import fitz
from PIL import Image, ImageDraw, ImageFont

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").is_file())
OUT = Path(__file__).resolve().parent
PAPER = ROOT / 'benchmark/AegisKV/paper'
STEMS = ['serving_model', 'agent_value_a', 'agent_value_b', 'kv_value',
         'system-overview', 'master-selection', 'recovery-pipeline', 'depth-bandwidth',
         'eval-online-wct', 'eval-retry-length', 'eval-native-topk']

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

manifest = {'source': str(PAPER.relative_to(ROOT)), 'figures': [], 'source_files': {}}
for name in ['main.tex', 'background.tex', 'motivation.tex', 'system_design.tex',
             'evaluation.tex', 'abstract.tex', 'introduction.tex', 'references.bib',
             'main.pdf']:
    p = PAPER / name
    manifest['source_files'][str(p.relative_to(ROOT))] = sha(p)
for stem in STEMS:
    src = PAPER / 'figures' / f'{stem}.pdf'
    dst = OUT / 'assets' / f'{stem}.png'
    with fitz.open(src) as doc:
        assert len(doc) == 1, (src, len(doc))
        page = doc[0]
        scale = 1800 / page.rect.width
        page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False).save(dst)
        item = {'name': stem, 'source': str(src.relative_to(ROOT)), 'source_sha256': sha(src),
                'asset': str(dst.relative_to(OUT)), 'asset_sha256': sha(dst),
                'pdf_size_pt': list(page.rect)[2:], 'width_px': 1800}
        manifest['figures'].append(item)

font_path = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
fonts = list(Path('/usr/share/fonts').rglob('DejaVuSans.ttf'))
if fonts:
    font_path = str(fonts[0])
font = lambda n: ImageFont.truetype(font_path, n)
# A restrained editorial cover, not an experimental or architectural figure.
cover = Image.new('RGB', (1800, 600), '#142838')
d = ImageDraw.Draw(cover)
d.rectangle((0, 0, 20, 600), fill='#65b1ac')
d.text((132, 198), 'AegisKV', font=font(112), fill='#f7f4ec')
d.text((140, 340), 'Workflow-aware KV Recovery', font=font(33), fill='#9dccca')
for row in range(4):
    for col in range(7):
        x, y = 1230 + col*61, 198 + row*61
        color = '#65b1ac' if (row+col)%5 == 0 else '#274653'
        d.rounded_rectangle((x,y,x+40,y+40),radius=6,fill=color)
cover.save(OUT/'assets/cover.png')

# Thumbnail contact sheet. The full-resolution assets are retained for inspection.
w, h = 640, 730
sheet = Image.new('RGB', (w*3, h*4), '#edf0f2')
draw = ImageDraw.Draw(sheet)
for i,stem in enumerate(STEMS):
    img = Image.open(OUT/'assets'/f'{stem}.png').convert('RGB')
    img.thumbnail((w-30,h-70))
    x,y=(i%3)*w,(i//3)*h
    draw.text((x+16,y+12),stem,font=font(23),fill='#172a38')
    sheet.paste(img,(x+(w-img.width)//2,y+55))
sheet.save(OUT/'review/figures-contact.png')
manifest['cover']={'asset':'assets/cover.png','sha256':sha(OUT/'assets/cover.png')}
(OUT/'source-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'figures':len(STEMS),'output':str(OUT),'contact':'review/figures-contact.png'},indent=2))
