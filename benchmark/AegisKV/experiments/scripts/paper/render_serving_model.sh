#!/usr/bin/env bash
set -euo pipefail

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
aegiskv_root=$(CDPATH= cd -- "$script_dir/../../.." && pwd)
review_dir="$aegiskv_root/exports/serving-model-paper-20260923"
drawio_cli="/home/comp/zhanzhao/.codex/skills/drawio/scripts/drawio-cli"
mkdir -p "$review_dir/sources" "$review_dir/review"
python3 "$script_dir/build_serving_model.py" --output "$review_dir/sources/serving_model.drawio"

# Scope font discovery to this exporter; do not change the user's system fonts.
python3 - "$review_dir" <<'PY'
from pathlib import Path
import subprocess, sys
out = Path(sys.argv[1])
font = Path(subprocess.check_output(['kpsewhich', 'LinLibertine_R.otf'], text=True).strip())
assert font.is_file(), font
(out/'fontconfig.conf').write_text(f'''<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "fonts.dtd">
<fontconfig>
 <include ignore_missing="yes">/etc/fonts/fonts.conf</include>
 <dir>{font.parent}</dir>
 <cachedir>{out}/font-cache</cachedir>
</fontconfig>
''')
PY
export FONTCONFIG_FILE="$review_dir/fontconfig.conf"
fc-match 'Linux Libertine O' | rg -q 'LinLibertine_R.otf'
"$drawio_cli" -x -f png -e -s 2 -b 0 -o "$review_dir/serving_model.png" "$review_dir/sources/serving_model.drawio"
"$drawio_cli" -x -f pdf -e --crop -b 0 -o "$review_dir/serving_model.native.pdf" "$review_dir/sources/serving_model.drawio"
"$drawio_cli" -x -f svg -e -b 0 -o "$review_dir/serving_model.svg" "$review_dir/sources/serving_model.drawio"

python3 - "$aegiskv_root" "$review_dir" <<'PY'
from pathlib import Path
import fitz, sys
root, out = map(Path, sys.argv[1:])
src = fitz.open(out/'serving_model.native.pdf')
# Chromium embeds this CFF OTF as Type 3 glyphs. Verify fontconfig above;
# native PNG/PDF visual review remains necessary. Text is still extractable.
figure_text = src[0].get_text()
assert all(label in figure_text for label in ('Workflow runtime', 'Router', 'Reused KV', 'New KV', 'A2', 'B3, D2', 'C4', 'D1', 'E1'))
assert 'A2, B3' not in figure_text and 'D5' not in figure_text
assert 'histories' not in figure_text.lower() and 'tool' not in figure_text.lower()
# Current acmart column: (505.89 - 24) / 2 TeX points, converted to PDF points.
width = (505.89 - 24) / 2 * 72 / 72.27
doc = fitz.open()
page = doc.new_page(width=width, height=src[0].rect.height*width/src[0].rect.width)
page.show_pdf_page(page.rect, src, 0)
doc.save(root/'paper/figures/serving_model.pdf', garbage=4, deflate=True)
page.get_pixmap(matrix=fitz.Matrix(3,3)).save(root/'paper/figures/preview/serving_model.png')
page.get_pixmap(matrix=fitz.Matrix(1,1)).save(out/'review/serving_model.column-72dpi.png')
page.get_pixmap(matrix=fitz.Matrix(2,2)).save(out/'review/serving_model.column-144dpi.png')
page.get_pixmap(colorspace=fitz.csGRAY, matrix=fitz.Matrix(2,2)).save(out/'review/serving_model.gray.png')
print('Placed figure size:', tuple(page.rect))
PY
