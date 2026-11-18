#!/usr/bin/env bash
set -euo pipefail
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
aegiskv_root=$(CDPATH= cd -- "$script_dir/../../.." && pwd)
review_dir="$aegiskv_root/exports/teacher-system-design-20260923"
drawio_cli="/home/comp/zhanzhao/.codex/skills/drawio/scripts/drawio-cli"
python3 "$script_dir/build_teacher_design.py"
python3 - "$review_dir" <<'PY'
from pathlib import Path
import subprocess, sys
out = Path(sys.argv[1])
font = Path(subprocess.check_output(['kpsewhich', 'LinLibertine_R.otf'], text=True).strip())
assert font.is_file()
(out/'fontconfig.conf').write_text(f'''<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "fonts.dtd">
<fontconfig><include ignore_missing="yes">/etc/fonts/fonts.conf</include>
<dir>{font.parent}</dir><cachedir>{out}/font-cache</cachedir></fontconfig>
''')
PY
export FONTCONFIG_FILE="$review_dir/fontconfig.conf"
fc-match 'Linux Libertine O' | rg -q 'LinLibertine_R.otf'
for figure in teacher-system-overview teacher-selective-recovery; do
  "$drawio_cli" --user-data-dir="$review_dir/runtime" -x -f png -e -s 2 -b 0 \
    -o "$review_dir/figures/$figure.native.png" "$review_dir/sources/$figure.drawio"
  "$drawio_cli" --user-data-dir="$review_dir/runtime" -x -f pdf -e --crop -b 0 \
    -o "$review_dir/figures/$figure.native.pdf" "$review_dir/sources/$figure.drawio"
done
python3 - "$aegiskv_root" "$review_dir" <<'PY'
from pathlib import Path
import fitz, json, sys
root, out = map(Path, sys.argv[1:])
paper = root/'paper_teacher'
width = (505.89 - 24) / 2 * 72 / 72.27
records = {}
for name in ['teacher-system-overview', 'teacher-selective-recovery']:
    src = fitz.open(out/f'figures/{name}.native.pdf')
    doc = fitz.open()
    page = doc.new_page(width=width, height=src[0].rect.height*width/src[0].rect.width)
    page.show_pdf_page(page.rect, src, 0)
    doc.save(paper/f'figures/{name}.pdf', garbage=4, deflate=True)
    page.get_pixmap(matrix=fitz.Matrix(3,3)).save(paper/f'figures/preview/{name}.png')
    page.get_pixmap(matrix=fitz.Matrix(2,2)).save(out/f'review/{name}.column.png')
    page.get_pixmap(matrix=fitz.Matrix(2,2), colorspace=fitz.csGRAY).save(out/f'review/{name}.gray.png')
    spans = [s for b in page.get_text('dict')['blocks'] if 'lines' in b
             for line in b['lines'] for s in line['spans'] if s['text'].strip()]
    minimum = min(s['size'] for s in spans)
    assert minimum >= 10, (name, minimum)
    records[name] = {'width_mm':page.rect.width/72*25.4,
                     'height_mm':page.rect.height/72*25.4,
                     'minimum_font_pt':minimum, 'embedded_rasters':len(page.get_images())}
(out/'review/figure-metadata.json').write_text(json.dumps(records, indent=2)+'\n')
print(json.dumps(records, indent=2))
PY
