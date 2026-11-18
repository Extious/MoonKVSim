#!/usr/bin/env bash
set -euo pipefail
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
aegiskv_root=$(CDPATH= cd -- "$script_dir/../../.." && pwd)
review_dir="$aegiskv_root/exports/system-overview-dp-tp-20260923"
drawio_cli="/home/comp/zhanzhao/.codex/skills/drawio/scripts/drawio-cli"
mkdir -p "$review_dir/sources" "$review_dir/review"
python3 "$script_dir/build_dp_tp_overview.py"
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
"$drawio_cli" -x -f png -e -s 2 -b 0 -o "$review_dir/system-overview.png" "$review_dir/sources/system-overview.drawio"
"$drawio_cli" -x -f pdf -e --crop -b 0 -o "$review_dir/system-overview.native.pdf" "$review_dir/sources/system-overview.drawio"
"$drawio_cli" -x -f svg -e -b 0 -o "$review_dir/system-overview.svg" "$review_dir/sources/system-overview.drawio"
python3 - "$aegiskv_root" "$review_dir" <<'PY'
from pathlib import Path
import fitz, sys
root, out = map(Path, sys.argv[1:])
src = fitz.open(out/'system-overview.native.pdf')
text = src[0].get_text()
assert all(t in text for t in ['TP0', 'TP1', 'shard 0', 'shard 1', 'KV Master'])
width = (505.89 - 24) / 2 * 72 / 72.27
doc = fitz.open()
page = doc.new_page(width=width, height=src[0].rect.height*width/src[0].rect.width)
page.show_pdf_page(page.rect, src, 0)
doc.save(root/'paper/figures/system-overview.pdf', garbage=4, deflate=True)
page.get_pixmap(matrix=fitz.Matrix(3,3)).save(root/'paper/figures/preview/system-overview.png')
page.get_pixmap(matrix=fitz.Matrix(1,1)).save(out/'review/system-overview.column-72dpi.png')
page.get_pixmap(matrix=fitz.Matrix(2,2)).save(out/'review/system-overview.column-144dpi.png')
page.get_pixmap(colorspace=fitz.csGRAY, matrix=fitz.Matrix(2,2)).save(out/'review/system-overview.gray.png')
print('Placed figure size:', tuple(page.rect))
PY
